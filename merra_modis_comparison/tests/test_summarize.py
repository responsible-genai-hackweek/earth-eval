"""Summary layer over synthetic checkpoints - no network.

Protects the unit conversions between the two models and the rule that
MERRA-2's grid-mean depth is FRSNO * SNODP.
"""
import csv
from datetime import date, timedelta

import numpy as np
import pytest

from merra_modis_comparison.summarize import (
    load_depth_series,
    load_swe_series,
    model_agreement,
    ranked,
    summarize_model,
)


def write_year(tmp_path, model, wy, swe_profile, density=250.0, frsno=0.5):
    """Write a synthetic checkpoint for one water year."""
    start = date(wy - 1, 10, 1)
    rows = []
    for i, swe in enumerate(swe_profile):
        day = (start + timedelta(days=i)).isoformat()
        depth = swe / density  # metres, as the pipeline computes it per cell
        if model == "era5":
            rows.append([day, "final", f"{swe:.6f}", f"{density:.4f}",
                         f"{depth:.8f}", "0.5"])
        else:
            # SNOMAS is a grid mean; SNODP is in-pack depth
            snodp = (swe / density) / frsno if frsno else 0.0
            rows.append([day, f"{frsno:.8f}", f"{snodp:.8f}", f"{swe:.6f}",
                         f"{depth:.8f}"])
    header = (
        ["date", "stream", "swe_mm_we", "snow_density_kg_m3", "depth_m", "fsca"]
        if model == "era5"
        else ["date", "frsno", "snodp_m", "snomas_kg_m2", "depth_m"]
    )
    path = tmp_path / f"{model}_WY{wy}.csv"
    with path.open("w", newline="") as handle:
        w = csv.writer(handle)
        w.writerow(header)
        w.writerows(rows)
    return path


class TestLoading:
    def test_era5_swe_is_read_in_millimetres(self, tmp_path):
        write_year(tmp_path, "era5", 2020, [10.0, 20.0, 30.0])
        s = load_swe_series(tmp_path, "era5", [2020])
        np.testing.assert_allclose(s.values, [10.0, 20.0, 30.0])

    def test_merra2_snomas_is_already_millimetres_of_water(self, tmp_path):
        write_year(tmp_path, "merra2", 2020, [10.0, 20.0, 30.0])
        s = load_swe_series(tmp_path, "merra2", [2020])
        np.testing.assert_allclose(s.values, [10.0, 20.0, 30.0])

    def test_both_models_load_to_the_same_units(self, tmp_path):
        write_year(tmp_path, "era5", 2020, [42.0])
        write_year(tmp_path, "merra2", 2020, [42.0])
        a = load_swe_series(tmp_path, "era5", [2020])
        b = load_swe_series(tmp_path, "merra2", [2020])
        assert a.values[0] == pytest.approx(b.values[0])

    def test_a_missing_year_is_skipped_not_faked(self, tmp_path):
        write_year(tmp_path, "era5", 2020, [1.0])
        s = load_swe_series(tmp_path, "era5", [2019, 2020, 2021])
        assert len(s) == 1

    def test_dates_come_back_in_order(self, tmp_path):
        write_year(tmp_path, "era5", 2020, list(range(40)))
        s = load_swe_series(tmp_path, "era5", [2020])
        assert list(s.dates) == sorted(s.dates)


class TestDepthConversion:
    def test_merra2_depth_multiplies_by_snow_covered_fraction(self, tmp_path):
        write_year(tmp_path, "merra2", 2020, [50.0], density=250.0, frsno=0.5)
        depth = load_depth_series(tmp_path, "merra2", [2020])
        # 50 kg/m2 over 250 kg/m3 = 0.2 m of grid-mean depth
        assert depth.values[0] == pytest.approx(0.2)

    def test_era5_depth_divides_water_equivalent_by_density(self, tmp_path):
        write_year(tmp_path, "era5", 2020, [50.0], density=250.0)
        depth = load_depth_series(tmp_path, "era5", [2020])
        assert depth.values[0] == pytest.approx(0.2)

    def test_the_two_models_agree_on_depth_for_identical_inputs(self, tmp_path):
        write_year(tmp_path, "era5", 2020, [50.0], density=250.0)
        write_year(tmp_path, "merra2", 2020, [50.0], density=250.0, frsno=0.4)
        a = load_depth_series(tmp_path, "era5", [2020])
        b = load_depth_series(tmp_path, "merra2", [2020])
        assert a.values[0] == pytest.approx(b.values[0])


