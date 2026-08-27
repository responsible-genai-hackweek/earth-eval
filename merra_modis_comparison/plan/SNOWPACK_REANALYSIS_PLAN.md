# Colorado snowpack in two reanalyses — MERRA-2 versus ERA5, WY1981–WY2026

Status: **specification — access details pending measurement.**

Planning date: 2026-08-26. Supersedes, but does not amend, the archived fSCA plans
beside it: `FSCA_PIPELINE_PLAN.md` and `MULTIYEAR_2010_2023_PLAN.md` describe a
different experiment and are left untouched as the record of it.

## 1. The question

Was water year 2026 an exceptionally low snowpack year in Colorado, and do two
independently produced reanalyses agree that it was?

WY2023 serves as the above-average counterpoint. The scientific interest is not
only the ranking but whether MERRA-2 and ERA5 — different models, different
assimilation systems, different snow schemes — agree about an extreme. Two
reanalyses agreeing is evidence; two disagreeing is a result in its own right and
must be reported as one rather than averaged away.

## 2. Fixed scope

- Domain: the 72 native MERRA-2 cells whose centers lie in 109–104°W, 37–41°N.
  Unchanged from the earlier experiment, including the complete-cell envelope
  −109.0625…−104.0625°E, 36.75…41.25°N.
- Period: water years 1981 through 2026, inclusive. 46 water years.
  WY1981 begins 1980-10-01; MERRA-2 begins 1980-01-01, so WY1981 is the first
  complete water year available from both models.
- Full water years, October through September — not the November–May window of
  the earlier fSCA work. Peak-SWE timing and melt-out date are the point here,
  and a truncated year cannot express either.
- WY2026 is complete through the snow season. MERRA-2's latest granule is
  2026-08-01, so WY2026 is short only its final two months, which carry no
  snowpack signal in this domain.

### 2.1 ERA5T and the provenance it obliges

ERA5's final stream lags real time by several months, so the most recent portion
of WY2026 is covered by ERA5T, the near-real-time extension. **ERA5T is used
where final ERA5 is unavailable.** This is a deliberate choice: without it the
record-low year is not covered at all, which would defeat the analysis.

ERA5T values are preliminary and can be *revised* when final ERA5 replaces them.
That imposes three requirements, none optional:

1. Every daily record stores which ERA5 stream produced it, read from the data
   rather than inferred from the date.
2. The stream boundary is part of the configuration fingerprint, so a rerun after
   ERA5T has been superseded is recognised as different rather than reused.
3. Any figure or statement in which WY2026 depends on ERA5T says so on its face.
   A record-low claim resting partly on provisional data must be legible as such.

The MERRA-2 side has no equivalent provisional stream, so this qualification
attaches to the ERA5 series alone — which is itself a reason the two-model
framing is worth having.

## 3. Compared quantities

Snow water equivalent leads. It is what "snowpack" means for water supply, it is
the basis of operational records, and both models carry it natively rather than
deriving it.

| Quantity | MERRA-2 | ERA5 | Status |
|---|---|---|---|
| Snow water equivalent | `SNOMAS` (kg m⁻²) | `sd` (m of **water equivalent**) | headline |
| Geometric snow depth | `SNODP` (m) | `sd` ÷ `rsn` (m) | supporting |
| Fractional snow cover | `FRSNO` (0–1) | `snowc` (%) | supporting |

**The ERA5 trap.** ERA5's variable named *snow depth* (`sd`) is snow *water
equivalent* in metres of water, not a geometric depth. Geometric depth requires
dividing by snow density `rsn`. Comparing `sd` against MERRA-2 `SNODP` directly
would be wrong by roughly the snow-to-water density ratio — a factor of three to
four — and would look entirely plausible. Every variable name, unit, and
conversion in the table above is to be verified against the granules themselves
before any comparison is computed, and asserted at read time thereafter.

## 4. Spatial rule — and why the earlier rule does not transfer

The fSCA experiment aggregated 500 m equal-area satellite pixels up to MERRA-2
cells by pixel-center binning. That rule is correct there and wrong here.

ERA5 is 0.25° and MERRA-2 is 0.625° × 0.5°, so roughly five ERA5 cells fall in
one MERRA-2 cell. Pixel-center binning is a good approximation when a fine pixel
is a ten-thousandth of a target cell; at five to one it is not. ERA5 is also a
regular latitude/longitude grid, so its cells are **not** equal area and cell
counts are not valid weights.

Therefore:

1. **Domain-mean time series — no regridding at all.** Compute each model's
   cos(latitude)-weighted domain mean on its own native grid. This is the
   headline product and it never needs a common grid.
2. **Difference maps — conservative area-weighted regridding.** Where a spatial
   difference is shown, regrid ERA5 onto the MERRA-2 grid by fractional cell
   overlap weighted by cell area. Never by pixel-center binning, and never by
   bilinear interpolation.

Both models are reported with their own land treatment; any land-fraction or
glacier mask is applied as a weight, not as a silent exclusion.

## 5. Time convention

The earlier experiment sampled MERRA-2 hour index 15 to match a MODIS overpass.
That convention is not appropriate here and is not carried over: there is no
overpass to match, and a snowpack state variable should not be sampled at an hour
chosen for a satellite.

