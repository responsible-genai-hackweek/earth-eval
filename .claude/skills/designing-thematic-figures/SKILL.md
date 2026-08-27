---
name: designing-thematic-figures
description: Use when a figure is going into a paper, report, or briefing for readers who already know the field; when revising one that a reader called cluttered, busy, or hard to read; when a plot carries dozens of same-kind series; when deciding whether a title, subtitle, callout, or legend stays on the canvas; or when choosing display units, labels, and wording for a domain audience. Presentation and communication design only - metric definitions, masking, significance tests, and map or palette conventions belong to the domain skill that owns them.
---

# Designing Thematic Figures

A thematic figure makes one point to readers who already know the subject. **Core
principle: every mark, word and colour must do work the reader cannot do without it.**
Scope is presentation, not metric choice, masking or map conventions.

## Delete what the canvas already says

- A title naming the x axis repeats the axis in words ("by Water Year" over an axis
  labelled Oct–Jul), as does a title naming the dimension each panel already carries.
- Callouts giving value, rank and percent-of-normal collapse to a bare identifier once
  the mark encodes height and position: annotate only what the mark cannot say itself.
- Narrative prose belongs in the caption, editable without re-rendering, with the
  domain, the mask and the cell count.
- Two encodings of one quantity is double-encoding: replacing a band with the curves
  means deleting the band, not layering it underneath.
- State only what the figure cannot show for itself: the record period in the title,
  never a range wider than the figure covers — a single-year panel carries its own year.

## Draw a population as a population

Dozens of curves of one kind — 46 water years, say — are one population, not N series.

- One neutral hue, thin, translucent. Forty-six colours is a cycled-hue rainbow, and
  the highlighted curves then compete with noise.
- Overlap does the work honestly: where members coincide the ink darkens — the band
  earned rather than computed.
- A per-day percentile boundary traces a path no member followed; every spaghetti curve
  happened. Shape is part of the result — a member that ran below normal early and then
  failed to hold it is flattened by a band.
- Mark extremes by stepping **lightness within one hue per pole**, most extreme
  darkest. Rank then reads from weight alone and each ramp stays one family — degrees
  of the same thing, not separate identities.
- Members sharing a colour share one legend row naming both; separate rows in one
  colour rest identity on colour alone.

## The anchor, and identity off the curves

- Give one reference every other curve is read against: the ensemble mean, in a strong
  neutral no other mark uses, reused for that role on other figures.
- An observation the models are checked against is drawn heaviest: it is the reference,
  not a third opinion.
- Labels pinned to each curve's own peak fail where the story is: extreme members peak
  within days of each other, so a label lands in a thicket of near-identical lines.
  Nudging them clear removed the overprint ("201908" as one run of digits) but left
  identity unattributable. Rank belongs in shade, identity in a legend.

## Layout, type, orientation

- Orientation is meaning: the high elevation band goes on the top panel because
  elevation increases upward on the page. Reverse for display only; the stored order is
  untouched.
- Panel labels sit above their panel, left-aligned, never in the data area; the figure
  title is centred, so the two never compete.
- Frame a legend in a quiet box so a key reads as a key, not as data, and set legend
  text in the axis black: a grey key beside black axes reads as a different class of
  thing than it is.
- A style library supplies spines, grid, ticks and type sizing — but not the colours,
  which stay with a palette validated for colour-vision separation.
- Panels a reader moves between should span the same window; an Oct–Sep axis beside
  Oct–Jul ones forces a re-read to compare the same span.
- Shade gaps; never interpolate across them.
- Hairline-dense figures degrade in raster: at any sane DPI thin strokes soften and the
  overlap density carrying the envelope stops reading. Emit vector beside the PNG; the
  vector is the artefact.

## Say it the way the audience says it

- Display in the audience's units, and pick the one that keeps the signal in the
  digits: a record-low depth reads 3.8 in against 0.32 ft, which buries it behind a
  leading zero.
- Round numbers must be round in the display unit: an elevation threshold is stated in
  the reader's feet and converted internally, even where depth displays in inches.
- Ranges beat sides; words beat operators. "6,500–8,000 ft" is something a reader can
  place on the map; "above" and "below" only name a side of a line, and open versus
  closed intervals belong in point-set topology, not on a figure.
- Label the terrain, not the grid's smoothing of it: if cell means top out near 10,800
  ft because a coarse cell averages a peak away, the label is the mountain, not the
  model's number.
- Drop notation the reader already carries, such as "w.e." on a unit label; rank 1 is
  "lowest of 46", not "1st lowest of 46"; separate title parts with space, not colons
  and commas.

## Red flags

- *"It changes every number on the plot, so it belongs on the canvas."* It belongs in
  the caption, editable without re-rendering.
- *"These two elements are inconsistent, so I'll make the plot match the code."* The
  diagnosis is **which element should not be on the figure at all**; resolving toward
  the more technical one propagates notation onto a canvas that should never have
  carried it.
- *"I'll label each curve at its peak."* Extremes peak within days of each other; the
  label cannot be traced back to a curve. Shade for rank, legend for identity.
