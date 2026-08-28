import io
from datetime import date

import numpy as np
import pytest

from fsca_eval import config, earthdata


def test_with_backoff_returns_immediately_on_success():
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    result = earthdata.with_backoff(fn, backoffs=(1, 2, 3), sleep=lambda s: (_ for _ in ()).throw(AssertionError("should not sleep")))
    assert result == "ok"
    assert len(calls) == 1


def test_with_backoff_retries_transient_errors_with_correct_sleep_schedule():
    attempts = {"n": 0}
    sleeps = []

    def fn():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise earthdata.TransientFetchError("421 too many connections")
        return "recovered"

    result = earthdata.with_backoff(fn, backoffs=(5, 10, 20), sleep=sleeps.append)
    assert result == "recovered"
    assert attempts["n"] == 3
    assert sleeps == [5, 10]


def test_with_backoff_exhausts_retries_and_raises_last_transient_error():
    sleeps = []

    def fn():
        raise earthdata.TransientFetchError("always fails")

    with pytest.raises(earthdata.TransientFetchError):
        earthdata.with_backoff(fn, backoffs=(1, 2), sleep=sleeps.append)
    assert sleeps == [1, 2]


def test_with_backoff_never_retries_fatal_errors():
    calls = []

    def fn():
        calls.append(1)
        raise earthdata.FatalFetchError("auth failure")

    with pytest.raises(earthdata.FatalFetchError):
        earthdata.with_backoff(fn, backoffs=(1, 2, 3), sleep=lambda s: (_ for _ in ()).throw(AssertionError("should not sleep")))
    assert len(calls) == 1


