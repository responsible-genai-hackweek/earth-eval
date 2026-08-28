---
name: building-beamer-decks
description: Use when building, revising or rebuilding a LaTeX beamer deck under Tectonic - adding or reordering a frame, placing a figure or a logo on a slide, switching the deck's theme, chasing an Overfull \vbox or a Missing character, sizing a title, a column or a figure, or judging whether a clean build means the page is right; and when a number on a slide has to be traced back to the result it came from. Typesetting, layout and deck convention only - what a figure should show belongs to designing-thematic-figures, and which claim a number may carry belongs to the domain skill that owns it.
---

# Building Beamer Decks

A projected deck is typeset by a program that cannot see. **Core principle: the log proves
the page did not overflow, and nothing else — every other property of the slide has to be
looked at.**

## Build, gate, then look

- `build.sh` greps `main.log` for the two failures the room would otherwise find:
  `Overfull \vbox`, a slide running off its page, and `Missing character`, a glyph absent
  from the font and rendering as nothing at all.
- **A green build is not proof a page looks right.** The log cannot see a collision, a
  clipped label, a figure rotated the wrong way, or type too small to read. Render and
  look: `pdftoppm -png -r 110 main.pdf out/p`.
- Where the doubt is about type rather than layout, crop at high resolution with
  `pdftoppm -r 500 -f N -l N -x X -y Y -W W -H H`. Upside-down text builds clean.
- Measure off the render, never an estimate. A title's size is bound by the WIDTH of its
  longest line against `\textwidth`, not the page height: 14.1cm at 19pt in a 14.9cm
  block overruns at 20pt.

## The engine fails silently

Tectonic is XeTeX and unicode-native, which removes some traps and adds others. Each of
these builds clean and is wrong on the page:

- `fontspec` must load BEFORE whatever loads the text font. Loaded after, it resets
  `\rmdefault`/`\sfdefault` to Latin Modern and switches `\encodingdefault` from T1 to TU
  while Helvetica exists only as `T1/phv`, so every request falls back to LM Roman and the
  deck silently turns serif. Restore `\renewcommand{\encodingdefault}{T1}\normalfont`
  immediately after.
- A literal em dash has no mapping into a T1-encoded body font and is dropped. `inputenc`
  is a no-op on a unicode-native engine, so make the character active by catcode or write
  `---`. This is what the `Missing character` gate is for.
- `listings`, never `minted`: no shell-escape under Tectonic.
- Where vertical space is tight prefer `\centering` in a box to the `center` environment,
  whose `\topsep` glue alone can tip a slide into Overfull.
- `[T]` on `columns` aligns the column BOXES, not the ink: a `tikzpicture` whose bounding
  box starts above its first mark hangs low beside the block opposite. Lift the column
  with a negative `\vspace*`, don't move every node. Mismatched heights want `[c]`.

## The theme is one line, and only if nothing cheats

- The palette is chosen by a single `\input` in `colors.tex`. That is the whole change
  only because no frame names a palette colour: frames are written against a symbolic seam
  — `accent`, `accentSoft`, `accentDeep`, `accentFill`, `accentTint`, `mutedInk`.
- The contract is checkable, so check it after editing frames:
  `grep -ohE 'nasa[A-Za-z]+|claude[A-Za-z]+' frames/*.tex` must return nothing.
- **Never carry a tier by hue alone.** A monochrome palette has no second hue to spend, so
  a distinction made in colour reads fine under a two-hue theme and disappears under a
  one-hue one. Make it structurally — italic for an aside, bold for emphasis.
- Measure contrast, don't assume it: white on this deck's clay is 3.12:1, AA for large
  text but not body copy, so that ground carries bold headings only. Record the
  measurement in the theme file so it stays a decision rather than an oversight.
- Vendor inks are content, not chrome. A brand's own mark, or a panel painting another
  product's interface, keeps its colours under every theme and lives outside the seam.

## Figures on a 16:9 page

- Figure colour encodes DATA, not deck chrome: a per-product mapping specified with the
  analysis stays fixed under every theme.
- A tall figure on a wide page is HEIGHT-bound. Widening its column does nothing; only
  `height=` moves it.
- Two figures side by side want columns proportional to their ASPECT RATIOS. Equal columns
  give them different heights, so the captions land on different baselines and the taller
  runs off the page. `w_i = a_i / Σa`, less half the gap; recompute if either is redrawn.
- Rotating a portrait figure into landscape is a TRADE, not a fix. Row and axis labels are
  usually already rotated 90° in the source, so no rigid rotation leaves them upright AND
  keeps the reading order forward — one direction buys readable labels, the other forward
  time. Render both, choose knowingly; only regenerating in landscape gets both.
- Bake a rotation into the file rather than using `\rotatebox`, so the aspect ratio
  `\includegraphics` sees is the one on the page — then re-read the caption, because a
  rotation silently falsifies every "left", "right", "above" and "below" in it.

## Marks and logos

- **Symbols, not wordmark lockups**, when marks share a band: a lockup spends most of its
  bounding box on leading rather than ink, so at a shared height it whispers beside a
  solid disc. Set heights PER MARK for the same reason — a solid disc and a thin radial
  starburst carry very different ink at one height.
- Put the band IN THE FLOW under a `\vfill`, never as a page overlay. An overlay costs no
  vertical space, so it knows nothing about the text above it and prints through it. In
  the flow they cannot collide, and if they will not both fit the build fails on Overfull.
- A third party's mark carries usage rules that outrank layout convenience: no recolouring,
  rotation, cropping or stretching; the registered variant when it stands alone; exactly
  one of `height` or `width`. Record provenance beside the files.

## Every number on a slide was quoted from somewhere

- A number on a slide comes from the generated results file, not from memory and not from
  an earlier draft of the slide. A rerun of the analysis obliges a pass over the deck.
- The claims discipline governing the report governs the slides: rank rather than
  magnitude, and every quoted amount says WHICH MODEL produced it. Where two models
  disagree about amount by a factor of three or more, the amount describes that model
  and not the world. Say it the way a caption would — "all values ERA5" — not as an
  aphorism about what a number does.
- Words on a slide must survive being said out loud to someone outside the project.
  Archive vocabulary ("product" for a dataset), engineering metaphor ("load-bearing") and
  jargon in a title ("claim") all build clean, read fluently, and say nothing to the room.
- Record in the frame file WHY a size, a gap or a direction is what it is, and what failed.
  Every measurement is hand-tuned against a render; the comment is the only copy.

## Red flags

- *"The build is green, so the deck is done."* The gate proves the page did not overflow.
  It cannot see an upside-down label, a collision, or a figure nobody can read.
- *"I'll widen the column to make the figure bigger."* A portrait figure on a wide page is
  height-bound. Column width is not the lever.
- *"The second colour will carry the distinction."* Under a monochrome theme there is no
  second colour. Carry it in weight or slope.
- *"Rotating it fixes the labels."* Rotation moves everything, including the reading order
  and every direction word in the caption.
