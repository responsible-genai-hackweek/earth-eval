import json
import math
import os

import pytest

from fsca_eval import checkpoint, config, metrics


def _stats(sum_w=10.0, sum_w_error=2.0, sum_w_abs_error=3.0, sum_w_r=5.0, valid=10, expected=10, observed=8, n=1):
    return metrics.SufficientStats(
        sum_w=sum_w, sum_w_error=sum_w_error, sum_w_abs_error=sum_w_abs_error, sum_w_r=sum_w_r,
        valid_pixels=valid, expected_pixels=expected, observed_pixels=observed,
        n_cell_days=n, n_days=n, n_calendar_days=n,
    )


def _all_cell_stats(n_calendar_days=1):
    return [_stats(n=n_calendar_days) for _ in range(config.N_CELLS)]


def test_build_month_checkpoint_rows_shape_and_domain_row():
    rows, metadata = checkpoint.build_month_checkpoint_rows(2010, 2009, 10, _all_cell_stats())
    assert len(rows) == config.ROWS_PER_MONTH == 73
    for i, row in enumerate(rows[:-1]):
        assert row["cell_id"] == i
    assert rows[-1]["cell_id"] == checkpoint.DOMAIN_CELL_ID
    assert rows[-1]["sum_w"] == pytest.approx(10.0 * config.N_CELLS)
    assert metadata["water_year"] == 2010
    assert metadata["calendar_year"] == 2009
    assert metadata["calendar_month"] == 10


def test_build_month_checkpoint_rows_wrong_length_raises():
    with pytest.raises(ValueError):
        checkpoint.build_month_checkpoint_rows(2010, 2009, 10, [_stats()])


def test_write_and_read_checkpoint_round_trip(tmp_path):
    rows, metadata = checkpoint.build_month_checkpoint_rows(2010, 2009, 10, _all_cell_stats(n_calendar_days=31))
    path = str(tmp_path / "2009-10.csv")
    checkpoint.write_checkpoint(path, rows, metadata)

    read_metadata, read_rows = checkpoint.read_checkpoint(path)
    assert read_metadata == metadata
    assert len(read_rows) == 73
    assert read_rows[0]["cell_id"] == 0
    assert read_rows[0]["sum_w"] == pytest.approx(10.0)


def test_write_checkpoint_atomic_no_partial_file_left_on_crash(tmp_path, monkeypatch):
    rows, metadata = checkpoint.build_month_checkpoint_rows(2010, 2009, 10, _all_cell_stats())
    path = str(tmp_path / "2009-10.csv")

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated crash before rename")

    monkeypatch.setattr(os, "fsync", _boom)
    with pytest.raises(RuntimeError):
        checkpoint.write_checkpoint(path, rows, metadata)

    assert not os.path.exists(path)
    leftover = [f for f in os.listdir(tmp_path) if f.startswith(".tmp-checkpoint-")]
    assert leftover == []


def test_validate_checkpoint_passes_for_freshly_built_checkpoint(tmp_path):
    rows, metadata = checkpoint.build_month_checkpoint_rows(2010, 2009, 10, _all_cell_stats(n_calendar_days=31))
    path = str(tmp_path / "ck.csv")
    checkpoint.write_checkpoint(path, rows, metadata)

    result = checkpoint.validate_checkpoint(path, expected_water_year=2010, expected_year=2009, expected_month=10)
    assert result.ok, result.errors


def test_validate_checkpoint_expected_field_mismatch_fails(tmp_path):
    rows, metadata = checkpoint.build_month_checkpoint_rows(2010, 2009, 10, _all_cell_stats(n_calendar_days=31))
    path = str(tmp_path / "ck.csv")
    checkpoint.write_checkpoint(path, rows, metadata)

    result = checkpoint.validate_checkpoint(path, expected_water_year=2011, expected_year=2009, expected_month=10)
    assert not result.ok
    assert any("water_year mismatch" in e for e in result.errors)


def test_validate_checkpoint_detects_config_fingerprint_mutation(tmp_path, monkeypatch):
    rows, metadata = checkpoint.build_month_checkpoint_rows(2010, 2009, 10, _all_cell_stats(n_calendar_days=31))
    path = str(tmp_path / "ck.csv")
    checkpoint.write_checkpoint(path, rows, metadata)

    monkeypatch.setattr(config, "SUPPORT_THRESHOLD", 0.5)
    result = checkpoint.validate_checkpoint(path)
    assert not result.ok
    assert any("config_fingerprint mismatch" in e for e in result.errors)


def test_validate_checkpoint_detects_row_count_mismatch(tmp_path):
    rows, metadata = checkpoint.build_month_checkpoint_rows(2010, 2009, 10, _all_cell_stats(n_calendar_days=31))
    path = str(tmp_path / "ck.csv")
    checkpoint.write_checkpoint(path, rows[:-1], metadata)  # drop domain row

    result = checkpoint.validate_checkpoint(path)
    assert not result.ok
    assert any("row count mismatch" in e for e in result.errors)


def test_validate_checkpoint_detects_out_of_order_cells(tmp_path):
    rows, metadata = checkpoint.build_month_checkpoint_rows(2010, 2009, 10, _all_cell_stats(n_calendar_days=31))
    rows[0], rows[1] = rows[1], rows[0]
    path = str(tmp_path / "ck.csv")
    checkpoint.write_checkpoint(path, rows, metadata)

    result = checkpoint.validate_checkpoint(path)
    assert not result.ok
    assert any("out of stable order" in e for e in result.errors)


def test_validate_checkpoint_detects_tampered_derived_column(tmp_path):
    rows, metadata = checkpoint.build_month_checkpoint_rows(2010, 2009, 10, _all_cell_stats(n_calendar_days=31))
    rows[0]["bias_pp"] = rows[0]["bias_pp"] + 1000.0
    path = str(tmp_path / "ck.csv")
    checkpoint.write_checkpoint(path, rows, metadata)

    result = checkpoint.validate_checkpoint(path)
    assert not result.ok
    assert any("stored bias_pp" in e for e in result.errors)


def test_validate_checkpoint_detects_domain_row_mismatch(tmp_path):
    rows, metadata = checkpoint.build_month_checkpoint_rows(2010, 2009, 10, _all_cell_stats(n_calendar_days=31))
    rows[-1]["sum_w"] = rows[-1]["sum_w"] + 1.0
    path = str(tmp_path / "ck.csv")
    checkpoint.write_checkpoint(path, rows, metadata)

    result = checkpoint.validate_checkpoint(path)
    assert not result.ok
    assert any("domain row: sum_w" in e for e in result.errors)


def test_validate_checkpoint_zero_pair_cell_gets_nan_row_with_no_error():
    stats = [metrics.SufficientStats() for _ in range(config.N_CELLS)]
    rows, metadata = checkpoint.build_month_checkpoint_rows(2010, 2009, 10, stats)
    assert math.isnan(rows[0]["bias_pp"])
    assert math.isnan(rows[0]["mae_pp"])
    assert rows[0]["sum_w"] == 0
    assert rows[0]["valid_pixels"] == 0


def test_validate_checkpoint_missing_file_reports_unreadable(tmp_path):
    result = checkpoint.validate_checkpoint(str(tmp_path / "does-not-exist.csv"))
    assert not result.ok
    assert any("unreadable" in e for e in result.errors)
