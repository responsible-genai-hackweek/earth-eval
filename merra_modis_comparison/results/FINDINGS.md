# Findings

Generated from the daily checkpoints. Do not edit by hand.

Domain: 72 native MERRA-2 cells over Colorado, 109-104W and 37-41N.

- **ERA5**: WY1981-WY2026, 46 complete water years.
- **MERRA-2**: WY2017-WY2026, 9 complete water years (not contiguous).

## ERA5

Ranks below are within WY1981-WY2026.

- **1 April SWE, WY2023**: 157.5 mm w.e. — highest of 46, 184% of the record mean (+2.40 sd).
- **1 April SWE, WY2026**: 34.33 mm w.e. — lowest of 46, 40% of the record mean (-1.72 sd).
- **1 April snow depth, WY2023**: 0.5922 m — highest of 46, 185% of the record mean (+2.28 sd).
- **1 April snow depth, WY2026**: 0.0969 m — lowest of 46, 30% of the record mean (-1.88 sd).
- **peak SWE, WY2023**: 159.4 mm w.e. — highest of 46, 157% of the record mean (+2.25 sd).
- **peak SWE, WY2026**: 58.56 mm w.e. — 3rd lowest of 46, 58% of the record mean (-1.69 sd).
- **season-mean SWE, WY2023**: 66.13 mm w.e. — 5th highest of 46, 149% of the record mean (+1.52 sd).
- **season-mean SWE, WY2026**: 20.38 mm w.e. — 2nd lowest of 46, 46% of the record mean (-1.70 sd).

## MERRA-2

Only WY2017-WY2026 available so far; values are reported without ranks.

- **1 April SWE** — omitted deliberately. MERRA-2 melts this domain out almost entirely by April in most years, so the ranking within that band is noise rather than a result.
- **1 April snow depth, WY2023**: 0.1501 m — not ranked; only 9 water years available, too few to place it in a distribution.
- **1 April snow depth, WY2026**: 0.00495 m — not ranked; only 9 water years available, too few to place it in a distribution.
- **peak SWE, WY2023**: 54.04 mm w.e. — not ranked; only 9 water years available, too few to place it in a distribution.
- **peak SWE, WY2026**: 13.83 mm w.e. — not ranked; only 9 water years available, too few to place it in a distribution.
- **season-mean SWE, WY2023**: 19.2 mm w.e. — not ranked; only 9 water years available, too few to place it in a distribution.
- **season-mean SWE, WY2026**: 1.665 mm w.e. — not ranked; only 9 water years available, too few to place it in a distribution.

## Satellite validation, WY2023

347 of 365 days carry a usable MODSCAG reference; 18 have none in the archive and 0 failed to fetch.

- **ERA5 minus MODSCAG** snow-cover fraction, 347 paired days: mean bias +0.161, MAE 0.162. ERA5 publishes no snow-cover fraction, so this is diagnosed from the IFS scheme, which saturates at 0.10 m of depth; a high bias is a property of that diagnostic as much as of the model.
- **MERRA-2 minus MODSCAG** snow-cover fraction, 347 paired days: mean bias -0.088, MAE 0.089.

Melt-out, the last day snow cover stays above 0.10:

- **MODSCAG**: 2023-05-20
- **ERA5**: 2023-06-04
- **MERRA-2**: 2023-04-26

