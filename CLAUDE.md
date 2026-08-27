# earth-eval

## What this repository is now

**Colorado snowpack in two reanalyses: MERRA-2 versus ERA5, water years
1981–2026, snow-water-equivalent led.** The motivating question is whether WY2026
was an exceptionally low snowpack year and whether two independently produced
reanalyses agree that it was. See `merra_modis_comparison/CLAUDE.md` for the
working guidance and `plan/SNOWPACK_REANALYSIS_PLAN.md` for the specification.

## History, and why the branches differ

This repository began as a coding-agent comparison: `clinton` holds a
Codex-authored implementation of a MERRA-2 versus STC-MODSCAG fractional
snow-cover evaluation, and `david` began as an independent Claude implementation
of the same specification.

**That comparison was superseded and is not live.** Partway through, the analysis
was re-scoped to the reanalysis intercomparison above, prompted by the WY2026
snowpack. The two branches now implement different experiments and their code is
no longer comparable.

`clinton` is therefore **no longer off-limits**. Read it, diff it, borrow from it.
It remains a working implementation of the fSCA comparison, which survives here
only as the secondary WY2023 satellite validation, so it is a reasonable
cross-reference for that part.

What the comparison did produce, before it was superseded, is the shared
inputs on this branch: the ported research notes, the two archived plans, and the
domain skills — plus a scientific core (target grid, sufficient statistics,
regridding, coverage gate) that was built independently against the same spec.

## Where things are

- `merra_modis_comparison/CLAUDE.md` — working guidance, invariants, claims discipline
- `merra_modis_comparison/plan/SNOWPACK_REANALYSIS_PLAN.md` — the current spec
- `merra_modis_comparison/plan/SEASON_SHAPE_PLAN.md` — SNOTEL season-shape
  methodology. Timing only, never magnitude; the elevation correction is load-bearing
- `merra_modis_comparison/plan/FSCA_*.md`, `MULTIYEAR_*.md` — archived specs of the
  superseded experiment, left unedited as its record
- `merra_modis_comparison/research/` — product research notes
- `merra_modis_comparison/results/` — checkpoints, statistics, figures, findings
- `.claude/skills/` — domain skills. `reanalysis-snowpack-comparison` covers the
  primary analysis; `snow-hydrology-fsca-evaluation` and the three it routes to
  cover the secondary WY2023 validation.
