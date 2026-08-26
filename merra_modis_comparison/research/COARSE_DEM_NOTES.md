# Coarse terrain reference for figure context

> **Provenance:** the raster and its metadata sidecar were copied byte-identical
> from the `clinton` branch (authored by Codex) on 2026-08-26, so both
> implementations draw their figures over exactly the same terrain. This note
> records the retrieval parameters so the subset can be re-downloaded and
> verified independently.

## Files

- `data/usgs_3dep_coarse_dem.tif` — 100 × 90 float32 GeoTIFF, EPSG:4326
- `data/usgs_3dep_coarse_dem.metadata.json` — retrieval parameters sidecar

## Product

- Source: USGS 3DEP bare-earth elevation,
  <https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer>
- Access: public ArcGIS ImageServer `exportImage`; no credentials required
- Downloaded 2026-08-26

## Requested subset

```json
{
  "bbox_epsg_4326": [-109.0625, 36.75, -104.0625, 41.25],
  "shape": [90, 100],
  "pixel_size_degrees": [0.05, 0.05],
  "crs": "EPSG:4326",
  "pixel_type": "float32",
  "units": "meters",
  "interpolation": "bilinear"
}
```

The bounding box is exactly the complete-cell envelope of the 72-cell MERRA-2
target domain, so the DEM and the metric layers share one geographic frame with
no reprojection at plot time. A 0.05° grid is intentionally coarse: it is about
one twelfth of a MERRA-2 cell, enough for legible hillshade and for smooth
2,000 m and 3,000 m contours, and small enough (tens of kilobytes) to commit.

## Purpose

Hillshade underlay, labeled 2,000 m and 3,000 m contours, and mean elevation per
MERRA-2 cell for the elevation-dependence figures. Terrain is context only; it
never enters a metric.

## Cautions

- Bare-earth elevation, not surface elevation. It carries no canopy or snow
  signal, which is what makes it a neutral backdrop for an fSCA error map.
- A cell-mean elevation hides subgrid relief. An elevation-dependence plot
  therefore describes MERRA-2 cell means, not the elevation of any snowpack.
- Keep the sidecar beside the raster so a refreshed download is verifiably the
  same subset.
