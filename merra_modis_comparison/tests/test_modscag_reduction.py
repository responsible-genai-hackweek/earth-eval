import h5py
import numpy as np

from merra_modis_comparison.config import TargetGrid
from merra_modis_comparison.products import TileMapping, aggregate_modscag


def test_modscag_reduction_masks_fill_and_tracks_observations(tmp_path):
    path = tmp_path / "tile.nc"
    with h5py.File(path, "w") as dataset:
        dataset.create_dataset(
            "snow_fraction", data=np.array([[[0, 100], [255, 50]]], dtype="u1")
        )
        dataset.create_dataset(
            "days_without_observation",
            data=np.array([[[0, 1], [65535, 0]]], dtype="u2")
        )
    grid = TargetGrid(
        lons=(-1.0, 0.0), lats=(40.0,), lon_indices=(0, 1), lat_indices=(0,)
    )
    mapping = TileMapping(
        tile="test", row_start=0, row_stop=2, col_start=0, col_stop=2,
        target_index=np.array([[0, 0], [1, 1]], dtype=np.int32),
        expected_counts=np.array([2, 2]),
    )
    fraction, counts, expected, observed = aggregate_modscag(
        {"test": path}, {"test": mapping}, grid
    )
    assert np.allclose(fraction, [[0.5, 0.5]])
    assert np.array_equal(counts, [[2, 1]])
    assert np.array_equal(expected, [[2, 2]])
    assert np.array_equal(observed, [[1, 1]])
