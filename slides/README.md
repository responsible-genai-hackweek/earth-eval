# Hackweek deck

Nine slides summarising this project for the
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

## Switching theme

Edit the one `\input` line in `colors.tex`:

```latex
\input{themes/anthropic_orange}   % current
% \input{themes/nasa_blue}
```

`themes/<name>.tex` holds a palette and binds the symbolic seam the slides are
written against. Nothing else in the deck names a palette colour, so that line
is the whole change. The contract, checkable:

```
grep -ohE 'nasa[A-Za-z]+|claude[A-Za-z]+' frames/*.tex   # must return nothing
```

| Seam name | What it paints |
|---|---|
| `accent` | primary chrome — frametitle bar, block titles. **Bold text only**: white on Anthropic clay measures 3.12:1, which clears AA for large text and not for body copy |
| `accentSoft` | second tier — alertblocks, asides, review gates |
| `accentDeep` | deep ink — diagram labels, `\figcaption`, emphasis |
| `accentFill` | diagram node fill |
| `accentTint` | block body ground |
| `mutedInk` | de-emphasised labels |
| `\themelogo` | the theme's own mark |

`anthropic_orange` departs from Media's shipped template in one way, on
purpose: the template is single-seam (`accentSoft = accent`), and slides 02 and
04 need a real block/alertblock contrast, so `accentSoft` binds to Anthropic's
dark brown instead.

Tiers are **not** carried by hue alone. A warm monochrome palette has no second
hue to spend, so `\figaside` is italic and the title's emphasis line is bold —
both read under either theme. Adding a new tier by colour alone will look fine
in `nasa_blue` and disappear in `anthropic_orange`.

## Layout

| File | What it is |
|---|---|
| `main.tex` | entry point; the `\input` order is the show order |
| `preamble.tex` | 16:9 beamer, chrome, `\figcaption`, `\figaside`, `\decklink`, the CLI panel |
| `colors.tex` | the theme switch, plus font, vendor inks and `\graphicspath` |
| `themes/*.tex` | one palette per theme |
| `meta.tex` | title, subtitle, venue, date |
| `frames/NN-*.tex` | one slide per file |
| `figures/` | the plots, copied from the analysis output |
| `graphics/logos/` | the four marks; provenance and usage rules in `SOURCES.md` |

The deck is self-contained: `preamble.tex`, `colors.tex`, `themes/` and the
marks are local copies, not references into `~/DavidFillmore/Media`, so this
repository builds the deck on its own.

## Conventions

These are also written down as the `building-beamer-decks` skill in
`.claude/skills/`, together with the Tectonic traps that produce a clean build
and a wrong page. This README is the deck's own record; the skill is what an
agent loads before touching it. Change one and change the other.


- One slide per file; `main.tex` is the ordering source of truth.
- Every number on a slide comes from `merra_modis_comparison/results/FINDINGS.md`,
  which is generated from the daily checkpoints. Re-measure before the talk if
  the analysis has been rerun; the counts on `02-project-planning` (modules,
  tests, notes) are measured off the tree the same way.
- The claims discipline in `merra_modis_comparison/CLAUDE.md` applies to the
  slides as much as to the report: rank rather than magnitude, and every figure
  says which model its numbers came from. MERRA-2 and ERA5 disagree about snow
  amount by roughly threefold in a wet year and by more than an order of
  magnitude in a dry one, so an amount is a fact about the model and not about
  Colorado — and WY2026, the year the deck is about, is where that gap is
  widest.
- The plots keep their own scientific palette — NASA blue for MERRA-2, NASA red
  for ERA5 — under **either** deck theme. Figure colour encodes data, not
  chrome, and that mapping was specified separately.
- Title-slide marks are **symbols only**, no wordmark lockups. A lockup spends
  most of its bounding box on leading rather than ink, so at a shared height it
  whispers beside a solid disc, and matching it by eye makes it run half the
  page wide. Symbols are what let all four be set large.
- The mark band sits in the flow under a `\vfill`, never as a page overlay. As
  an overlay it knew nothing about the text above it and the Block W struck
  through the date line.
- `listings`, never `minted` — no shell-escape under Tectonic.
- Links render as regular text, underlined, via `\decklink`, and are never
  shrunk relative to the line they sit in.
- `figures/wy2023_wet_dry_composite_rot.png` is pre-rotated into landscape and
  baked into the file (`sips`), not applied in LaTeX. The direction is a **trade**:
  the month names are already-rotated matplotlib y-labels, so no rigid rotation
  gives upright labels *and* forward time. **Clockwise** (current) sets the labels
  upright but reverses the columns to May-at-left; counter-clockwise runs months
  November to May left to right with every label upside down. Slide 07's caption
  states whichever order is on the page — check it after any re-rotation.
  Regenerating the figure in a landscape layout is the only way to get both.
- The UW Block W may not be recoloured, rotated, cropped or stretched, and the
  registered version is the one required when it stands alone. See
  `graphics/logos/SOURCES.md`.
- Authors are deliberately absent. To restore them, add `\PosterAuthor` to
  `meta.tex` and a line for it in `frames/01-title.tex` between the venue and
  the date.