class TestDepthIsNotRederivedFromDomainMeans:
    """The mean of a ratio is not the ratio of means.

    Depth must be computed per cell and then averaged. Re-deriving it from
    already-averaged SWE and density understates or overstates it - on real
    dry-year fields by about a factor of two, because low water equivalent and
    low density coincide in space.
    """

    def test_the_stored_column_is_used_verbatim(self, tmp_path):
        path = write_year(tmp_path, "era5", 2020, [50.0], density=250.0)
        text = path.read_text().replace("0.20000000", "0.09700000")
        path.write_text(text)
        depth = load_depth_series(tmp_path, "era5", [2020])
        assert depth.values[0] == pytest.approx(0.097), (
            "depth must come from the stored per-cell average, not be recomputed "
            "from the domain-mean SWE and density"
        )

    def test_a_missing_depth_column_is_null_not_guessed(self, tmp_path):
        path = write_year(tmp_path, "merra2", 2020, [50.0], density=250.0, frsno=0.4)
        lines = path.read_text().splitlines()
        trimmed = [",".join(line.split(",")[:-1]) for line in lines]
        path.write_text("\n".join(trimmed) + "\n")
        depth = load_depth_series(tmp_path, "merra2", [2020])
        assert np.isnan(depth.values[0])

    def test_the_two_orderings_actually_differ(self):
        """Guard against the fix being reverted as a no-op."""
        from merra_modis_comparison.snowvars import geometric_depth_m

        swe = np.array([1.0, 1.0, 200.0])
        rho = np.array([120.0, 120.0, 400.0])
        mean_of_ratio = float(np.mean(geometric_depth_m(swe, rho)))
        ratio_of_means = float(geometric_depth_m(swe.mean(), rho.mean()))
        assert abs(mean_of_ratio - ratio_of_means) / mean_of_ratio > 0.10


class TestSummary:
    def test_peak_and_april_first_are_found(self, tmp_path):
        # WY2020 is a leap year: 1 Oct + 183 days is 1 April
        profile = [0.0] * 183 + [100.0] + [0.0] * 100
        write_year(tmp_path, "era5", 2020, profile)
        stats = summarize_model(tmp_path, "era5", [2020])[0]
        assert stats.peak_swe_mm == pytest.approx(100.0)
        assert stats.peak_day == date(2020, 4, 1)
        assert stats.april_first_swe_mm == pytest.approx(100.0)

    def test_melt_out_follows_the_peak(self, tmp_path):
        profile = [0.0] * 100 + [80.0] * 60 + [1.0] * 100
        write_year(tmp_path, "era5", 2020, profile)
        stats = summarize_model(tmp_path, "era5", [2020])[0]
        assert stats.melt_out == date(2019, 10, 1) + timedelta(days=160)

    def test_a_year_with_no_checkpoint_is_absent(self, tmp_path):
        write_year(tmp_path, "era5", 2020, [1.0] * 10)
        assert [s.water_year for s in summarize_model(tmp_path, "era5", [2019, 2020])] == [2020]


class TestRankingAndAgreement:
    def test_the_lowest_year_ranks_one(self, tmp_path):
        for wy, level in ((2018, 90.0), (2019, 50.0), (2020, 10.0)):
            write_year(tmp_path, "era5", wy, [level] * 200)
        stats = summarize_model(tmp_path, "era5", [2018, 2019, 2020])
        table = ranked(stats, "peak_swe_mm")
        assert table[2020][1] == 1
        assert table[2018][1] == 3

    def test_models_can_agree_on_rank_while_differing_in_magnitude(self, tmp_path):
        for wy, level in ((2018, 90.0), (2019, 50.0), (2020, 10.0)):
            write_year(tmp_path, "era5", wy, [level] * 200)
            write_year(tmp_path, "merra2", wy, [level / 3.12] * 200)
        a = summarize_model(tmp_path, "era5", [2018, 2019, 2020])
        b = summarize_model(tmp_path, "merra2", [2018, 2019, 2020])
        rho, _, n = model_agreement(a, b, "peak_swe_mm")
        assert n == 3
        assert rho == pytest.approx(1.0)
