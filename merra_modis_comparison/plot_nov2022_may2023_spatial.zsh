#!/bin/zsh
set -euo pipefail

PROJECT_DIRECTORY=${0:A:h}
cd "$PROJECT_DIRECTORY"

exec /Users/clintonalden/miniconda3/envs/env1/bin/python \
  -m merra_modis_comparison.spatial_plotting
