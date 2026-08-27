"""End-to-end report build from synthetic checkpoints. No network."""
import csv
from datetime import date, timedelta

import numpy as np
import pytest

from merra_modis_comparison.report import build_report
from tests.test_summarize import write_year


@pytest.fixture
def built(tmp_path):
    cp = tmp_path / "cp"
    cp.mkdir()
    res = tmp_path / "res"
    rng = np.random.default_rng(0)
    years = list(range(2016, 2027))
    for wy in years:
        level = 20.0 if wy == 2026 else (140.0 if wy == 2023 else float(rng.uniform(60, 110)))
        profile = list(np.linspace(0, level, 180)) + list(np.linspace(level, 0, 185))
        write_year(cp, "era5", wy, profile)
        write_year(cp, "merra2", wy, [v / 3.1 for v in profile])
    return build_report(cp, res, years), res, years


class TestTable:
    def test_writes_one_row_per_model_year(self, built):
        _, res, years = built
        with (res / "water_year_statistics.csv").open() as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 2 * len(years)

    def test_both_models_are_present(self, built):
        _, res, _ = built
        with (res / "water_year_statistics.csv").open() as handle:
            models = {r["model"] for r in csv.DictReader(handle)}
        assert models == {"era5", "merra2"}

    def test_ranks_are_recorded(self, built):
        _, res, years = built
        with (res / "water_year_statistics.csv").open() as handle:
            rows = [r for r in csv.DictReader(handle) if r["model"] == "era5"]
        ranks = sorted(int(r["april_first_swe_rank"]) for r in rows)
        assert ranks == list(range(1, len(years) + 1))

    def test_the_planted_low_year_ranks_lowest(self, built):
        _, res, _ = built
        with (res / "water_year_statistics.csv").open() as handle:
            rows = {(r["model"], r["water_year"]): r for r in csv.DictReader(handle)}
        assert rows[("era5", "2026")]["april_first_swe_rank"] == "1"

    def test_the_planted_high_year_ranks_highest(self, built):
        summary, res, years = built
        with (res / "water_year_statistics.csv").open() as handle:
            rows = {(r["model"], r["water_year"]): r for r in csv.DictReader(handle)}
        assert rows[("era5", "2023")]["april_first_swe_rank"] == str(len(years))


class TestFigures:
    def test_every_figure_is_written(self, built):
        summary, _, _ = built
        assert len(summary["figures"]) == 4
        for path in summary["figures"]:
            from pathlib import Path

            assert Path(path).exists()
            assert Path(path).stat().st_size > 5000

    def test_no_temporary_files_survive(self, built):
        _, res, _ = built
        assert not list(res.glob("*.tmp*"))


class TestAgreement:
    def test_rank_agreement_is_reported(self, built):
        summary, _, years = built
        assert summary["agreement_peak_swe"]["n"] == len(years)
        assert summary["agreement_peak_swe"]["rho"] == pytest.approx(1.0)


class TestPartialYears:
    def test_a_part_built_year_is_excluded_by_default(self, tmp_path):
        cp = tmp_path / "cp"
        cp.mkdir()
        write_year(cp, "era5", 2025, [50.0] * 365)
        write_year(cp, "era5", 2026, [5.0] * 30)  # only 30 days fetched so far
        summary = build_report(cp, tmp_path / "res", [2025, 2026])
        assert summary["water_years"] == [2025]

    def test_it_can_be_included_explicitly(self, tmp_path):
        cp = tmp_path / "cp"
        cp.mkdir()
        write_year(cp, "era5", 2025, [50.0] * 365)
        write_year(cp, "era5", 2026, [5.0] * 30)
        summary = build_report(
            cp, tmp_path / "res", [2025, 2026], complete_only=False
        )
        assert summary["water_years"] == [2025, 2026]


class TestFetchOrder:
    """A partial run must still answer the question it was started for."""

    def test_feature_years_come_first(self):
        from merra_modis_comparison.run_analysis import fetch_order

        order = fetch_order(1981, 2026)
        assert order[:2] == [2026, 2023]

    def test_the_rest_run_most_recent_first(self):
        from merra_modis_comparison.run_analysis import fetch_order

        order = fetch_order(1981, 2026)
        assert order[2] == 2025
        assert order[-1] == 1981

    def test_every_year_appears_exactly_once(self):
        from merra_modis_comparison.run_analysis import fetch_order

        order = fetch_order(1981, 2026)
        assert sorted(order) == list(range(1981, 2027))
        assert len(set(order)) == len(order)

    def test_a_range_excluding_a_feature_year_still_works(self):
        from merra_modis_comparison.run_analysis import fetch_order

        order = fetch_order(1990, 2000)
        assert sorted(order) == list(range(1990, 2001))
