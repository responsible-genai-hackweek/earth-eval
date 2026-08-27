---
name: reanalysis-snowpack-comparison
description: Use when comparing snow between two reanalyses or gridded models - MERRA-2 against ERA5, snow water equivalent, snow depth, or snow cover fraction - including choosing which quantity carries a claim, converting units between products, weighting a domain mean across mismatched grids, ranking water years, or judging whether two models agree about an extreme year.
---

# Comparing Snowpack Between Reanalyses

**Core principle: the two models agree on order and disagree on magnitude.** Rank
is usually the defensible claim; a ratio between products usually is not. Design
every statement so it survives that asymmetry.

## The variable traps

Both products publish a field whose *name* means something other than what a
reader assumes. Each of these was confirmed against the data and the providers'
own documentation, and each produces a plausible wrong answer rather than an
error.

| Field | What it actually is | Correct use |
|---|---|---|
| ERA5 `sd` "Snow depth" | Snow **water equivalent**, metres of water | SWE; multiply by 1000 for kg m⁻² |
| ERA5 `sde` (paramId 3066) | Geometric depth, metres | The *other* parameter also called "Snow depth" |
| ERA5 geometric depth | Not archived in the analysis-ready store | Derive as `sd / rsn` |
| ERA5 snow cover | **Not archived at all** | Diagnose `min(1, depth/0.10)`; label it derived |
| MERRA-2 `SNODP` | Depth **within the snow-covered fraction** | Grid mean is `SNODP * FRSNO` |
| MERRA-2 `SNOMAS` | Grid-cell mean SWE, kg m⁻² | Directly comparable to `sd * 1000` |

Two variables in one MERRA-2 granule use **different area conventions**. Never
assume consistency within a file.

**The tell for a depth-convention error is implied density.** Divide snow mass by
your candidate depth. Physical bulk snow density is roughly 150–500 kg m⁻³. If
you get single digits, you divided a grid-mean mass by an in-pack depth. In one
real case the wrong convention changed a dry-year-to-wet-year depth ratio from
0.019 to 0.415 — a factor of 22 in the headline number — because in-pack depth
*saturates* and barely moves between a record low and an above-average year.

Also: MERRA-2's declared `valid_range` **equals its fill value**, so it is
useless as a quality bound. Mask on the fill sentinel's magnitude instead.

## Grids: weight, never select

Reanalyses rarely share a grid, and the coarse grid's cell edges will not align
with the fine one's. Selecting whole cells then compares two different regions
and reports the difference as a model difference.

- **Domain-mean series: do not regrid at all.** Compute each model's
  area-weighted mean on its own native grid, over the same geographic envelope,
  using **fractional overlap** weights so both integrate identical area.
- **Difference maps only: regrid conservatively**, by fractional area. Never
  pixel-center binning at a small grid ratio, and never bilinear.
- Latitude weights are a **difference of sines**, not degrees. Cell counts are
  valid weights only on an equal-area grid — a regular lat/lon grid is not one.
- Pixel-center binning is fine when a fine cell is a ten-thousandth of a coarse
  one, as with 500 m satellite pixels. At five to one it is not.

## Which metric can carry a claim

Not every metric supports the same statement, even from the same data.

- **A fixed-date benchmark** (1 April, say) is robust: immune to sampling
  frequency, and one value per year.
- **Peak** is sampling-sensitive. A weekly series can miss a sharp peak and
  *reverse* which year ranks lowest, while leaving a flat peak untouched.
  Compute peaks from daily data or do not rank them.
- **A metric that saturates or bottoms out is degenerate.** If a model melts the
  domain out by the benchmark date in most years, several years collapse into a
  band below any credible precision and ranking within it is noise. Reporting
  that rank is as misleading as ignoring the model. Use the metric where the
  model is not degenerate, and say why you switched.
- **Do not quote timing from a model whose timing is unphysical** for the domain,
  even when its ranking is sound.

## Stating cross-model results

- Report **rank agreement** (Spearman) as the agreement claim, and plot rank
  against rank. Plotting values against values implies an agreement that a
  three-to-forty-fold magnitude spread does not support.
- **Never quote "percent of normal" or "N times lower than year X" without
  naming the product.** The magnitude ratio between two models typically grows
  as the snowpack thins — which is exactly the axis a drought story runs along.
- When models disagree in magnitude but agree in order, that *is* the finding.
  Report it; do not average it away.
- Two reanalyses are not independent observations. Agreement raises confidence
  in the ranking, not in the absolute value.

## Access economics

- Analysis-ready Zarr stores are often chunked as **one global field per
  timestep**. A small spatial window then costs the same as the whole planet, so
  budget from chunk size and timestep count, never from region size.
- A **padded time axis** is the sharpest trap: the coordinate may extend decades
  beyond the data, and absent chunks read back as NaN with no error. Check the
  store's declared data bounds and refuse dates outside them.
- Check the longitude convention (0–360 versus ±180) and the latitude direction.
  A slice in the wrong convention returns an **empty array, not an error**, which
  looks exactly like missing data. Two products on opposite conventions cannot
  share a slicing helper.
- Where a product has a preliminary near-real-time stream, record which stream
  produced each value **from the data**, not from the date, and carry it into any
  figure that depends on it.

## Red flags

- "ERA5 snow depth is 0.15 m, so the snowpack is 15 cm."
- "I'll use SNODP as the grid-cell depth."
- "The models disagree by 40×, so one must be broken." *(Check whether the ratio
  varies with snowpack depth first — it usually does.)*
- "Weekly sampling is enough to find the peak."
- "Model B ranks it 7th, so the claim is contested." *(Check for degeneracy.)*
- "I'll select the ERA5 cells inside the domain."
- "The time axis goes to 2050, so the data does."
