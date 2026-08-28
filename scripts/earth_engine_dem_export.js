// Earth Engine Code Editor snippet (code.earthengine.google.com).
//
// Exports a USGS 3DEP DEM over the MERRA-2/MODSCAG comparison domain
// (config.DOMAIN_LON_EDGE_MIN/MAX, DOMAIN_LAT_EDGE_MIN/MAX) at the same
// 800x600 display grid terrain.fetch_dem() uses by default. This is a
// cosmetic hillshade/contour basemap, not a science-resolution grid --
// it intentionally does NOT match the MERRA-2 (0.625x0.5 deg) or MODSCAG
// (~463 m) grids. Sized this way (rather than at 3DEP's native 10 m,
// which would be several GB over this domain) so the output is small
// enough to save as a real test fixture in tests/fixtures/.
//
// Paste into the Code Editor and Run. The console will print a direct
// download URL (no Drive export/task needed at this size).

var aoi = ee.Geometry.Rectangle([-109.0625, 36.75, -104.0625, 41.25], 'EPSG:4326', false);
var WIDTH_PX = 800;
var HEIGHT_PX = 600;

var dem = ee.Image('USGS/3DEP/10m').select('elevation').clip(aoi);
// Fallback with full global coverage if 3DEP has gaps: ee.Image('USGS/SRTMGL1_003')

Map.centerObject(aoi, 7);
Map.addLayer(dem, {min: 1500, max: 4300, palette: ['#2b6cb0', '#f0e6d2', '#8b5a2b', '#ffffff']}, 'DEM');

print('Download URL (save as tests/fixtures/domain_dem_3dep.tif):',
  dem.getDownloadURL({
    region: aoi,
    dimensions: WIDTH_PX + 'x' + HEIGHT_PX,
    format: 'GEO_TIFF'
  })
);
