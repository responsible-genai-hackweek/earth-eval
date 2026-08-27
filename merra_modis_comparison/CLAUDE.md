# Repository guidance — Colorado Rocky Mountains snowpack, MERRA-2 versus ERA5

## What this project is

**Primary analysis:** daily domain-mean Colorado snowpack in two reanalyses,
MERRA-2 and ERA5, over water years 1981–2026, snow-water-equivalent led. The
motivating question is whether WY2026 was an exceptionally low snowpack year and
whether two independently produced reanalyses agree that it was. WY2023 is the
above-average counterpoint. See `plan/SNOWPACK_REANALYSIS_PLAN.md`.

**Secondary analysis:** a single-year satellite validation for WY2023 against
STC-MODSCAG fSCA. WY2023 lies entirely inside the clean historical MODSCAG
record, so no product splice or near-real-time era is involved. The archived
plans `plan/FSCA_PIPELINE_PLAN.md` and `plan/MULTIYEAR_2010_2023_PLAN.md`
describe an earlier, superseded experiment and are left unedited as its record.

The `clinton` branch holds a separate, complete implementation of that
superseded fSCA experiment. It is a legitimate cross-reference for the WY2023
validation and is not off-limits; the coding-agent comparison that once made it
so was abandoned when the scope changed.

## Skills

The three domain skills under `.claude/skills/` were written for the fSCA
experiment. `modis-merra-regridding` and its coverage gate still govern the
WY2023 validation. `snow-bias-statistics-and-figures` still governs metric
definitions and figure conventions. Read the relevant one before acting.

## Scientific invariants

- Domain: the 72 native MERRA-2 cells centred in 109–104°W, 37–41°N. Envelope
  −109.0625…−104.0625°E, 36.75…41.25°N. Described as the Colorado Rocky
  Mountains: median cell elevation 2442 m, 75% of cells above 2000 m. The box
  is a rectangle, so its eastern column is High Plains (1717 m) and its
  western column Colorado Plateau (2003 m). Say "Rockies" for the region, not
  for every cell in it.
- Both models are averaged over **the same geography**, by fractional-overlap
  area weights. ERA5's 0.25° cells do not align with the envelope, so selecting
  whole cells would compare two different regions.
- Domain-mean series are computed on each model's **own native grid**. Only
  difference maps regrid, and then only conservatively by area.
- MERRA-2 `SNODP` is depth over the snow-covered fraction. Grid-mean depth is
  `FRSNO * SNODP`. `SNOMAS` in the same granule is already a grid mean.
- ERA5 `sd` is snow **water equivalent** in metres of water, not geometric depth.
  Geometric depth is `sd / rsn`. Two ECMWF parameters share the name "snow
  depth"; match on short name, never on the long name.
- MERRA-2 fill is 9.99999987e14 and the granule's `valid_range` equals the fill
  value, so it cannot be used as a bound.
- ERA5 archives no fractional snow cover; it is diagnosed from the IFS scheme and
  labelled a derived diagnostic, never an ERA5 product.
- The MERRA-2 production stream is calendar-based with six changeovers between
  1980 and now. A wrong stream returns HTTP 404 with a small XML document, not an
  exception.

## Claims discipline

- Anchor a record-low claim on **1 April SWE and 1 April geometric depth**. Peak
  SWE does not support an unqualified claim — WY2026 is second lowest there.
- Peak SWE must be computed from **daily** data; weekly sampling reverses it.
- **Never use MERRA-2's 1 April value as a benchmark in this domain.** MERRA-2
  melts the domain out almost entirely by April in most years, so the ranking
  within that band is noise. Use it for peak and season-mean SWE instead.
- Do not quote MERRA-2 peak **dates**; they are unphysical for Colorado.
- Never quote a "% of normal" or "times lower than WY2023" figure without naming
  the product. The two models' magnitude ratio grows as the snowpack thins,
  which is the very axis this story runs along.
- Where a value depends on provisional ERA5T rather than final ERA5, say so.

## Workflow

Research, then plan, then implement. Reuse the daily checkpoints under
`results/daily_domain_means/`; they are the unit of resumption and the whole
report rebuilds from them without network access.

Never expose or commit Earthdata credentials, `.netrc` content, raw granules,
temporary subsets, Python caches, or package build metadata.

## Validation

- Run `python -m pytest -q` after any code or scientific-logic change.
- Regenerate every affected CSV and figure, and **look at the rendered PNG** —
  a plotting call exiting zero says nothing about collisions, masks or limits.
- Validate any categorical palette with the dataviz validator rather than by eye.
- Keep `README.md` and the relevant plan synchronized with public behaviour.

## Code review rules

Flag changes that:

- compare ERA5 `sd` against MERRA-2 `SNODP` as though both were depths;
- use raw `SNODP` as a grid-cell mean;
- select whole ERA5 cells instead of fractional-overlap weights;
- regrid for a domain-mean series, or regrid non-conservatively for a map;
- rank peak SWE from sub-daily-resolution data;
- quote MERRA-2 1 April SWE as a benchmark, or MERRA-2 peak dates;
- state a cross-model ratio without naming the product;
- treat fill as zero snow; or
- persist credentials or raw data.
