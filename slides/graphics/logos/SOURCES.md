# Logo provenance

Vector only, no raster objects (`pdfimages -list <file>.pdf` must report none).

| File | Source | Notes |
|---|---|---|
| `nasa_logo.pdf` | `~/DavidFillmore/Media/graphics/logos/nasa/` | NASA insignia ("meatball"). Full-colour; it does not reverse to white by a fill swap, so on a dark ground it needs a white plate. |
| `uw_block_w.pdf`, `.svg` | [UW Brand, Logos](https://www.washington.edu/brand/brand-elements/logos/) → `W-Logo_RegistrationMark_Purple_2685.eps` | Downloaded 2026-08-28 from `cdn.uw.edu`. UW ships vector as EPS, not SVG: the PDF is `epstopdf` off the official EPS and the SVG is Inkscape off that PDF, so both derive from the shipped file with no redraw. |
| `ChatGPT_symbol.pdf` | `~/DavidFillmore/Media/graphics/logos/openai/` | OpenAI mark, monochrome. |
| `Claude_symbol_clay.pdf` | `~/DavidFillmore/Media/graphics/logos/claude/` | Claude starburst, Anthropic clay. The `Claude_by_Anthropic` wordmark lockup was dropped from this deck — symbols only, so all four marks can be set large. |
| `Codex_by_OpenAI.pdf` | `~/DavidFillmore/Media/graphics/logos/openai/` | Not currently placed on any slide; kept as the alternative OpenAI mark. |

## UW usage rules, from the brand site

These constrain what may be done to `uw_block_w.pdf`:

- The Block W may not appear in any colour outside the University palette. It is
  placed here in the ink the official EPS carries and is **not** recoloured —
  not to the deck accent, not to NASA blue.
- The **registered** version is the one required when the Block W stands alone
  as a graphic element, which is what it does on the title slide. That is why
  this is `W-Logo_RegistrationMark`, not the plain `W-Logo_Purple_vector`.
- No stretching, rotation, cropping, outlines, effects, or busy backgrounds.
  `\includegraphics` must always carry exactly one of `height` or `width`.
- Minimum size is 0.25 in wide in print. The title slide sets it far above that.
