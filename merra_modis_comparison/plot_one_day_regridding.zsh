#!/bin/zsh
set -euo pipefail

PROJECT_DIRECTORY=${0:A:h}
cd "$PROJECT_DIRECTORY"

TASK_MPL_CACHE=${TMPDIR:-/tmp}/merra-modis-matplotlib-cache
mkdir -p "$TASK_MPL_CACHE"
export MPLCONFIGDIR="$TASK_MPL_CACHE"

exec /Users/clintonalden/miniconda3/envs/env1/bin/python \
  -m merra_modis_comparison.regridding_diagnostic \
  --date 2023-01-15 \
  --output results/modscag_merra_grid_diagnostic_2023-01-15.png
