"""The frozen scientific configuration and its fingerprint.

Two kinds of setting live in this module and they are deliberately kept apart.

:class:`ComparisonConfig` holds the scientific choices - products, timing,
domain, thresholds, masks, period. Changing any of them makes a different
experiment, so the whole object is hashed into a fingerprint that every
checkpoint carries and is validated against.

:class:`OperationalConfig` holds how fast and how parallel the run is. Those
settings change nothing about the answer, so they are deliberately excluded from
the fingerprint: raising the worker count must not invalidate a month of work.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date

__all__ = [
    "ComparisonConfig",
    "OperationalConfig",
    "ReferenceEra",
    "default_config",
]

#: The archive refuses about ten simultaneous FTP connections from one address.
FTP_CONNECTION_CAP = 9


@dataclass(frozen=True)
class ReferenceEra:
    """One reference product covering a contiguous span of dates.

    Eras exist because no single published reference product spans the whole
    requested period. Recording them explicitly keeps the seam visible in the
    fingerprint, in checkpoint metadata, and in figure captions, instead of
    letting two products be silently read as one homogeneous record.
    """

    product: str
    version: str
    start: date
    end: date | None = None

    def contains(self, day: date) -> bool:
        return day >= self.start and (self.end is None or day <= self.end)

    def as_key(self) -> dict[str, str | None]:
        return {
            "product": self.product,
            "version": self.version,
            "start": self.start.isoformat(),
            "end": self.end.isoformat() if self.end else None,
        }


@dataclass(frozen=True)
class ComparisonConfig:
    """Scientific choices that define the experiment."""

    # --- domain -----------------------------------------------------------
    lon_min: float = -109.0
    lon_max: float = -104.0
    lat_min: float = 37.0
    lat_max: float = 41.0

    # --- model ------------------------------------------------------------
    model_collection: str = "M2T1NXLND"
    model_version: str = "5.12.4"
    model_variable: str = "FRSNO"
    model_time_index: int = 15

    # --- reference --------------------------------------------------------
    reference_eras: tuple[ReferenceEra, ...] = ()
    reference_variable: str = "snow_fraction"
    reference_diagnostic: str = "days_without_observation"
    reference_scale: float = 100.0
    reference_valid_max: float = 100.0
    tiles: tuple[str, ...] = ("h09v04", "h09v05", "h10v04")

    # --- comparison rules -------------------------------------------------
    error_sign: str = "model_minus_reference"
    support_threshold: float = 0.8
    composite_min_reference_fsca: float = 0.05
    significance_min_reference_fsca: float = 0.10

    # --- period -----------------------------------------------------------
    water_years: tuple[int, ...] = (2023,)
    months: tuple[int, ...] = (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)

    schema_version: str = "1"

    def __post_init__(self) -> None:
        if not 0.0 < self.support_threshold <= 1.0:
            raise ValueError(
                f"support_threshold must be in (0, 1], got {self.support_threshold}"
            )
        for name in ("composite_min_reference_fsca", "significance_min_reference_fsca"):
            value = getattr(self, name)
            if not 0.0 <= value < 1.0:
                raise ValueError(f"{name} must be in [0, 1), got {value}")
        for month in self.months:
            if not 1 <= month <= 12:
                raise ValueError(f"month must be in 1..12, got {month}")
        if not self.months:
            raise ValueError("months must not be empty")
        if not self.tiles:
            raise ValueError("tiles must not be empty - no reference coverage")
        if self.model_time_index < 0:
            raise ValueError(
                f"model_time_index must be non-negative, got {self.model_time_index}"
            )
        if not self.water_years:
            raise ValueError("water_years must not be empty")
        if self.error_sign not in ("model_minus_reference", "reference_minus_model"):
            raise ValueError(f"unknown error_sign {self.error_sign!r}")
        if self.lon_min >= self.lon_max or self.lat_min >= self.lat_max:
            raise ValueError("domain bounds must be ordered min < max")

    # --- reference era resolution ----------------------------------------

    def resolve_era(self, day: date) -> ReferenceEra:
        """Return the reference era covering ``day``.

        A date with no era is fatal rather than silently skipped: it means the
        requested period runs past the reference record.
        """
        for era in self.reference_eras:
            if era.contains(day):
                return era
        raise ValueError(f"no reference era covers {day.isoformat()}")

    def eras_used_by_water_year(self, wy: int) -> tuple[str, ...]:
        """Return the distinct reference products used within one water year."""
        from .calendars import enumerate_dates

        seen: list[str] = []
        for day in enumerate_dates((wy,), self.months):
            product = self.resolve_era(day).product
            if product not in seen:
                seen.append(product)
        return tuple(seen)

    @property
    def year_contrast_is_product_confounded(self) -> bool:
        """True when each water year is covered by a different single product.

        When this holds, a year-versus-year contrast cannot be separated from
        the change of reference product, and every figure comparing the years
        must say so.
        """
        per_year = [self.eras_used_by_water_year(wy) for wy in self.water_years]
        singles = [products[0] for products in per_year if len(products) == 1]
        return len(singles) == len(per_year) > 1 and len(set(singles)) == len(singles)

    # --- fingerprint ------------------------------------------------------

    def as_dict(self) -> dict:
        """Return the canonical scientific description of this configuration."""
        payload = dataclasses.asdict(self)
        payload["reference_eras"] = [era.as_key() for era in self.reference_eras]
        return payload

    def fingerprint(self) -> str:
        """SHA-256 over the canonical scientific configuration.

        Checkpoints carry this digest. A checkpoint whose digest differs was
        produced under different science and is refused, not reused.
        """
        canonical = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OperationalConfig:
    """How the run is executed. Deliberately absent from the fingerprint."""

    workers: int = 16
    ftp_slots: int = 8
    daily_retries: int = 4
    month_attempts: int = 2
    max_runtime_minutes: int | None = None
    ftp_backoff_seconds: tuple[int, ...] = (5, 10, 20)

    def __post_init__(self) -> None:
        if self.workers < 1:
            raise ValueError(f"workers must be >= 1, got {self.workers}")
        if not 1 <= self.ftp_slots < FTP_CONNECTION_CAP + 1:
            raise ValueError(
                f"ftp_slots must be in 1..{FTP_CONNECTION_CAP}, got {self.ftp_slots}; "
                "the archive refuses about ten simultaneous connections per address"
            )
        if self.max_runtime_minutes is not None and self.max_runtime_minutes <= 0:
            raise ValueError("max_runtime_minutes must be positive when set")


#: The clean historical MODSCAG record. Water year 2023 lies entirely inside it,
#: which is why WY2023 is the satellite-validation year: no product splice, no
#: near-real-time era, and no algorithm-version break is involved.
STC_MODSCAG_HIST = ReferenceEra(
    product="STC_MODSCGDRF_HIST",
    version="1",
    start=date(2000, 3, 1),
    end=date(2023, 9, 30),
)


def default_config(**overrides) -> ComparisonConfig:
    """Configuration for the WY2023 satellite validation.

    This is the *secondary* analysis. The primary comparison is MERRA-2 versus
    ERA5 snowpack over WY1981-WY2026; see ``plan/SNOWPACK_REANALYSIS_PLAN.md``.
    """
    base = {"reference_eras": (STC_MODSCAG_HIST,)}
    base.update(overrides)
    return ComparisonConfig(**base)
