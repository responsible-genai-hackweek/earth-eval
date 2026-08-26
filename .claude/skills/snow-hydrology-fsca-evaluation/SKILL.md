---
name: snow-hydrology-fsca-evaluation
description: Use when a task touches the Colorado MERRA-2 versus MODSCAG fractional snow-covered area (fSCA) comparison in merra_modis_comparison/ - reproducing it, auditing it, extending it, plotting it, or explaining what it measured - and before any change that would alter the compared products, water-year range, 15Z time match, spatial support threshold, error sign, normalization masks, or wet/dry year groups.
---

# Snow Hydrology fSCA Evaluation

Daily modeled snow-covered fraction (MERRA-2 `FRSNO`) is evaluated against a
satellite reference (STC-MODSCAG `snow_fraction`) over 72 MERRA-2 cells in
Colorado for water years 2010-2023.

**Core principle: the scientific contract is fixed; the pipeline is
negotiable.** Every engineering decision here exists to make 5,113 days
tractable *without* moving a contract term. A change that moves one is a new
experiment — say so out loud and write it down before implementing it.

## Read before acting

- [references/scientific-contract.md](references/scientific-contract.md) — the
  fixed terms: domain, products, time match, regridding rule, metric equations,
  missingness policy, wet/dry groups.
- `merra_modis_comparison/research/FSCA_PRODUCT_NOTES.md` — why these products,
  what their fill and gap-filling semantics are, what was rejected.
- `merra_modis_comparison/plan/FSCA_PIPELINE_PLAN.md` — the WY2023 trial spec.
- `merra_modis_comparison/plan/MULTIYEAR_2010_2023_PLAN.md` — the WY2010-2023
  spec, including the checkpoint contract.

Verify any claim in a README or docstring against code and checkpoint metadata
before relying on it.

## Route to the domain skill

| Task | Skill |
|------|-------|
| Binning 500 m pixels into MERRA cells, support thresholds, boundary rules | `modis-merra-regridding` |
| Earthdata/NSIDC access, resumable parallel runs, checkpoint reuse, reprocessing decisions | `earthdata-streaming-checkpoints` |
| Bias/MAE/NMB, significance tests, low-snow masks, maps, figure interpretation | `snow-bias-statistics-and-figures` |

## Invariants — never change these silently

1. Reference is STC-MODSCAG v1 `snow_fraction`; model is MERRA-2
   `M2T1NXLND` v5.12.4 `FRSNO` at time index 15 (15:00-16:00 UTC).
2. Aggregate 500 m MODSCAG **up** to the native MERRA-2 grid. Never interpolate
   MERRA-2 down to MODIS resolution.
3. Require 80% daily MODSCAG support per cell-day; weight pooled errors by
   valid fine-pixel count.
4. Error sign is MERRA-2 minus MODSCAG.
5. Water years 2010-2023, no extension without a product-continuity review.
6. Stream daily inputs; persist only monthly sufficient statistics and final
   outputs.
7. Water years — not spatial cells or pixels — are the independent replicates
   for cellwise temporal tests.
8. The wet/dry NMB figure hatches raw two-sided `p < 0.05`, uncorrected.
9. Credentials, `.netrc` contents, tokens, and raw granules never reach
   repository outputs.

## Order of work

1. **Research** the exact product, variable, timestamp, coordinate system, and
   missing-data semantics. Prefer the existing research notes over a fresh
   external search.
2. **Plan**: name which contract entries stay fixed and which single one the
   task proposes to change. Update a plan file before any material redesign.
3. **Implement** the smallest change that preserves checkpoint resumability and
   sufficient-statistic consistency.
4. **Reuse** validated checkpoints whenever they already contain the needed
   sufficient statistics; reprocess daily data only when they do not.
5. **Verify**: run the tests, regenerate every affected output, and look at the
   rendered figures.

## Completion standard

A scientific change is not done until you have stated the data period, products,
time match, grid, and masks; the metric equation and sign convention; the
independent sample unit and degrees of freedom for any test; whether monthly
checkpoints stayed valid or why they had to be recomputed; passing tests plus
visual inspection of every regenerated figure; and synchronized plan/README text
when public behavior changed.

## Red flags — stop and re-read the contract

- "I'll just resample MERRA to the MODIS grid, it's easier to plot."
- "72 cells gives me n=72 for the t-test."
- "Averaging the monthly biases is close enough."
- "Support was 78%, that's basically 80%."
- "The reference was near zero, so the normalized bias of 900% is real."
- "I'll re-download the year; it's simpler than reading the checkpoints."
- "FDR would be more rigorous here."

Each of these changes what the experiment means. Raise it explicitly instead.
