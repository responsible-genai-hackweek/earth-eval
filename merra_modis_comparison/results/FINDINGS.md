# Findings

Generated from the daily checkpoints. Do not edit by hand.

Domain: the Colorado Rocky Mountains, as 72 native MERRA-2 cells spanning
109-104W and 37-41N. Median cell elevation 2442 m; 75% of cells average
above 2000 m. The easternmost column reaches onto the High Plains
(1717 m mean) and the westernmost onto the Colorado Plateau (2003 m).

- **ERA5**: WY1981-WY2026, 46 complete water years.
- **MERRA-2**: WY1991-WY2026, 36 complete water years.

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

Ranks below are within WY1991-WY2026.

- **1 April SWE** — omitted deliberately. MERRA-2 melts this domain out almost entirely by April in most years, so the ranking within that band is noise rather than a result.
- **1 April snow depth, WY2023**: 0.1501 m — highest of 36, 492% of the record mean (+3.67 sd).
- **1 April snow depth, WY2026**: 0.00495 m — 9th lowest of 36, 16% of the record mean (-0.78 sd).
- **peak SWE, WY2023**: 54.04 mm w.e. — 5th highest of 36, 165% of the record mean (+1.36 sd).
- **peak SWE, WY2026**: 13.83 mm w.e. — lowest of 36, 42% of the record mean (-1.20 sd).
- **season-mean SWE, WY2023**: 19.2 mm w.e. — 2nd highest of 36, 221% of the record mean (+2.21 sd).
- **season-mean SWE, WY2026**: 1.665 mm w.e. — lowest of 36, 19% of the record mean (-1.48 sd).

## Do the two reanalyses agree?

Over the 36 water years both models cover (WY1991-WY2026).

- **1 April snow depth** rank correlation: rho = 0.886, p = 6.6e-13, n = 36
- **peak SWE** rank correlation: rho = 0.807, p = 2.7e-09, n = 36
- **season-mean SWE** rank correlation: rho = 0.808, p = 2.6e-09, n = 36

Rank, not magnitude. The two models' magnitude ratio varies with how thin the snowpack is, so a ratio quoted without naming the product is not a fact about Colorado.

## Satellite validation, WY2023

347 of 365 days carry a usable MODSCAG reference; 18 have none in the archive and 0 failed to fetch.

- **ERA5 minus MODSCAG** snow-cover fraction, 347 paired days: mean bias +0.161, MAE 0.162. ERA5 publishes no snow-cover fraction, so this is diagnosed from the IFS scheme, which saturates at 0.10 m of depth; a high bias is a property of that diagnostic as much as of the model.
- **MERRA-2 minus MODSCAG** snow-cover fraction, 347 paired days: mean bias -0.088, MAE 0.089.

Melt-out, the last day snow cover stays above 0.10:

- **MODSCAG**: 2023-05-20
- **ERA5**: 2023-06-04
- **MERRA-2**: 2023-04-26

