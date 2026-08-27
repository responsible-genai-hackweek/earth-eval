---
name: snow-hydrology-fsca-evaluation
description: Reproduce, audit, interpret, or extend the Colorado daily MERRA-2, ERA5, or ERA5-Land versus STC-MODSCAG fractional snow-covered area evaluation. Use for product and time matching, MODIS-to-model-grid aggregation, checkpointed execution, bias metrics, wet/dry composites, elevation analysis, cellwise significance tests, or related figures in this repository. Do not carry these choices to unrelated variables or domains without revisiting the scientific contract.
---

# Snow Hydrology fSCA Evaluation

Preserve the snow-hydrology meaning of the comparison while making the pipeline
reproducible and computationally practical.

## Route the task

- For product selection, timing, spatial support, metric definitions, masks, or
  changes to the experiment, read
  [references/scientific-contract.md](references/scientific-contract.md).
- For downloading, resuming, parallel execution, checkpoint reuse, output
  regeneration, or a complete reproduction, read
  [references/reproduction-workflow.md](references/reproduction-workflow.md).
- For maps, elevation plots, wet/dry composites, hypothesis tests, hatching, or
  interpretation, read
  [references/statistics-and-figures.md](references/statistics-and-figures.md).

Read `README.md` before changing behavior. Treat it as the public description
of the implemented experiment, then verify important claims against code and
checkpoint metadata.

## Preserve these core decisions

- Compare daily STC-MODSCAG `snow_fraction` with the reviewed model field:
  MERRA-2 `FRSNO` at index 15 (15:00–16:00 UTC), or the ERA5/ERA5-Land hourly
  `snow_cover` field at 15:00 UTC.
- Aggregate the equal-area 500 m MODSCAG pixels to the selected model product
  grid. Do not interpolate a model down to MODIS resolution and call the
  resulting samples independent.
- Use MODSCAG pixel centers for target-cell membership and an arithmetic mean
  of valid fine pixels. Require at least 80% daily MODSCAG support.
- Weight pooled errors by valid MODSCAG pixel count, which represents paired
  fine-pixel area.
- Stream daily inputs through temporary directories. Persist monthly sufficient
  statistics and final results, not raw daily granules or subsets.
- Use water years—not spatial pixels—as independent replicates in the cellwise
  t-tests.
- In the current wet/dry NMB map, hatch raw two-sided `p < 0.05`. Do not apply
  FDR or another multiple-testing correction unless the user explicitly changes
  the analysis.

## Work in research-plan-implement order

1. Research the exact product, variable, timestamp, coordinate system, and
   missing-data semantics. Prefer the existing research notes and product code
   before external search.
2. State which scientific contract entries remain fixed and which one the task
   proposes to change. Update a plan file before a material experiment redesign.
3. Implement the smallest change that preserves checkpoint resumability and
   sufficient-statistic consistency.
4. Reuse validated checkpoints whenever they contain the needed sufficient
   statistics. Reprocess daily data only when the requested quantity cannot be
   reconstructed from them.
5. Run the relevant tests, regenerate affected outputs, and visually inspect
   changed figures. Report formulas, masks, sample units, and uncertainty
   choices explicitly.

## Scientific guardrails

- Do not silently change the MODSCAG product, selected model collection, 15Z match,
  water-year range, wet/dry membership, support threshold, weighting, or mask.
- Do not use the number of spatial cells as the degrees of freedom for temporal
  bias tests. Spatial autocorrelation and shared storms violate that
  independence assumption.
- Distinguish pooled NMB from the mean of annual NMB values: the pooled value is
  plotted, while annual values are the replicates used by the wet/dry t-test.
- Treat low-reference normalization as unstable. Preserve the 5% MODIS fSCA
  mask for composite NMB/NMAE and the 10% mask for the significance map unless
  a new sensitivity analysis is requested.
- Keep `days_without_observation` as a diagnostic. The selected MODSCAG product
  already contains its documented interpolation; do not silently reinterpret
  it as direct observation.
- Never write Earthdata or CDS credentials, tokens, `.netrc`/`.cdsapirc`
  contents, or downloaded raw granules to repository outputs.

## Completion standard

For scientific changes, finish with:

- the exact data period, products, time match, grid, and masks;
- the metric equation and sign convention;
- the independent sample unit and degrees of freedom for any test;
- confirmation that monthly checkpoints remain valid or a clear reason they
  required reprocessing;
- passing tests and visual inspection of every regenerated figure; and
- synchronized README or plan documentation when public behavior changed.
