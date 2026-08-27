# Colorado Rocky Mountains snowpack in two reanalyses

MERRA-2 and ERA5 disagree about how much snow the Colorado Rockies hold by a
factor that
grows as the snowpack thins. They agree closely about which years were extreme.
This project measures both statements over water years 1981–2026, motivated by
the question of whether WY2026 was an exceptionally low snowpack year.

**Headline numbers live in [`results/FINDINGS.md`](results/FINDINGS.md), which is
generated from the data.** Nothing in this README restates a value by hand.

## What is compared

| | MERRA-2 | ERA5 |
|---|---|---|
| Collection | `M2T1NXLND` v5.12.4 | ARCO-ERA5, 0.25° hourly |
| Snow water equivalent | `SNOMAS`, kg m⁻² | `sd` × 1000, kg m⁻² |
| Grid-cell mean depth | `SNODP` × `FRSNO`, m | `sd` ÷ `rsn`, m |
| Snow cover fraction | `FRSNO`, 0–1 | diagnosed, not archived |
| Daily value | mean of 24 hourly means | 12 UTC sample |
| Access | Cloud OPeNDAP, Earthdata login | Google Cloud, no credentials |

Domain: the 72 native MERRA-2 cells centred within 109–104°W and 37–41°N — the
Colorado Rocky Mountains. Median cell elevation is 2442 m and 75% of cells
average above 2000 m, but the box is a rectangle, not a range: its eastern
column reaches the High Plains at 1717 m mean and its western column the
Colorado Plateau at 2003 m.

## Three things that silently produce wrong answers

**ERA5's "snow depth" is not depth.** `sd` is snow *water equivalent* in metres
of water. Geometric depth needs `sd / rsn`. A second ECMWF parameter, `sde`, is
also called "snow depth" and *is* geometric — so matching on the long name picks
the wrong physics without complaint.

**MERRA-2's `SNODP` is not a grid-cell mean.** It is depth within the
snow-covered fraction; the grid mean is `SNODP × FRSNO`. `SNOMAS` in the same
granule *is* a grid mean. Using `SNODP` directly overstates a patchy cell, and
because it saturates it barely moves between a record-low and an above-average
year — which would flatten the very signal being measured.

**Derived quantities must be computed per cell, then averaged.** Depth taken
from domain-mean SWE and domain-mean density is a ratio of means, which differs
from the mean of the ratio by roughly a factor of two in a dry year, because low
water equivalent and low density coincide in space.

## What can and cannot be claimed

- Anchor a record-low claim on **1 April SWE and 1 April depth**. Both are fixed
  dates, insensitive to sampling frequency, and drawn from final ERA5 rather
  than the provisional ERA5T stream.
- **Peak SWE needs daily data.** A weekly sample misses a sharp peak while
  leaving a flat one intact, which can reverse which year ranks lowest.
- **MERRA-2's 1 April value is degenerate here** and is deliberately omitted.
  MERRA-2 melts this domain out almost entirely by April in most years, so
  several years collapse into a band below any credible precision.
- **Never quote a cross-model ratio without naming the product.** The two models
  differ threefold in a wet year and by more than an order of magnitude in a dry
  one.

## Running it

```bash
python -m pip install -e '.[test]'
python -m pytest -q

python -m merra_modis_comparison.run_analysis era5   1981 2026
python -m merra_modis_comparison.run_analysis merra2 1981 2026
python -m merra_modis_comparison.validate_wy2023
```

MERRA-2 access needs Earthdata credentials in `~/.netrc`. ERA5 needs none.

Each water year is checkpointed under `results/daily_domain_means/`, written
atomically, so an interrupted run resumes without refetching. Only domain means
are persisted — never raw fields, and never credentials. The report and every
figure rebuild from those checkpoints with no network access.

## Satellite validation

Water year 2023 is checked against STC-MODSCAG fractional snow cover. WY2023 is
the validation year because it lies entirely inside the clean historical MODSCAG
record, so no product splice or near-real-time era is involved.

The three published MODIS tiles cannot fully cover the domain: cell `j260_i121`
receives 85.6% of its pixel centres, the remainder falling in `h10v05`, which is
not published. That is above the 80% support threshold, so it would pass
silently; the coverage gate refuses it unless the deficit is accepted explicitly,
and it is stamped into every row.

Measured, the bias this actually causes is small: the missing wedge averages
1511 m elevation against 1522 m for the covered part, both flat eastern plains.
The gate exists because nothing in a support fraction would have told you that —
the same deficit over mountainous terrain would bias the cell mean materially,
and a denominator derived from the configured tiles would report 100% support
either way.

## Season shape against SNOTEL

The two reanalyses disagree about magnitude by a factor this project reports and
declines to adjudicate. They also disagree about *when the season happens*, and
that an observation can settle: MERRA-2 peaks in mid-February, ERA5 in early
April.

All 120 Colorado SNOTEL stations, water years 1981–2026, say early April. Against
the observed timing corrected to the comparison band's elevation, ERA5 lands
within 3 days at the peak and MERRA-2 48 days early; at melt-out, +10 days and
−57 days. Since a pure precipitation deficit would scale a snowpack curve without
moving it, MERRA-2's deficit cannot be a precipitation deficit alone.

**SNOTEL is used for timing only, never magnitude.** Every Colorado station sits
above this domain's median cell elevation — the network samples the high country
inside the domain, not the domain — so a raw network statistic beside a raw
domain statistic measures siting, not model error. Even the timing comparison
carries an elevation correction, fitted on the network's own gradient, and that
correction moves the observation *toward* MERRA-2 rather than toward ERA5.

Methodology and the numbers are in
[`plan/SEASON_SHAPE_PLAN.md`](plan/SEASON_SHAPE_PLAN.md); product research and
the API traps are in
[`research/SNOTEL_PRODUCT_NOTES.md`](research/SNOTEL_PRODUCT_NOTES.md). The
measurement has been performed but the code is not yet in the package, which the
plan states in its implementation-status section.

## Layout

```
plan/SNOWPACK_REANALYSIS_PLAN.md   the specification for this analysis
plan/SEASON_SHAPE_PLAN.md          SNOTEL season-shape methodology
plan/FSCA_PIPELINE_PLAN.md         archived spec of a superseded experiment
research/                          product research notes
src/merra_modis_comparison/        the package
results/                           checkpoints, statistics, figures, findings
```