def test_ftp_slot_pool_bounds_concurrent_holders():
    import threading
    import time

    pool = earthdata.FtpSlotPool(slots=2)
    concurrent_count = {"current": 0, "max": 0}
    lock = threading.Lock()

    def worker():
        with pool:
            with lock:
                concurrent_count["current"] += 1
                concurrent_count["max"] = max(concurrent_count["max"], concurrent_count["current"])
            time.sleep(0.05)
            with lock:
                concurrent_count["current"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert concurrent_count["max"] <= 2


def test_month_requeue_queue_fifo_and_requeue_to_back():
    queue = earthdata.MonthRequeueQueue([(2020, 1), (2020, 2), (2020, 3)])
    assert len(queue) == 3
    first = queue.pop()
    assert first == (2020, 1)
    queue.requeue_to_back(first)
    assert len(queue) == 3
    assert queue.pop() == (2020, 2)
    assert queue.pop() == (2020, 3)
    assert queue.pop() == (2020, 1)
    assert queue.pop() is None


def test_create_session_wraps_login_failure_as_fatal():
    def failing_login():
        raise RuntimeError("bad credentials")

    with pytest.raises(earthdata.FatalFetchError):
        earthdata.create_session(login_fn=failing_login)


def test_create_session_returns_login_result_on_success():
    session = earthdata.create_session(login_fn=lambda: "fake-session")
    assert session == "fake-session"


# --- RealTransport.fetch_merra_subset --------------------------------------


def _build_fake_merra_netcdf(*, domain_values=None):
    """A synthetic MERRA-2-shaped granule truncated to just cover our domain's
    global index range (114:122 lon, 254:263 lat), so the file is small but
    the real index math in `merra_domain_index_ranges` still applies.
    """
    import xarray as xr

    lon_size = 122
    lat_size = 263
    time_size = config.MERRA_TIME_INDEX + 1

    lon = np.arange(lon_size) * config.LON_SPACING + earthdata.MERRA_GLOBAL_LON_MIN
    lat = np.arange(lat_size) * config.LAT_SPACING + earthdata.MERRA_GLOBAL_LAT_MIN

    if domain_values is None:
        domain_values = (
            np.arange(config.N_LAT_CELLS)[:, None] * config.N_LON_CELLS + np.arange(config.N_LON_CELLS)[None, :]
        ) / 100.0

    frsno = np.zeros((time_size, lat_size, lon_size), dtype=np.float32)
    frsno[config.MERRA_TIME_INDEX, -config.N_LAT_CELLS :, -config.N_LON_CELLS :] = domain_values

    ds = xr.Dataset(
        {"FRSNO": (("time", "lat", "lon"), frsno)},
        coords={"time": np.arange(time_size), "lat": lat, "lon": lon},
    )
    buf = io.BytesIO()
    ds.to_netcdf(buf, engine="h5netcdf")
    return buf.getvalue(), domain_values


class _FakeResponse:
    def __init__(self, status_code, content=b"", text=""):
        self.status_code = status_code
        self.content = content
        self.text = text


class _FakeHttpSession:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        return self._response


def test_merra_granule_url_matches_documented_convention():
    url = earthdata.merra_granule_url(date(2020, 2, 15), 400)
    assert url == (
        "https://data.gesdisc.earthdata.nasa.gov/data/MERRA2/M2T1NXLND.5.12.4/"
        "2020/02/MERRA2_400.tavg1_2d_lnd_Nx.20200215.nc4"
    )


def test_merra_domain_index_ranges_match_confirmed_global_grid_offsets():
    lon_slice, lat_slice = earthdata.merra_domain_index_ranges()
    assert lon_slice == slice(114, 122)
    assert lat_slice == slice(254, 263)


def test_fetch_merra_subset_decodes_domain_and_matches_config_grid():
    content, domain_values = _build_fake_merra_netcdf()
    http_session = _FakeHttpSession(_FakeResponse(200, content=content))
    transport = earthdata.RealTransport(session=http_session, ftp_pool=earthdata.FtpSlotPool(1))

    result = transport.fetch_merra_subset(date(2020, 2, 15), 400)

    assert result.stream == 400
    assert np.allclose(result.lon_centers, config.CELL_LON_CENTERS)
    assert np.allclose(result.lat_centers, config.CELL_LAT_CENTERS)
    assert np.allclose(result.frsno, domain_values)
    assert http_session.calls == [earthdata.merra_granule_url(date(2020, 2, 15), 400)]


def test_fetch_merra_subset_unwraps_auth_object_via_get_session():
    content, _ = _build_fake_merra_netcdf()
    http_session = _FakeHttpSession(_FakeResponse(200, content=content))

    class FakeAuth:
        def get_session(self):
            return http_session

    transport = earthdata.RealTransport(session=FakeAuth(), ftp_pool=earthdata.FtpSlotPool(1))
    result = transport.fetch_merra_subset(date(2020, 2, 15), 400)
    assert result.frsno.shape == (config.N_LAT_CELLS, config.N_LON_CELLS)


def test_fetch_merra_subset_raises_fatal_on_eula_style_403():
    http_session = _FakeHttpSession(
        _FakeResponse(403, text='{"error_description":"EULA Acceptance Failure"}')
    )
    transport = earthdata.RealTransport(session=http_session, ftp_pool=earthdata.FtpSlotPool(1))
    with pytest.raises(earthdata.FatalFetchError):
        transport.fetch_merra_subset(date(2020, 2, 15), 400)


def test_fetch_merra_subset_raises_transient_on_5xx():
    http_session = _FakeHttpSession(_FakeResponse(503, text="service unavailable"))
    transport = earthdata.RealTransport(session=http_session, ftp_pool=earthdata.FtpSlotPool(1))
    with pytest.raises(earthdata.TransientFetchError):
        transport.fetch_merra_subset(date(2020, 2, 15), 400)


def test_fetch_merra_subset_raises_transient_on_request_exception():
    import requests

    class RaisingSession:
        def get(self, url, timeout=None):
            raise requests.exceptions.ConnectionError("boom")

    transport = earthdata.RealTransport(session=RaisingSession(), ftp_pool=earthdata.FtpSlotPool(1))
    with pytest.raises(earthdata.TransientFetchError):
        transport.fetch_merra_subset(date(2020, 2, 15), 400)


def test_fetch_merra_subset_raises_fatal_on_out_of_range_values():
    domain_values = np.full((config.N_LAT_CELLS, config.N_LON_CELLS), 5.0)
    content, _ = _build_fake_merra_netcdf(domain_values=domain_values)
    http_session = _FakeHttpSession(_FakeResponse(200, content=content))
    transport = earthdata.RealTransport(session=http_session, ftp_pool=earthdata.FtpSlotPool(1))

    with pytest.raises(earthdata.FatalFetchError):
        transport.fetch_merra_subset(date(2020, 2, 15), 400)


def test_fetch_merra_subset_raises_fatal_on_undecodable_content():
    http_session = _FakeHttpSession(_FakeResponse(200, content=b"not a netcdf file"))
    transport = earthdata.RealTransport(session=http_session, ftp_pool=earthdata.FtpSlotPool(1))

    with pytest.raises(earthdata.FatalFetchError):
        transport.fetch_merra_subset(date(2020, 2, 15), 400)


# --- RealTransport.fetch_modscag_tiles --------------------------------------


def test_modscag_domain_tiles_matches_confirmed_three_tiles():
    assert earthdata.modscag_domain_tiles() == ("h09v04", "h09v05", "h10v04")


def test_modscag_remote_path_matches_documented_convention():
    path = earthdata.modscag_remote_path("h09v04", date(2020, 2, 15))
    assert path == (
        "/pub/DATASETS/STC_MODSCGDRF_HIST_v1/h09v04/2020/"
        "STC_MODSCGDRF_HIST_h09v04_20200215_v01.0.nc"
    )


def _build_fake_modscag_netcdf(tile, *, fill_value_snow=255, snow_value=40.0, dwo_value=0):
    """A full 2400x2400 synthetic granule (matching the real archive's shape)
    with the domain-crop region set to known test values and everything else
    left at the fill sentinel, so real crop indices apply unmodified.
    """
    import xarray as xr

    row_slice, col_slice = earthdata.modscag_domain_crop(tile)
    n = earthdata.MODSCAG_TILE_PIXELS

    snow = np.full((1, n, n), fill_value_snow, dtype=np.uint8)
    dwo = np.zeros((1, n, n), dtype=np.uint16)
    snow[0, row_slice, col_slice] = snow_value
    dwo[0, row_slice, col_slice] = dwo_value

    x, y = earthdata._modscag_tile_pixel_centers(tile)
    ds = xr.Dataset(
        {
            "snow_fraction": (("time", "y", "x"), snow),
            "days_without_observation": (("time", "y", "x"), dwo),
        },
        coords={"time": [0], "y": y, "x": x},
    )
    buf = io.BytesIO()
    ds.to_netcdf(buf, engine="h5netcdf")
    return buf.getvalue()


class _FakeFtp:
    def __init__(self, content, *, raise_on_retr=None):
        self._content = content
        self._raise_on_retr = raise_on_retr
        self.quit_called = False
        self.retrieved_paths = []

    def retrbinary(self, cmd, callback):
        if self._raise_on_retr is not None:
            raise self._raise_on_retr
        self.retrieved_paths.append(cmd)
        callback(self._content)

    def quit(self):
        self.quit_called = True

    def close(self):
        pass


def test_fetch_modscag_tiles_decodes_all_three_tiles(tmp_path):
    tiles_in_order = list(earthdata.modscag_domain_tiles())
    contents = {tile: _build_fake_modscag_netcdf(tile) for tile in tiles_in_order}
    ftps = []

    def ftp_factory():
        tile = tiles_in_order[len(ftps)]
        ftp = _FakeFtp(contents[tile])
        ftps.append(ftp)
        return ftp

    transport = earthdata.RealTransport(
        session=None, ftp_pool=earthdata.FtpSlotPool(1), ftp_factory=ftp_factory
    )

    result = transport.fetch_modscag_tiles(date(2020, 2, 15), str(tmp_path))

    assert len(result) == 3
    for tile_result in result:
        assert np.all(tile_result.snow_fraction == 40.0)
        assert np.all(tile_result.days_without_observation == 0)
        assert tile_result.pixel_x_sinusoidal.shape == tile_result.snow_fraction.shape
    assert all(ftp.quit_called for ftp in ftps)
    assert list(tmp_path.iterdir()) == []  # granules deleted immediately


def test_fetch_modscag_tiles_raises_transient_on_ftp_error_temp(tmp_path):
    from ftplib import error_temp

    def ftp_factory():
        return _FakeFtp(b"", raise_on_retr=error_temp("421 too many connections"))

    transport = earthdata.RealTransport(
        session=None, ftp_pool=earthdata.FtpSlotPool(1), ftp_factory=ftp_factory
    )
    with pytest.raises(earthdata.TransientFetchError):
        transport.fetch_modscag_tiles(date(2020, 2, 15), str(tmp_path))


def test_fetch_modscag_tiles_raises_fatal_on_ftp_error_perm(tmp_path):
    from ftplib import error_perm

    def ftp_factory():
        return _FakeFtp(b"", raise_on_retr=error_perm("550 no such file"))

    transport = earthdata.RealTransport(
        session=None, ftp_pool=earthdata.FtpSlotPool(1), ftp_factory=ftp_factory
    )
    with pytest.raises(earthdata.FatalFetchError):
        transport.fetch_modscag_tiles(date(2020, 2, 15), str(tmp_path))


def test_fetch_modscag_tiles_raises_transient_on_connection_failure(tmp_path):
    def ftp_factory():
        raise OSError("connection refused")

    transport = earthdata.RealTransport(
        session=None, ftp_pool=earthdata.FtpSlotPool(1), ftp_factory=ftp_factory
    )
    with pytest.raises(earthdata.TransientFetchError):
        transport.fetch_modscag_tiles(date(2020, 2, 15), str(tmp_path))


def test_fetch_modscag_tiles_raises_fatal_on_undecodable_content(tmp_path):
    def ftp_factory():
        return _FakeFtp(b"not a netcdf file")

    transport = earthdata.RealTransport(
        session=None, ftp_pool=earthdata.FtpSlotPool(1), ftp_factory=ftp_factory
    )
    with pytest.raises(earthdata.FatalFetchError):
        transport.fetch_modscag_tiles(date(2020, 2, 15), str(tmp_path))
    assert list(tmp_path.iterdir()) == []  # cleaned up even on failure
