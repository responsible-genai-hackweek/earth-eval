"""Fixed scientific-contract constants for the MERRA-2 vs STC-MODSCAG comparison.

See .claude/skills/snow-hydrology-fsca-evaluation/references/scientific-contract.md
for the authoritative description of every value below. Do not change any of
these without an explicit, documented scientific-contract review.
"""

from __future__ import annotations

import hashlib
import json

# --- Water year range -------------------------------------------------------

WY_START = 2010
WY_END = 2023
N_WATER_YEARS = WY_END - WY_START + 1  # 14

# --- Domain grid -------------------------------------------------------------

N_LON_CELLS = 8
N_LAT_CELLS = 9
N_CELLS = N_LON_CELLS * N_LAT_CELLS  # 72

LON_SPACING = 0.625
LAT_SPACING = 0.5

CELL_LON_CENTERS = tuple(round(-108.75 + LON_SPACING * i, 6) for i in range(N_LON_CELLS))
CELL_LAT_CENTERS = tuple(round(37.0 + LAT_SPACING * i, 6) for i in range(N_LAT_CELLS))

# Complete cell edges for the full domain (outermost boundary).
DOMAIN_LON_EDGE_MIN = round(CELL_LON_CENTERS[0] - LON_SPACING / 2, 6)  # -109.0625
DOMAIN_LON_EDGE_MAX = round(CELL_LON_CENTERS[-1] + LON_SPACING / 2, 6)  # -104.0625
DOMAIN_LAT_EDGE_MIN = round(CELL_LAT_CENTERS[0] - LAT_SPACING / 2, 6)  # 36.75
DOMAIN_LAT_EDGE_MAX = round(CELL_LAT_CENTERS[-1] + LAT_SPACING / 2, 6)  # 41.25

assert DOMAIN_LON_EDGE_MIN == -109.0625
assert DOMAIN_LON_EDGE_MAX == -104.0625
assert DOMAIN_LAT_EDGE_MIN == 36.75
assert DOMAIN_LAT_EDGE_MAX == 41.25

# --- Products ----------------------------------------------------------------

MODSCAG_PRODUCT = "STC_MODSCGDRF_HIST"
MODSCAG_VERSION = "1"
MODSCAG_VARIABLE = "snow_fraction"  # stored 0-100 percent
MODSCAG_DIAGNOSTIC_VARIABLE = "days_without_observation"
MODSCAG_NATIVE_PIXEL_M = 500  # approximate equal-area MODIS sinusoidal pixel size

MERRA_COLLECTION = "M2T1NXLND"
MERRA_VERSION = "5.12.4"
MERRA_VARIABLE = "FRSNO"  # stored 0-1 fraction
MERRA_TIME_INDEX = 15  # 15:00-16:00 UTC mean, timestamped 15:30 UTC

# MERRA filename stream boundaries.
MERRA_STREAM_EARLY = 300  # through calendar year 2010
MERRA_STREAM_LATE = 400  # from calendar year 2011
MERRA_STREAM_REPROCESSED = 401
MERRA_STREAM_REPROCESSED_MONTHS = frozenset(
    {
        (2020, 9),
        (2021, 6),
        (2021, 7),
        (2021, 8),
        (2021, 9),
    }
)

# --- Comparison rules ---------------------------------------------------------

ERROR_SIGN = "MERRA_MINUS_MODSCAG"  # error = M - R
SUPPORT_THRESHOLD = 0.8  # minimum fraction of expected fine pixels required

# --- Composite/significance masks ---------------------------------------------

COMPOSITE_FSCA_MASK_THRESHOLD = 0.05
SIGNIFICANCE_FSCA_MASK_THRESHOLD = 0.10

# --- Wet/dry composite groups ---------------------------------------------------

WET_WATER_YEARS = frozenset({2011, 2017, 2019, 2023})
DRY_WATER_YEARS = frozenset({2012, 2013, 2015, 2018})
COMPOSITE_MONTHS = (11, 12, 1, 2, 3, 4, 5)  # November - May, water-year month order

SIGNIFICANCE_DF = len(WET_WATER_YEARS) - 1  # 3, four annual replicates
SIGNIFICANCE_ALPHA = 0.05

