# Season shape against an observation — SNOTEL versus MERRA-2 and ERA5

Status: **methodology recorded; results measured; implementation not yet ported
into the package.** See §9.

Planning date: 2026-08-26. Extends, and does not amend,
[`SNOWPACK_REANALYSIS_PLAN.md`](SNOWPACK_REANALYSIS_PLAN.md), which owns the
magnitude and ranking analysis. Product research is in
[`../research/SNOTEL_PRODUCT_NOTES.md`](../research/SNOTEL_PRODUCT_NOTES.md).

## 1. The question

MERRA-2 and ERA5 disagree about Colorado snowpack magnitude by a factor of three
in midwinter that grows past ten by April. The parent analysis reports that
disagreement and declines to adjudicate it, because two reanalyses are not
independent observations.

They also disagree about *when the season happens*, and that disagreement an
observation can settle. **Does the Colorado snowpack peak in mid-February, as
MERRA-2 has it, or in early April, as ERA5 has it?**

The answer matters beyond timing. A pure precipitation deficit scales a snowpack
curve without moving it. MERRA-2's curve has moved five to six weeks. If the
observation confirms the later peak, the deficit cannot be a precipitation
deficit alone — it is a pack losing mass it should be keeping.

## 2. Why shape, and not magnitude

SNOTEL cannot arbitrate magnitude in this domain and must not be asked to. Every
Colorado station sits above the model domain's median cell elevation; the network
is a sample of the high country inside the domain, not of the domain. A raw
network mean beside a raw domain mean measures siting, not model error.

Timing survives that mismatch far better than magnitude does, and what remains of
it is measurable and correctable (§5). **The claim this analysis supports is
about when the season turns, and nothing else.**

## 3. The comparator on the model side

Two routes, both computed, and they must agree for the result to stand:

1. **Headline — the 8,000–14,500 ft band.** 36 of the 72 MERRA-2 cells and the
   162 ERA5 cells over the same band. Mean cell elevation 9,103 ft against the
   full domain's 8,010 ft median, which closes most of the elevation gap before
   any correction is applied.
2. **Check — per cell, median across cells.** The same operation SNOTEL gets
   (metric per member, then median across members), which the band-mean route
   does not give. A band mean melts out later than a typical member within it,
   so this route is the fairer one and the band route the more familiar.

Neither needs network access. The per-cell checkpoints under
`results/water_year_1981_2026_cell_checkpoints/` already hold daily per-cell
fields for both models across all 46 water years.

**Inherited asymmetry:** MERRA-2 daily values are true 24-hour means; ERA5 is a
12 UTC sample (`fetch.era5_daily_cells`, `hours=(12,)`). For a slowly varying
state variable compared at daily resolution this does not move a timing metric
materially, but it is not zero and is recorded rather than corrected.

## 4. Metric definitions

Applied identically to every source. All are computed **per member on the raw
series** — never from a composite.

| Metric | Definition |
|---|---|
| onset | first day before the peak on which the pack exceeds 10% of that year's peak |
| centroid | Σ(t · SWE) ÷ Σ(SWE) over the water year, mass-weighted mean day |
| peak | day of maximum SWE, ties to the earliest |
| melt-out | first day after the peak on which the pack falls below 10% of that year's peak |

**The threshold is a fraction of peak, not an absolute value.** SNOTEL sites melt
to exactly zero; a cell mean only asymptotes toward it. An absolute cutoff would
compare unlike things and would additionally reintroduce the magnitude difference
this analysis exists to exclude.

**Centroid carries the claim.** It is threshold-free, invariant under a uniform
rescaling of SWE — so immune to the 3–11× magnitude disagreement — and it is the
only one of the four on which the two models share enough interannual signal for
"which model tracks the observation" to be answerable. Across the 46 water years
the two models correlate at rho = +0.76 on centroid and +0.08 on peak date.

**Peak date supports a mean offset only, never a ranking.** At rho = +0.08 the
models' year-to-year variation in peak date is noise in at least one of them.

**Coverage gate.** A station-year is admitted on ≥95% coverage of 1 October–31
July and a peak of at least 2 inches; a cell-year on a peak of at least 5 mm. The
gate is defined on the snow season rather than the calendar year because the
archive ends in August and a full-year gate discards WY2026.

## 5. The elevation correction

The correction is what makes §4 comparable at all, and it is load-bearing.

