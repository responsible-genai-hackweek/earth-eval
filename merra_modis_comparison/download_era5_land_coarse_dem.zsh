#!/bin/zsh
set -euo pipefail

project_directory=${0:A:h}
output_path="$project_directory/data/usgs_3dep_era5_land_coarse_dem.tif"
mkdir -p "${output_path:h}"

exec curl --fail --location --get \
  'https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage' \
  --data-urlencode 'bbox=-109.05,36.95,-103.95,41.05' \
  --data 'bboxSR=4326' \
  --data 'imageSR=4326' \
  --data 'size=102,82' \
  --data 'format=tiff' \
  --data 'pixelType=F32' \
  --data 'interpolation=RSP_BilinearInterpolation' \
  --data 'f=image' \
  --output "$output_path"
