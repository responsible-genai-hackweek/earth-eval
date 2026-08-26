#!/bin/zsh
set -euo pipefail

PROJECT_DIRECTORY=${0:A:h}
cd "$PROJECT_DIRECTORY"

exec /Users/clintonalden/miniconda3/envs/env1/bin/python -m merra_modis_comparison \
  --start-water-year 2010 \
  --end-water-year 2023 \
  --west -109 \
  --east -104 \
  --south 37 \
  --north 41 \
  --workers 16 \
  --ftp-connections 8 \
  --max-runtime-minutes 30