**Decision: the daily value is the mean of all twenty-four hours, on both
sides.** A single fixed hour would have been roughly twenty-four times cheaper
and probably adequate for a slowly varying state variable, but "probably
adequate" is not a defensible basis for a record-ranking claim, and the transfer
cost is affordable at this domain size.

One asymmetry is inherent and is documented rather than corrected: MERRA-2
`tavg1` fields are hourly *time-averaged*, so their 24-hour mean is a true daily
mean; ERA5 snow fields are *instantaneous* analysis values at each hour, so their
24-hour mean is a 24-sample estimate of one. For SWE and snow depth the
difference is negligible at daily resolution; it is noted because it is not zero,
and because it would matter for a variable with a strong diurnal cycle.

The convention is recorded in the configuration fingerprint.

## 6. Derived metrics, per water year and per model

- Peak SWE and the date it occurs.
- 1 April SWE, the standard operational benchmark.
- Melt-out date, defined from a stated threshold on domain-mean SWE.
- Water-year rank against the WY1981–WY2026 distribution, and the standardized
  anomaly against the climatology.
- Model-minus-model differences, pooled from sufficient statistics rather than
  averaged from derived metrics, retaining the existing weighted bias and MAE
  machinery with the error sign MERRA-2 minus ERA5.

A record-low claim is reported as a rank with its distribution, from each model
separately. It is never asserted from a single model, and never from a
model-mean.

## 6.1 Which metric carries the claim, and which cannot

Established by measurement across WY2000–WY2026 before the full record was
built. These are constraints on the write-up, not preferences.

**Anchor the claim on 1 April SWE and 1 April geometric depth.** On both, WY2026
is the lowest of the record under every sensitivity test applied — four domain
weightings, a mountain-only subset, and 12Z versus 24-hour sampling — and both
rest on final ERA5 rather than provisional ERA5T. The depth signal is the sharper
of the two, because WY2026's snow was also less dense than usual.

**Peak SWE does not support an unqualified record-low claim.** In ERA5, WY2026 is
the *second* lowest; WY2018 is lower by about 4%, and that ordering survives
recomputation with true 24-hour daily means around each peak. If peak SWE is
quoted at all, it is quoted as "second lowest, essentially tied with WY2018".

**Peak SWE must be computed from daily data.** A weekly sample reverses the
result: it misses WY2026's sharp early-March peak while WY2018's flat peak is
unaffected. The 1 April benchmark is immune, being a single fixed date.

**MERRA-2's 1 April value is a degenerate metric in this domain and must not be
used as a benchmark.** MERRA-2 melts this domain out almost entirely by April in
most years — several years fall below 1 mm and at least one is exactly zero
across all 72 cells — so ranking within that band is noise. Reporting "MERRA-2
ranks WY2026 only seventh" would mislead exactly as much as calling it a record.
MERRA-2 earns its place on peak SWE and season-mean SWE, where it is not
degenerate and where it independently puts WY2026 lowest.

**Do not quote MERRA-2 peak dates.** They fall in November–February in most
years, which is not physical for Colorado; ERA5's early-March-to-early-April
peak is. MERRA-2 is used for ranking, not for timing.

**Never quote a "% of normal" or "times lower than WY2023" figure without naming
the product.** The two models disagree in magnitude by roughly three-fold in a
wet year and by more than an order of magnitude in a dry one. The disagreement is
not a constant offset — it grows as the snowpack thins, which is precisely the
axis this story runs along. That behaviour is itself a finding and is reported as
one.

## 7. Satellite validation — WY2023 only

One observational anchor, deliberately narrow: STC-MODSCAG `snow_fraction` versus
both models' fractional snow cover for water year 2023.

WY2023 is chosen because it lies entirely inside the clean historical MODSCAG
record, which ends 2023-09-30, so no product splice, near-real-time era, or
algorithm-version break is involved — and because it is the above-average
counterpoint year the story already needs. The existing sinusoidal geometry,
pixel-center mapping, and tile-coverage gate are reused unchanged, including the
gate that refuses the three-tile set because cell `j260_i121` would otherwise sit
at 85.6% coverage.

This validation is explicitly secondary. It answers "do the models' snow-cover
fields resemble what was observed in a normal year", not "is WY2026 a record".

## 8. What carries over from the earlier implementation

Unchanged and already tested: the 72-cell target grid and complete-cell edges,
the water-year calendar, the sufficient-statistic accumulators and their
combine-over-time versus combine-over-space distinction, the frozen configuration
and its SHA-256 fingerprint, atomic checkpointing, and the MODIS sinusoidal
geometry with its coverage gate.

Requires extension: the MERRA-2 production-stream rule, verified only from 2009
onward, must be extended back to 1980 across streams 100, 200, and 300.

## 9. Open items, pending measurement

1. The ERA5 access route, its grid conventions, chunk layout, and the measured
   cost of a 46-year, 24-hour-per-day Colorado extraction.
2. Where exactly the final-ERA5 / ERA5T boundary falls today, and how the stream
   is identified from the data itself rather than assumed from the date.
3. Exact MERRA-2 stream boundaries between 1980 and 2001.
4. Confirmation of every variable name, unit, and fill value in section 3.
