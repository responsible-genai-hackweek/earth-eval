#!/bin/zsh
set -euo pipefail

PROJECT_DIRECTORY=${0:A:h}
cd "$PROJECT_DIRECTORY"

TASK_MPL_CACHE=${TMPDIR:-/tmp}/merra-modis-matplotlib-cache
mkdir -p "$TASK_MPL_CACHE"
export MPLCONFIGDIR="$TASK_MPL_CACHE"

exec /Users/clintonalden/miniconda3/envs/env1/bin/python \
  -m merra_modis_comparison.wet_dry_bias_significance \
  --workers 16
