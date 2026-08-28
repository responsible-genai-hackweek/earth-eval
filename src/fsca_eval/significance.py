"""Cellwise wet/dry composite NMB and its significance test.

Years, not spatial cells, are the independent replicates: each of the 4 wet
and 4 dry water years contributes one Nov-May composite NMB per cell, and a
one-sample two-sided t-test (df=3, popmean=0) is run per cell per group. The
plotted composite NMB itself is the pooled sufficient-statistic value across
all years in the group -- never the mean of the four yearly NMBs -- per
"combine sufficient statistics before deriving metrics". The two computations
share the same per-year building blocks but serve different purposes:
replicate values for the test, pooled value for display.

Per CLAUDE.md: this figure uses raw two-sided p < 0.05 hatching with no FDR
correction. Do not add FDR here without an explicit scientific-contract review.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from . import aggregate, config, metrics

CheckpointIndex = dict  # (water_year: int, calendar_month: int) -> list[SufficientStats], length N_CELLS


def build_index(loaded: list[aggregate.LoadedCheckpoint]) -> CheckpointIndex:
    return {(lc.water_year, lc.month): lc.cell_stats for lc in loaded}


def combine_composite_months(
    index: CheckpointIndex, water_year: int, months: tuple[int, ...] = config.COMPOSITE_MONTHS
) -> list:
    combined = [metrics.SufficientStats() for _ in range(config.N_CELLS)]
    for month in months:
        cell_stats = index[(water_year, month)]
        for cell_id in range(config.N_CELLS):
            combined[cell_id] = combined[cell_id] + cell_stats[cell_id]
    return combined


def yearly_nmb_matrix(
    index: CheckpointIndex, water_years: frozenset, months: tuple[int, ...] = config.COMPOSITE_MONTHS
) -> np.ndarray:
    """Shape (len(water_years), N_CELLS): one Nov-May composite NMB per year, per cell."""
    rows = []
    for water_year in sorted(water_years):
        combined = combine_composite_months(index, water_year, months)
        rows.append([metrics.nmb(s) for s in combined])
    return np.array(rows, dtype=np.float64)


def _pooled_composite_metric(
    index: CheckpointIndex, water_years: frozenset, metric_fn, months: tuple[int, ...] = config.COMPOSITE_MONTHS
) -> np.ndarray:
    """Shape (N_CELLS,): metric_fn derived once from sufficient stats pooled
    across all years/months in the group -- never an average of already
    -derived per-year values.
    """
    pooled = [metrics.SufficientStats() for _ in range(config.N_CELLS)]
    for water_year in water_years:
        combined = combine_composite_months(index, water_year, months)
        for cell_id in range(config.N_CELLS):
            pooled[cell_id] = pooled[cell_id] + combined[cell_id]
    return np.array([metric_fn(s) for s in pooled], dtype=np.float64)


def pooled_composite_nmb(
    index: CheckpointIndex, water_years: frozenset, months: tuple[int, ...] = config.COMPOSITE_MONTHS
) -> np.ndarray:
    """Shape (N_CELLS,): NMB from sufficient stats pooled across all years/months
    in the group -- the value actually plotted, not an average of yearly NMBs.
    """
    return _pooled_composite_metric(index, water_years, metrics.nmb, months)


def pooled_composite_fsca(
    index: CheckpointIndex, water_years: frozenset, months: tuple[int, ...] = config.COMPOSITE_MONTHS
) -> np.ndarray:
    """Shape (N_CELLS,): pooled MODSCAG composite fSCA for the group, used for
    the 0.10 low-snow masking threshold on the significance figure.
    """
    return _pooled_composite_metric(index, water_years, metrics.composite_fsca, months)


def one_sample_pvalues(yearly_values: np.ndarray) -> np.ndarray:
    """Two-sided one-sample t-test per cell (columns), popmean=0.

    A cell with any NaN replicate (that year had no paired cell-days) yields
    NaN, propagated deliberately rather than dropped -- dropping a replicate
    would silently change the df from the fixed 4-replicate design.
    """
    with np.errstate(invalid="ignore"):
        result = stats.ttest_1samp(yearly_values, popmean=0.0, axis=0, nan_policy="propagate")
    return np.asarray(result.pvalue, dtype=np.float64)


@dataclass(frozen=True)
class WetDrySignificance:
    wet_composite_nmb: np.ndarray  # shape (N_CELLS,)
    dry_composite_nmb: np.ndarray
    wet_pvalues: np.ndarray
    dry_pvalues: np.ndarray
    wet_hatch: np.ndarray  # bool, shape (N_CELLS,), True where raw p < alpha
    dry_hatch: np.ndarray


def wet_dry_significance(
    index: CheckpointIndex, months: tuple[int, ...] = config.COMPOSITE_MONTHS
) -> WetDrySignificance:
    wet_years = config.WET_WATER_YEARS
    dry_years = config.DRY_WATER_YEARS
    assert len(wet_years) - 1 == config.SIGNIFICANCE_DF
    assert len(dry_years) - 1 == config.SIGNIFICANCE_DF

    wet_yearly = yearly_nmb_matrix(index, wet_years, months)
    dry_yearly = yearly_nmb_matrix(index, dry_years, months)

    wet_pvalues = one_sample_pvalues(wet_yearly)
    dry_pvalues = one_sample_pvalues(dry_yearly)

    return WetDrySignificance(
        wet_composite_nmb=pooled_composite_nmb(index, wet_years, months),
        dry_composite_nmb=pooled_composite_nmb(index, dry_years, months),
        wet_pvalues=wet_pvalues,
        dry_pvalues=dry_pvalues,
        wet_hatch=wet_pvalues < config.SIGNIFICANCE_ALPHA,
        dry_hatch=dry_pvalues < config.SIGNIFICANCE_ALPHA,
    )


def monthly_wet_dry_significance(
    index: CheckpointIndex, months: tuple[int, ...] = config.COMPOSITE_MONTHS
) -> dict:
    """One WetDrySignificance per single month, keyed by calendar month.

    Each month's test is identical in method to the pooled Nov-May test --
    same df=3, same raw two-sided p<0.05, no FDR -- just windowed to that
    single month's four annual replicates instead of the Nov-May composite.
    """
    return {month: wet_dry_significance(index, months=(month,)) for month in months}


def monthly_composite_metric(
    index: CheckpointIndex, water_years: frozenset, metric_fn, months: tuple[int, ...] = config.COMPOSITE_MONTHS
) -> dict:
    """One pooled metric array (shape (N_CELLS,)) per single month, keyed by
    calendar month -- e.g. NMAE or composite fSCA, which the contract does
    not require a per-month significance test for (only NMB is hatched).
    """
    return {month: _pooled_composite_metric(index, water_years, metric_fn, months=(month,)) for month in months}
