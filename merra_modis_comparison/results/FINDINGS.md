# Findings

Generated from the daily checkpoints. Do not edit by hand.

Domain: the Colorado Rocky Mountains, as 72 native MERRA-2 cells spanning
109-104W and 37-41N. Median cell elevation 2442 m; 75% of cells average
above 2000 m. The easternmost column reaches onto the High Plains
(1717 m mean) and the westernmost onto the Colorado Plateau (2003 m).

- **ERA5**: WY1981-WY2026, 46 complete water years.
- **MERRA-2**: WY1981-WY2026, 46 complete water years.

## ERA5

Ranks below are within WY1981-WY2026.

- **April 1st SWE, WY2023**: 7.937 in — highest of 46, 173% of the record mean (+2.18 sd).
- **April 1st SWE, WY2026**: 1.888 in — lowest of 46, 41% of the record mean (-1.76 sd).
- **April 1st snow depth, WY2023**: 29.85 in — 2nd highest of 46, 176% of the record mean (+2.12 sd).
- **April 1st snow depth, WY2026**: 5.325 in — lowest of 46, 31% of the record mean (-1.93 sd).
- **peak SWE, WY2023**: 8.048 in — highest of 46, 152% of the record mean (+2.12 sd).
- **peak SWE, WY2026**: 3.143 in — 3rd lowest of 46, 60% of the record mean (-1.64 sd).
- **season-mean SWE, WY2023**: 3.334 in — 5th highest of 46, 144% of the record mean (+1.37 sd).
- **season-mean SWE, WY2026**: 1.103 in — 2nd lowest of 46, 47% of the record mean (-1.66 sd).

## MERRA-2

Ranks below are within WY1981-WY2026.

- **April 1st SWE** — omitted deliberately. MERRA-2 melts this domain out almost entirely by April in most years, so the ranking within that band is noise rather than a result.
- **April 1st snow depth, WY2023**: 7.849 in — highest of 46, 515% of the record mean (+3.98 sd).
- **April 1st snow depth, WY2026**: 0.2555 in — 10th lowest of 46, 17% of the record mean (-0.80 sd).
- **peak SWE, WY2023**: 2.803 in — 6th highest of 46, 176% of the record mean (+1.52 sd).
- **peak SWE, WY2026**: 0.6836 in — 4th lowest of 46, 43% of the record mean (-1.14 sd).
- **season-mean SWE, WY2023**: 0.9825 in — 3rd highest of 46, 228% of the record mean (+2.23 sd).
- **season-mean SWE, WY2026**: 0.08254 in — 2nd lowest of 46, 19% of the record mean (-1.42 sd).

## Do the two reanalyses agree?

Over the 46 water years both models cover (WY1981-WY2026).

- **April 1st snow depth** rank correlation: rho = 0.881, p = 6.3e-16, n = 46
- **peak SWE** rank correlation: rho = 0.734, p = 6.3e-09, n = 46
- **season-mean SWE** rank correlation: rho = 0.781, p = 1.6e-10, n = 46

Rank, not magnitude. The two models' magnitude ratio varies with how thin the snowpack is, so a ratio quoted without naming the product is not a fact about Colorado.

## How far apart are the two models?

- **Peak SWE, mean over water years**: ERA5 5.28 in, MERRA-2 1.59 in — a factor of 3.3.
- **Wettest MERRA-2 year against ERA5's median year**: 3.94 in versus 5.12 in. The two ensembles barely overlap.
- **Water years where MERRA-2 exceeds ERA5's mean**: 0 of 46.

A ratio between the two is not a fact about the mountains. Quote the product with any figure taken from one of them.

## By elevation band

A domain mean averages the bands together. Splitting them shows whether a deficit was uniform.

- **6,500–8,000 ft, WY2023 April 1st SWE**: 6.63 in — 297% of the band mean (2.23 in), rank 46 of 46.
- **6,500–8,000 ft, WY2026 April 1st SWE**: 0.12 in — 5% of the band mean (2.23 in), rank 1 of 46.
- **8,000–14,500 ft, WY2023 April 1st SWE**: 8.93 in — 140% of the band mean (6.37 in), rank 42 of 46.
- **8,000–14,500 ft, WY2026 April 1st SWE**: 3.23 in — 51% of the band mean (6.37 in), rank 2 of 46.

## Satellite validation, WY2023

347 of 365 days carry a usable MODSCAG reference; 18 have none in the archive and 0 failed to fetch.

- **ERA5 minus MODSCAG** snow-cover fraction, 347 paired days: mean bias +0.231, MAE 0.232. ERA5 publishes no snow-cover fraction, so this is diagnosed from the IFS scheme, which saturates at 0.10 m of depth; a high bias is a property of that diagnostic as much as of the model.
- **MERRA-2 minus MODSCAG** snow-cover fraction, 347 paired days: mean bias -0.043, MAE 0.057.

Melt-out, the last day snow cover stays above 0.10:

- **MODSCAG**: 2023-05-20
- **ERA5**: 2023-06-08
- **MERRA-2**: 2023-04-26

