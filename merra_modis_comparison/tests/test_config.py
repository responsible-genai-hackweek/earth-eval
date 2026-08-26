from datetime import date

import pytest

from merra_modis_comparison.config import (
    RunConfig,
    season_for_month,
    water_year_for_date,
)
from merra_modis_comparison.products import (
    archived_tiles_for_grid,
    merra_opendap_url,
    merra_stream_for_date,
    tiles_for_grid,
)


def test_multiyear_grid_dates_months_and_tiles():
    config = RunConfig()
    grid = config.target_grid
    assert grid.shape == (9, 8)
    assert grid.size == 72
    assert grid.lats[0] == 37.0
    assert grid.lats[-1] == 41.0
    assert grid.lons[0] == -108.75
    assert grid.lons[-1] == -104.375
    assert tiles_for_grid(grid) == ("h09v04", "h09v05", "h10v04", "h10v05")
    assert archived_tiles_for_grid(grid) == ("h09v04", "h09v05", "h10v04")
    assert len(config.dates) == 5_113
    assert len(config.calendar_months) == 168
    assert config.calendar_months[0] == (2009, 10)
    assert config.calendar_months[-1] == (2023, 9)
    assert config.workers == 16
    assert config.ftp_connections == 8


def test_stable_cell_identity():
    grid = RunConfig().target_grid
    first = grid.cell_metadata(0)
    last = grid.cell_metadata(71)
    assert first == {
        "cell_id": "MERRA2_i254_j114",
        "merra_latitude": 37.0,
        "merra_longitude": -108.75,
        "merra_latitude_index": 254,
        "merra_longitude_index": 114,
    }
    assert last["merra_latitude"] == 41.0
    assert last["merra_longitude"] == -104.375


def test_water_year_and_seasons():
    assert water_year_for_date(date(2009, 10, 1)) == 2010
    assert water_year_for_date(date(2010, 9, 30)) == 2010
    assert season_for_month(10) == "SON"
    assert season_for_month(1) == "DJF"
    assert season_for_month(4) == "MAM"
    assert season_for_month(7) == "JJA"


def test_merra_production_stream_boundary():
    assert merra_stream_for_date(date(2010, 12, 31)) == 300
    assert merra_stream_for_date(date(2011, 1, 1)) == 400
    assert merra_stream_for_date(date(2020, 8, 31)) == 400
    assert merra_stream_for_date(date(2020, 9, 1)) == 401
    assert merra_stream_for_date(date(2020, 9, 30)) == 401
    assert merra_stream_for_date(date(2020, 10, 1)) == 400
    assert merra_stream_for_date(date(2021, 5, 31)) == 400
    assert merra_stream_for_date(date(2021, 6, 1)) == 401
    assert merra_stream_for_date(date(2021, 9, 30)) == 401
    assert merra_stream_for_date(date(2021, 10, 1)) == 400
    assert "MERRA2_300" in merra_opendap_url(date(2009, 10, 1))
    assert "MERRA2_401" in merra_opendap_url(date(2020, 9, 1))
    assert "MERRA2_400" in merra_opendap_url(date(2023, 9, 30))


def test_historical_product_end_is_enforced():
    with pytest.raises(ValueError, match="ends 2023-09-30"):
        RunConfig(end_water_year=2024).validate()


def test_ftp_connection_limit_stays_below_archive_cap():
    RunConfig(ftp_connections=9).validate()
    with pytest.raises(ValueError, match="10-connection"):
        RunConfig(ftp_connections=10).validate()
