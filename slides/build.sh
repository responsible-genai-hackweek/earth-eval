#!/usr/bin/env bash
# Build the deck with Tectonic and gate on the log.
#
# Usage:
#   slides/build.sh              # build and open in Preview
#   BUILD_NO_OPEN=1 slides/build.sh
#
# The gate is the one that matters for a projected deck: "Overfull \vbox"
# means a slide has run off the bottom of its page. A green build is still not
# proof a page LOOKS right — the log cannot see a collision or a clipped
# label, so render and look before calling the deck done.
set -euo pipefail

cd "$(dirname "$0")"

tectonic --keep-logs main.tex

if grep -n 'Overfull \\vbox' main.log; then
  echo "error: overfull vbox — a slide overruns its page" >&2
  exit 1
fi

# A missing glyph builds clean and renders as nothing at all, which is exactly
# the failure the em-dash catcode in preamble.tex exists to prevent. Catch any
# survivor here rather than in the room.
if grep -n 'Missing character' main.log; then
  echo "error: a character has no glyph in the selected font" >&2
  exit 1
fi

echo "built: $(pwd)/main.pdf ($(pdfinfo main.pdf | awk '/^Pages:/ {print $2}') pages)"

if [[ "${BUILD_NO_OPEN:-0}" != "1" ]]; then
  open -a Preview main.pdf
fi
