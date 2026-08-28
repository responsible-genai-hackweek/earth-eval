# Hackweek deck

Eight slides summarising this project for the
[Responsible Gen-AI for NASA Earthdata hackweek](https://responsible-genai.hackweek.io/)
(UW eScience Institute with NASA, Seattle, 24–28 August 2026). The emphasis is
the method — coding agents, agent skills, and the data pipeline they built —
with the snowpack result as the evidence that it worked.

## Build

```
slides/build.sh              # tectonic, gate the log, open main.pdf
BUILD_NO_OPEN=1 slides/build.sh
```

Requires `tectonic` (XeTeX) and the system Menlo font. The gates read
`main.log`: an `Overfull \vbox` means a slide has run off its page, and a
`Missing character` means a glyph is absent from the selected font and is
rendering as nothing at all. **A green build is not proof a page looks right** —
render and look before calling the deck done.

## Layout

| File | What it is |
|---|---|
| `main.tex` | entry point; the `\input` order is the show order |
| `preamble.tex` | 16:9 beamer, chrome, `\figcaption`, `\decklink`, the CLI panel |
| `colors.tex` | the NASA seam: palette, `\themelogo`, font, `\graphicspath` |
| `meta.tex` | title, subtitle, venue, date |
| `frames/NN-*.tex` | one slide per file |
| `figures/` | the plots, copied from the analysis output |
| `graphics/logos/` | NASA, OpenAI and Anthropic marks |

The deck is self-contained: `preamble.tex`, `colors.tex` and the marks are
local copies of the `nasa_blue` theme from `~/DavidFillmore/Media`, not
references into it, so this repository builds the deck on its own.

Slide patterns use only the symbolic colours (`accent`, `accentSoft`,
`accentDeep`) and `\themelogo`, never palette names or logo filenames — the
portability contract the theme was written to. Retheming is then a matter of
swapping `colors.tex`.

## Conventions

- One slide per file; `main.tex` is the ordering source of truth.
- Every number on a slide comes from `merra_modis_comparison/results/FINDINGS.md`,
  which is generated from the daily checkpoints. Re-measure before the talk if
  the analysis has been rerun; the counts on `02-project-planning` (modules,
  tests, notes) are measured off the tree the same way.
- The claims discipline in `merra_modis_comparison/CLAUDE.md` applies to the
  slides as much as to the report: rank rather than magnitude, and every figure
  names its product.
- `listings`, never `minted` — no shell-escape under Tectonic.
- Links render as regular text, underlined, via `\decklink`, and are never
  shrunk relative to the line they sit in.
- `figures/wy2023_wet_dry_composite_rot.png` is pre-rotated 90° **counter-clockwise**
  (`sips -r -90`) so months run November to May left to right. Clockwise
  reverses them. The rotation is baked into the file, not applied in LaTeX.
- Authors are deliberately absent. To restore them, add `\PosterAuthor` to
  `meta.tex` and a line for it in `frames/01-title.tex` between the venue and
  the date.
