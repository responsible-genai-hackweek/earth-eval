"""Season-shape statistics, and the properties the comparison depends on."""

import numpy as np
import pytest

from merra_modis_comparison.figures import beeswarm_offsets
from merra_modis_comparison.seasonshape import (
    METRICS,
    adjust_to_elevation,
    elevation_gradient,
    normalised_composite,
    season_shape,
)


def bell(peak_day=150.0, width=100.0, height=10.0, days=365):
    day = np.arange(float(days))
    value = height * np.cos((day - peak_day) / width * (np.pi / 2)) ** 2
    return day, np.where(np.abs(day - peak_day) <= width, value, 0.0)


def test_symmetric_season_puts_centroid_on_the_peak():
    day, value = bell()
    shape = season_shape(day, value)
    assert shape.peak == pytest.approx(150.0)
    assert shape.centroid == pytest.approx(150.0, abs=0.5)


def test_metrics_are_invariant_under_uniform_rescaling():
    """The whole method rests on this: a 3-11x magnitude difference between two
    models must not leak into a timing result."""
    day, value = bell()
    small, large = season_shape(day, value), season_shape(day, value * 1000.0)
    for metric in METRICS:
        assert getattr(small, metric) == pytest.approx(getattr(large, metric))


def test_onset_and_melt_out_bracket_the_peak_at_the_stated_fraction():
    day, value = bell()
    shape = season_shape(day, value, fraction=0.5)
    assert shape.onset < shape.peak < shape.melt_out
    assert value[int(shape.onset)] > 0.5 * shape.peak_value
    assert value[int(shape.melt_out)] < 0.5 * shape.peak_value


def test_floor_rejects_a_member_with_no_real_season():
    day, value = bell(height=1.0)
    assert season_shape(day, value, floor=5.0) is None
    assert season_shape(day, value, floor=0.5) is not None


def test_empty_and_all_zero_members_are_rejected_not_raised():
    assert season_shape(np.arange(10.0), np.zeros(10)) is None
    assert season_shape(np.array([]), np.array([])) is None


def test_missing_days_are_read_as_zero_not_propagated():
    day, value = bell()
    holed = value.copy()
    holed[7] = np.nan
    assert season_shape(day, holed).peak == season_shape(day, value).peak


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError):
        season_shape(np.arange(5.0), np.arange(4.0))


def test_composite_peaks_at_one_even_when_members_peak_on_different_days():
    """The regression this guards: a per-day median of members that each reach
    1.0 tops out below 1.0, by an amount that tracks peak-date dispersion. Left
    uncorrected that puts timing dispersion on an axis labelled fraction of
    peak, where it reads as magnitude."""
    days, values, members = [], [], []
    for index, peak_day in enumerate((110.0, 150.0, 190.0)):
        day, value = bell(peak_day=peak_day)
        days.append(day)
        values.append(value)
        members.append(np.full(day.size, f"m{index}"))
    _, composite = normalised_composite(
        np.concatenate(days), np.concatenate(values), np.concatenate(members)
    )
    assert composite.max() == pytest.approx(1.0)


def test_composite_ignores_member_magnitude():
    days, values, members = [], [], []
    for index, height in enumerate((1.0, 1000.0)):
        day, value = bell(height=height)
        days.append(day)
        values.append(value)
        members.append(np.full(day.size, f"m{index}"))
    grid, composite = normalised_composite(
        np.concatenate(days), np.concatenate(values), np.concatenate(members)
    )
    _, single = normalised_composite(*bell(), np.full(365, "one"))
    assert composite == pytest.approx(single)


def test_elevation_gradient_recovers_a_known_slope():
    elevation = np.linspace(8000.0, 12000.0, 40)
    metric = 100.0 + 0.01 * elevation
    slope, intercept, r = elevation_gradient(elevation, metric)
    assert slope == pytest.approx(0.01)
    assert intercept == pytest.approx(100.0)
    assert r == pytest.approx(1.0)


def test_elevation_gradient_refuses_too_few_points():
    slope, _, _ = elevation_gradient(np.array([1.0, 2.0]), np.array([1.0, 2.0]))
    assert np.isnan(slope)


def test_adjustment_collapses_a_pure_elevation_signal_onto_the_target():
    elevation = np.linspace(8000.0, 12000.0, 40)
    metric = 100.0 + 0.01 * elevation
    slope, _, _ = elevation_gradient(elevation, metric)
    adjusted = adjust_to_elevation(metric, elevation, slope, 9103.0)
    assert adjusted == pytest.approx(np.full(40, 100.0 + 0.01 * 9103.0))


def test_beeswarm_is_deterministic_and_separates_collisions():
    values = np.array([10.0, 10.0, 10.0, 60.0])
    first = beeswarm_offsets(values, width=2.0, step=0.1)
    assert first == pytest.approx(beeswarm_offsets(values, width=2.0, step=0.1))
    assert len(set(first[:3])) == 3          # the three coincident points separate
    assert first[3] == 0.0                   # the isolated one is not displaced


def test_beeswarm_leaves_well_separated_points_on_the_line():
    values = np.linspace(0.0, 100.0, 11)
    assert beeswarm_offsets(values, width=2.0, step=0.1) == pytest.approx(np.zeros(11))
