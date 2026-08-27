#!/bin/zsh
set -euo pipefail

script_directory=${0:A:h}
cd "$script_directory"

/Users/clintonalden/miniconda3/envs/env1/bin/python \
  -m merra_modis_comparison.reanalysis_cli \
  --models narr \
  --start-water-year 2010 --end-water-year 2023 \
  --west -109 --east -104 --south 37 --north 41 \
  --workers 16 --ftp-connections 8 --model-connections 4