# --- Execution -----------------------------------------------------------------

DEFAULT_MAX_WORKERS = 16
FTP_SEMAPHORE_SLOTS = 8
FTP_BACKOFF_SECONDS = (5, 10, 20)

# --- Checkpoint schema -----------------------------------------------------------

CHECKPOINT_SCHEMA_VERSION = 1

# NOTE on `sum_w_r`: this column is not among the 13 fields named in the
# original operational plan
# (y/repos/agent-test/shared/plans/2026-08-26-merra-modscag-wy2010-2023.md,
# section 3). It is added here as a documented, intentional departure because
# NMB and NMAE (normalized bias/MAE relative to paired MODSCAG signal,
# required by statistics-and-figures.md for the wet/dry composite and
# significance figures) need sum(w*R) as their denominator, and that
# sufficient statistic cannot be reconstructed from bias_pp/mae_pp alone.
# sum_w_r / sum_w is also exactly the "composite MODIS fSCA" statistic used
# for the 0.05/0.10 masking thresholds, so it serves both purposes at once.
CHECKPOINT_COLUMNS = (
    "sum_w",
    "sum_w_error",
    "sum_w_abs_error",
    "sum_w_r",
    "valid_pixels",
    "expected_pixels",
    "observed_pixels",
    "n_cell_days",
    "n_days",
    "n_calendar_days",
    "bias_pp",
    "mae_pp",
    "support_fraction",
    "direct_observation_fraction",
)

ROWS_PER_MONTH = N_CELLS + 1  # 72 cells + 1 domain row
N_MONTHS = N_WATER_YEARS * 12  # 168

EXPECTED_OVERALL_ROWS = 240
EXPECTED_PER_CELL_ROWS = 17280

# --- Known data gaps (used only for validation, not injected as behavior) -------

KNOWN_MODSCAG_ALL_FILL_GAP = ("2022-10-10", "2022-10-27")
KNOWN_WY2023_MISSING_DOMAIN_DAYS = 18

# --- Example-day illustration (not part of the metric pipeline) ----------------

EXAMPLE_DAYS = (
    ("2011-01-15", "high_snow"),
    ("2015-06-01", "low_snow"),
)

# --- Persisted artifact paths (relative to repo root) ---------------------------

RESULTS_DIR = "results"
CHECKPOINT_SUBDIR = "water_year_2010_2023_monthly_checkpoints"
OVERALL_STATS_FILENAME = "water_year_2010_2023_overall_stats.csv"
PIXEL_STATS_FILENAME = "water_year_2010_2023_pixel_stats.csv"
BIAS_MAE_FIGURE_FILENAME = "water_year_2010_2023_bias_mae.png"


def _fingerprint_payload() -> dict:
    """Everything that defines the scientific comparison, in one canonical dict."""
    return {
        "wy_start": WY_START,
        "wy_end": WY_END,
        "cell_lon_centers": CELL_LON_CENTERS,
        "cell_lat_centers": CELL_LAT_CENTERS,
        "domain_edges": (
            DOMAIN_LON_EDGE_MIN,
            DOMAIN_LON_EDGE_MAX,
            DOMAIN_LAT_EDGE_MIN,
            DOMAIN_LAT_EDGE_MAX,
        ),
        "modscag_product": MODSCAG_PRODUCT,
        "modscag_version": MODSCAG_VERSION,
        "modscag_variable": MODSCAG_VARIABLE,
        "merra_collection": MERRA_COLLECTION,
        "merra_version": MERRA_VERSION,
        "merra_variable": MERRA_VARIABLE,
        "merra_time_index": MERRA_TIME_INDEX,
        "error_sign": ERROR_SIGN,
        "support_threshold": SUPPORT_THRESHOLD,
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
    }


def config_fingerprint() -> str:
    """SHA-256 hex digest of the scientific configuration.

    Any change to a value in `_fingerprint_payload` changes this digest, which
    invalidates every previously written checkpoint (by design: a checkpoint
    written under a different scientific contract must never be silently
    reused).
    """
    payload = json.dumps(_fingerprint_payload(), sort_keys=True, default=list)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
