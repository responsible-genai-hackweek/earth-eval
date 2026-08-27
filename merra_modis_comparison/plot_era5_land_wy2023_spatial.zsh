#!/bin/zsh
set -euo pipefail

script_directory=${0:A:h}
cd "$script_directory"

/Users/clintonalden/miniconda3/envs/env1/bin/python \
  -m merra_modis_comparison.reanalysis_spatial_plotting
