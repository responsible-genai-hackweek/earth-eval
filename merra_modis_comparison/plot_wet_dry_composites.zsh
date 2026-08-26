#!/bin/zsh
set -euo pipefail

PROJECT_DIRECTORY=${0:A:h}
cd "$PROJECT_DIRECTORY"

/Users/clintonalden/miniconda3/envs/env1/bin/python \
  -m merra_modis_comparison.modis_fsca_stats \
  --workers 16 \
  --ftp-connections 8

exec /Users/clintonalden/miniconda3/envs/env1/bin/python \
  -m merra_modis_comparison.composite_plotting \
  --workers 16
