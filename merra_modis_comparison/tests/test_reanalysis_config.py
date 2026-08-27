import numpy as np
import pytest

from merra_modis_comparison.reanalysis_config import ReanalysisRunConfig


def test_era_product_grids_select_centers_inside_colorado_domain():
    config = ReanalysisRunConfig()
    era5 = config.target_grid("era5")
    era5_land = config.target_grid("era5-land")
    assert era5.shape == (17, 21)
    assert era5.size == 357
    assert era5_land.shape == (41, 51)
    assert era5_land.size == 2_091
    assert np.allclose(era5.lon_edges[[0, -1]], [-109.125, -103.875])
    assert np.allclose(era5_land.lat_edges[[0, -1]], [36.95, 41.05])
    assert era5.cell_metadata(0)["cell_id"] == "ERA5_lat+37.00_lon-109.00"
    assert era5_land.cell_metadata(era5_land.size - 1)["target_latitude"] == 41.0


def test_reanalysis_config_rejects_unknown_or_duplicate_models():
    with pytest.raises(ValueError, match="unknown reanalysis"):
        ReanalysisRunConfig(model_ids=("other",)).validate()
    with pytest.raises(ValueError, match="unique"):
        ReanalysisRunConfig(model_ids=("era5", "era5")).validate()


def test_execution_concurrency_does_not_change_product_grids():
    left = ReanalysisRunConfig(workers=1, cds_connections=1)
    right = ReanalysisRunConfig(workers=16, cds_connections=4)
    assert left.target_grid("era5") == right.target_grid("era5")
    assert left.target_grid("era5-land") == right.target_grid("era5-land")