Each timing metric is regressed on station elevation across the 99 stations with
20 or more valid water years, then evaluated at the band's mean cell elevation of
9,103 ft.

| Metric | gradient, days per 1,000 ft | r | correction applied |
|---|---|---|---|
| onset | −3.9 | −0.56 | +3 d |
| centroid | +5.5 | +0.52 | −6 d |
| peak | +9.4 | +0.54 | −6 d |
| melt-out | +10.5 | +0.52 | −12 d |

**This is an interpolation, not an extrapolation.** 9,103 ft lies inside the
fitted network's own 8,240–11,620 ft span.

**The correction runs against ERA5.** It moves the observation earlier — toward
MERRA-2 — on every metric except onset. ERA5 matches anyway. Anyone re-deriving
this result who omits the correction gets a stronger-looking ERA5 for the wrong
reason, and should not.

## 6. Results as measured

Median over water years. Model rows are the per-cell route; the band route agrees
on every verdict and differs only in degree.

| | onset | centroid | peak | melt-out |
|---|---|---|---|---|
| SNOTEL, raw | 11 Nov | 4 Mar | 8 Apr | 20 May |
| SNOTEL, corrected to 9,103 ft | 15 Nov | 26 Feb | 31 Mar | 10 May |
| ERA5 − SNOTEL | −9 d | **+2 d** | **+3 d** | +10 d |
| MERRA-2 − SNOTEL | −14 d | −31 d | **−48 d** | −57 d |

ERA5's season shape sits within days of the observation on the two metrics that
carry claims. MERRA-2 peaks seven weeks early and melts out eight weeks early.

The hypothesis in §1 survives: the observed pack accumulates until late March, so
MERRA-2's deficit is not a precipitation deficit alone.

**Onset was intended as a control and is not one.** Both models begin the season
one to two weeks before the observation. Whether that is a real shared bias or an
artefact of comparing a point against a cell mean at low snow amounts is open.

## 7. Figures

Three, with narrative in a captions file rather than on any canvas, and SNOTEL
drawn heaviest throughout as the reference rather than a third opinion.

- **Season Shape** — each member divided by its own peak, per-day median across
  members, composite rescaled to its own maximum. The second rescaling is not
  cosmetic: members peak on different days, so an unrescaled composite tops out
  below 1 by an amount that tracks peak-date dispersion (0.905 / 0.857 / 0.605
  against p5–p95 peak spreads of 69 / 95 / 131 days). Left alone it puts timing
  dispersion on an axis labelled fraction of peak, where it reads as magnitude.
- **Season Turning Points** — one point per water year, the median across band
  cells or across stations. Vertical offset is a deterministic beeswarm, so
  vertical extent reads as local density; random jitter would put noise on an
  axis a reader will take for meaning.
- **SNOTEL Timing by Elevation** — the §5 gradients with the band elevation
  marked, so the correction can be inspected rather than trusted.

Figure conventions follow the committed calls in `report.py`, which the figure
skill does not cover: Title Case, three-space separators, domain first, units
spelled out.

## 8. What must not be claimed

- **No magnitude statement from SNOTEL.** Not percent of normal, not "the models
  are low by N inches". The network's siting forbids it in this domain.
- **No ranking of peak dates**, from either model, against anything.
- **No unqualified claim that ERA5 is correct.** ERA5 matches the observed
  *timing*. Its magnitude remains unadjudicated, and its independence from
  SNOTEL is unverified (§10).
- **No dropping of the elevation correction**, for the reason in §5.

## 9. Implementation status

The measurement described here has been performed and the numbers in §5 and §6
are from it. The code is **not yet in the package**: the fetcher, the shape
metrics, the elevation regression, and the three figures currently exist as
standalone scripts. Porting them requires the fetcher to join `fetch.py`, the
metric definitions to join `snowseason.py` beside the existing `peak` and
`melt_out_date`, and tests for each, per the repository's validation rule.

Until that is done, no number in this document is reproducible from a clean
checkout, and this section stays until it is.

## 10. Open items

1. Whether ERA5's snow analysis ingests CONUS station data overlapping SNOTEL.
   If it does, "independent observation" is too strong on the ERA5 side.
2. The station set drifts from 47 to 117 stations across the record. A
   fixed-subset sensitivity test has not been run.
3. The onset disagreement in §6.
4. The recent part of WY2026 rests on provisional ERA5T rather than final ERA5,
   as it does throughout the parent analysis.
