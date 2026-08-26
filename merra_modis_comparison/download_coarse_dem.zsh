#!/bin/zsh
set -euo pipefail

PROJECT_DIRECTORY=${0:A:h}
OUTPUT_PATH="$PROJECT_DIRECTORY/data/usgs_3dep_coarse_dem.tif"
mkdir -p "${OUTPUT_PATH:h}"

exec curl --fail --location --get \
  'https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage' \
  --data-urlencode 'bbox=-109.0625,36.75,-104.0625,41.25' \
  --data 'bboxSR=4326' \
  --data 'imageSR=4326' \
  --data 'size=100,90' \
  --data 'format=tiff' \
  --data 'pixelType=F32' \
  --data 'interpolation=RSP_BilinearInterpolation' \
  --data 'f=image' \
  --output "$OUTPUT_PATH"
