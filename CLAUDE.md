# Repository guidance

## Snow-hydrology analysis

For any task that reproduces, changes, audits, plots, or interprets this MERRA-2/MODSCAG comparison, use the repository skill at `.claude/skills/snow-hydrology-fsca-evaluation/SKILL.md`. Read the linked reference appropriate to the task before acting.

Treat `README.md` as the public experiment contract. Keep it synchronized with user-visible scientific or operational changes.

## Scientific invariants

- Reference daily STC-MODSCAG v1 `snow_fraction` against MERRA-2 `M2T1NXLND.5.12.4:FRSNO` at index 15 (15:00-16:00 UTC).
- Aggregate equal-area 500 m MODSCAG pixel centers to native 0.625° x 0.5° MERRA cells. Do not interpolate MERRA down to MODIS resolution.
- Require 80% daily MODSCAG support and weight pooled errors by valid fine-pixel count.
- Keep the error sign MERRA-2 minus MODSCAG.
- Preserve WY2010-2023 unless a product-continuity review justifies an extension.
- Stream daily inputs and persist only atomic monthly statistics and final outputs.
- Use years, not spatial pixels, as independent replicates for cellwise temporal bias tests.
- The current wet/dry NMB figure uses raw two-sided p < 0.05 hatching with no FDR correction.

Do not silently change products, timestamps, year groups, normalization, support thresholds, low-snow masks, or test units. Explain and document any intentional departure.

## Workflow

Use the research-plan-implement sequence already established in `research/` and `plan/`. Reuse validated sufficient-statistic checkpoints whenever possible; do not trigger a multi-year redownload for a statistic already recoverable from saved sums and counts.

The intended local execution settings are 16 worker processes and eight FTP connections. Do not raise the FTP limit to the CPU count because the archive rejects ten concurrent connections per IP.

Never expose or commit Earthdata tokens, passwords, `.netrc` content, raw daily granules, temporary subsets, Python caches, or package build metadata.

## Validation

- Run `/Users/clintonalden/miniconda3/envs/env1/bin/python -m pytest -q` after code or scientific-logic changes.
- Regenerate every affected CSV and figure from validated inputs.
- Visually inspect changed plots for masks, hatching, month order, shared scales, terrain legibility, labels, and whitespace.
- Check checkpoint and output metadata for product, time, domain, aggregation, weighting, and error-sign consistency.
- Update `README.md` and the relevant plan when public behavior or the scientific contract changes.

## Code review rules

Flag changes that:
- compare a MERRA time other than index 15 without explicit scientific review;
- resample MERRA to MODIS instead of aggregating MODIS to MERRA;
- treat spatial cells or fine pixels as independent degrees of freedom;
- average derived metrics when sufficient statistics should be combined first;
- normalize by negligible MODIS snow without the documented masks;
- apply FDR to the current wet/dry significance figure;
- bypass the 80% support threshold or change the error sign; or
- persist credentials or raw daily data.
