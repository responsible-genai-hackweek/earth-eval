from __future__ import annotations

from dataclasses import dataclass, fields

import numpy as np


FLOAT_STAT_FIELDS = (
    "sum_w",
    "sum_w_error",
    "sum_w_abs_error",
)
INTEGER_STAT_FIELDS = (
    "valid_pixels",
    "expected_pixels",
    "observed_pixels",
    "n_cell_days",
    "n_days",
    "n_calendar_days",
)
ALL_STAT_FIELDS = FLOAT_STAT_FIELDS + INTEGER_STAT_FIELDS


@dataclass
class StatsBlock:
    """Additive sufficient statistics for every grid cell plus the domain.

    Slots 0..N-1 are individual MERRA-2 cells in row-major grid order. Slot N
    is the complete domain. Keeping the domain slot separately preserves the
    number of days on which at least one cell was paired.
    """

    sum_w: np.ndarray
    sum_w_error: np.ndarray
    sum_w_abs_error: np.ndarray
    valid_pixels: np.ndarray
    expected_pixels: np.ndarray
    observed_pixels: np.ndarray
    n_cell_days: np.ndarray
    n_days: np.ndarray
    n_calendar_days: np.ndarray

    @classmethod
    def empty(cls, n_cells: int) -> "StatsBlock":
        size = n_cells + 1
        floats = [np.zeros(size, dtype=np.float64) for _ in FLOAT_STAT_FIELDS]
        integers = [np.zeros(size, dtype=np.int64) for _ in INTEGER_STAT_FIELDS]
        return cls(*floats, *integers)

    @property
    def size(self) -> int:
        return int(self.sum_w.size)

    @property
    def n_cells(self) -> int:
        return self.size - 1

    @property
    def domain_slot(self) -> int:
        return self.n_cells

    def copy(self) -> "StatsBlock":
        return StatsBlock(*(getattr(self, item.name).copy() for item in fields(self)))

    def merge(self, other: "StatsBlock") -> None:
        if other.size != self.size:
            raise ValueError("cannot merge statistics blocks of different sizes")
        for name in ALL_STAT_FIELDS:
            getattr(self, name)[:] += getattr(other, name)

    def validate(self, expected_calendar_days: int | None = None) -> None:
        shapes = {getattr(self, name).shape for name in ALL_STAT_FIELDS}
        if shapes != {(self.size,)}:
            raise ValueError("statistics arrays have inconsistent shapes")
        for name in FLOAT_STAT_FIELDS:
            values = getattr(self, name)
            if not np.isfinite(values).all():
                raise ValueError(f"statistics field {name} contains non-finite values")
        for name in INTEGER_STAT_FIELDS:
            values = getattr(self, name)
            if np.any(values < 0):
                raise ValueError(f"statistics field {name} contains negative values")
        if np.any(self.sum_w < 0) or np.any(self.sum_w_abs_error < -1e-12):
            raise ValueError("weight and absolute-error sums must be nonnegative")
        if np.any(np.abs(self.sum_w_error) > self.sum_w_abs_error + 1e-10):
            raise ValueError("absolute weighted error is smaller than signed error")
        if not np.allclose(self.sum_w, self.valid_pixels, rtol=0, atol=1e-8):
            raise ValueError("weight sums do not match paired MODSCAG pixel counts")
        if np.any(self.valid_pixels > self.expected_pixels):
            raise ValueError("valid MODSCAG support exceeds expected support")
        if np.any(self.observed_pixels > self.valid_pixels):
            raise ValueError("direct observations exceed valid MODSCAG support")
        if np.any(self.n_days > self.n_calendar_days):
            raise ValueError("paired-day count exceeds calendar-day count")
        if np.any(self.n_cell_days[: self.n_cells] != self.n_days[: self.n_cells]):
            raise ValueError("individual-cell paired and cell-day counts disagree")
        if expected_calendar_days is not None and np.any(
            self.n_calendar_days != expected_calendar_days
        ):
            raise ValueError(
                f"statistics do not contain exactly {expected_calendar_days} calendar days"
            )
        domain = self.domain_slot
        for name in (
            *FLOAT_STAT_FIELDS,
            "valid_pixels",
            "expected_pixels",
            "observed_pixels",
            "n_cell_days",
        ):
            values = getattr(self, name)
            cell_total = values[:domain].sum()
            if name in FLOAT_STAT_FIELDS:
                matches = np.isclose(values[domain], cell_total, rtol=1e-12, atol=1e-8)
            else:
                matches = values[domain] == cell_total
            if not matches:
                raise ValueError(f"domain {name} does not equal the cell sum")


