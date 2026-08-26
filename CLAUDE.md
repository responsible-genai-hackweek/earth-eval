# earth-eval

## Coding-agent comparison experiment

This repository runs the same specification through more than one coding agent
so the resulting implementations can be compared.

- `clinton` — reference implementation authored by Codex.
- `david` — this branch. Independent implementation by Claude.

**Do not read, diff, cherry-pick, or otherwise consult the implementation on the
`clinton` branch** (`src/`, `tests/`, `results/`, `pyproject.toml`, `*.zsh`, or
its `README.md`). Doing so invalidates the comparison. The shared inputs — the
research notes, the plans, the domain skills, and the coarse DEM used for figure
context — have already been ported into this branch; work from those.

If a question can only be answered by looking at the other implementation, ask
the user instead.

## Where things are

- `merra_modis_comparison/CLAUDE.md` — project guidance and scientific invariants
- `merra_modis_comparison/research/` — product research (ported)
- `merra_modis_comparison/plan/` — the specification to implement (ported)
- `.claude/skills/` — domain skills, entry point `snow-hydrology-fsca-evaluation`