def update_stats(
    stats: StatsBlock,
    merra: np.ndarray,
    modscag: np.ndarray,
    valid_pixels: np.ndarray,
    expected_pixels: np.ndarray,
    observed_pixels: np.ndarray,
) -> bool:
    expected_shape = merra.shape
    for name, values in (
        ("modscag", modscag),
        ("valid_pixels", valid_pixels),
        ("expected_pixels", expected_pixels),
        ("observed_pixels", observed_pixels),
    ):
        if values.shape != expected_shape:
            raise ValueError(f"{name} shape {values.shape} differs from {expected_shape}")
    if merra.size != stats.n_cells:
        raise ValueError("statistics block size differs from the target grid")

    stats.n_calendar_days += 1
    flat_merra = merra.ravel()
    flat_modscag = modscag.ravel()
    flat_valid = valid_pixels.ravel()
    flat_expected = expected_pixels.ravel()
    flat_observed = observed_pixels.ravel()
    paired = (
        np.isfinite(flat_merra)
        & np.isfinite(flat_modscag)
        & (flat_valid > 0)
        & (flat_expected > 0)
    )
    if not np.any(paired):
        return False

    slots = np.flatnonzero(paired)
    errors = flat_merra[paired] - flat_modscag[paired]
    weights = flat_valid[paired].astype(np.float64)
    weighted_error = weights * errors
    weighted_abs_error = weights * np.abs(errors)

    stats.sum_w[slots] += weights
    stats.sum_w_error[slots] += weighted_error
    stats.sum_w_abs_error[slots] += weighted_abs_error
    stats.valid_pixels[slots] += flat_valid[paired]
    stats.expected_pixels[slots] += flat_expected[paired]
    stats.observed_pixels[slots] += flat_observed[paired]
    stats.n_cell_days[slots] += 1
    stats.n_days[slots] += 1

    domain = stats.domain_slot
    stats.sum_w[domain] += weights.sum()
    stats.sum_w_error[domain] += weighted_error.sum()
    stats.sum_w_abs_error[domain] += weighted_abs_error.sum()
    stats.valid_pixels[domain] += flat_valid[paired].sum()
    stats.expected_pixels[domain] += flat_expected[paired].sum()
    stats.observed_pixels[domain] += flat_observed[paired].sum()
    stats.n_cell_days[domain] += int(paired.sum())
    stats.n_days[domain] += 1
    return True


def merge_blocks(blocks: list[StatsBlock] | tuple[StatsBlock, ...]) -> StatsBlock:
    if not blocks:
        raise ValueError("at least one statistics block is required")
    merged = StatsBlock.empty(blocks[0].n_cells)
    for block in blocks:
        merged.merge(block)
    merged.validate()
    return merged


def metrics_for_slot(stats: StatsBlock, slot: int) -> dict[str, object]:
    if not 0 <= slot < stats.size:
        raise IndexError(slot)
    weight = float(stats.sum_w[slot])
    bias = None if weight <= 0 else 100.0 * float(stats.sum_w_error[slot]) / weight
    mae = None if weight <= 0 else 100.0 * float(stats.sum_w_abs_error[slot]) / weight
    if bias is not None and (mae is None or mae < -1e-12 or abs(bias) > mae + 1e-10):
        raise ValueError(f"metric sanity check failed for slot {slot}")
    expected = int(stats.expected_pixels[slot])
    valid = int(stats.valid_pixels[slot])
    observed = int(stats.observed_pixels[slot])
    calendar_days = int(stats.n_calendar_days[slot])
    paired_days = int(stats.n_days[slot])
    return {
        "bias_pp": bias,
        "mae_pp": mae,
        "sum_weight": weight,
        "sum_weighted_error": float(stats.sum_w_error[slot]),
        "sum_weighted_absolute_error": float(stats.sum_w_abs_error[slot]),
        "n_cell_days": int(stats.n_cell_days[slot]),
        "n_days": paired_days,
        "n_calendar_days": calendar_days,
        "n_missing_reference_days": calendar_days - paired_days,
        "paired_modscag_pixel_days": valid,
        "expected_modscag_pixel_days": expected,
        "direct_observation_pixel_days": observed,
        "support_fraction": None if expected == 0 else valid / expected,
        "direct_observation_fraction": None if valid == 0 else observed / valid,
    }
