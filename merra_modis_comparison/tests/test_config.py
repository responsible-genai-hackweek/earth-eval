"""The frozen scientific configuration and its fingerprint.

Protects: contract defaults, immutability, and the rule that the fingerprint
tracks scientific choices but not operational ones.
"""
from datetime import date

import pytest

from merra_modis_comparison.config import (
    ComparisonConfig,
    OperationalConfig,
    ReferenceEra,
    default_config,
)


@pytest.fixture(scope="module")
def cfg() -> ComparisonConfig:
    return default_config()


class TestContractDefaults:
    def test_model_is_merra2_land_frsno_at_index_15(self, cfg):
        assert cfg.model_collection == "M2T1NXLND"
        assert cfg.model_version == "5.12.4"
        assert cfg.model_variable == "FRSNO"
        assert cfg.model_time_index == 15

    def test_error_sign_is_model_minus_reference(self, cfg):
        assert cfg.error_sign == "model_minus_reference"

    def test_support_threshold_is_80_percent(self, cfg):
        assert cfg.support_threshold == 0.8

    def test_low_snow_masks_match_the_contract(self, cfg):
        assert cfg.composite_min_reference_fsca == 0.05
        assert cfg.significance_min_reference_fsca == 0.10

    def test_domain_is_the_72_cell_colorado_block(self, cfg):
        assert (cfg.lon_min, cfg.lon_max) == (-109.0, -104.0)
        assert (cfg.lat_min, cfg.lat_max) == (37.0, 41.0)

    def test_reference_is_scaled_from_percent_to_fraction(self, cfg):
        assert cfg.reference_variable == "snow_fraction"
        assert cfg.reference_scale == 100.0

    def test_reference_values_above_full_cover_are_fill(self, cfg):
        assert cfg.reference_valid_max == 100.0


class TestScope:
    def test_validation_year_is_wy2023(self, cfg):
        """WY2023 lies entirely inside the clean historical MODSCAG record."""
        assert cfg.water_years == (2023,)

    def test_full_water_year(self, cfg):
        assert cfg.months == (10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9)

    def test_three_modis_tiles(self, cfg):
        assert cfg.tiles == ("h09v04", "h09v05", "h10v04")


class TestReferenceEras:
    def test_eras_are_contiguous_and_ordered(self, cfg):
        eras = cfg.reference_eras
        assert len(eras) >= 1
        for earlier, later in zip(eras, eras[1:]):
            assert earlier.end is not None
            assert later.start == date.fromordinal(earlier.end.toordinal() + 1)

    def test_resolves_a_date_to_its_era(self, cfg):
        era = cfg.resolve_era(date(2023, 3, 15))
        assert era.product == "STC_MODSCGDRF_HIST"

    def test_the_whole_validation_year_is_inside_one_era(self, cfg):
        assert cfg.resolve_era(date(2022, 10, 1)).product == "STC_MODSCGDRF_HIST"
        assert cfg.resolve_era(date(2023, 9, 30)).product == "STC_MODSCGDRF_HIST"

    def test_a_date_past_the_historical_record_is_rejected(self, cfg):
        """The record ends 2023-09-30; asking for later must fail loudly."""
        with pytest.raises(ValueError, match="no reference era"):
            cfg.resolve_era(date(2025, 10, 1))

    def test_a_date_before_any_era_is_rejected(self, cfg):
        with pytest.raises(ValueError, match="no reference era"):
            cfg.resolve_era(date(1999, 1, 1))

    def test_the_validation_year_uses_exactly_one_product(self, cfg):
        assert cfg.eras_used_by_water_year(2023) == ("STC_MODSCGDRF_HIST",)

    def test_a_single_year_scope_cannot_be_product_confounded(self, cfg):
        assert cfg.year_contrast_is_product_confounded is False

    def test_a_two_era_two_year_scope_is_flagged_as_confounded(self):
        """The rejected SPIReS splice, kept as a regression guard."""
        confounded = default_config(
            water_years=(2025, 2026),
            months=(11, 12, 1, 2, 3, 4, 5),
            reference_eras=(
                ReferenceEra("SPIRES_HIST", "1", date(2000, 3, 1), date(2025, 9, 30)),
                ReferenceEra("SPIRES_NRT", "2", date(2025, 10, 1), None),
            ),
        )
        assert confounded.year_contrast_is_product_confounded is True


class TestImmutability:
    def test_config_is_frozen(self, cfg):
        with pytest.raises(Exception):
            cfg.support_threshold = 0.5

    def test_collections_are_hashable_tuples(self, cfg):
        hash(cfg.water_years)
        hash(cfg.months)
        hash(cfg.tiles)


class TestFingerprint:
    def test_is_a_sha256_hex_digest(self, cfg):
        assert len(cfg.fingerprint()) == 64
        int(cfg.fingerprint(), 16)

    def test_is_deterministic(self, cfg):
        assert cfg.fingerprint() == default_config().fingerprint()

    @pytest.mark.parametrize(
        "field,value",
        [
            ("support_threshold", 0.75),
            ("model_time_index", 12),
            ("error_sign", "reference_minus_model"),
            ("water_years", (2022,)),
            ("months", (12, 1, 2)),
            ("composite_min_reference_fsca", 0.10),
            ("lon_min", -108.0),
            ("reference_variable", "viewable_snow_fraction"),
        ],
    )
    def test_any_scientific_change_changes_the_fingerprint(self, cfg, field, value):
        import dataclasses

        changed = dataclasses.replace(cfg, **{field: value})
        assert changed.fingerprint() != cfg.fingerprint()

    def test_changing_the_reference_era_changes_the_fingerprint(self, cfg):
        import dataclasses

        other = dataclasses.replace(
            cfg,
            reference_eras=(
                ReferenceEra(product="MODSCGDRF_NRT", version="1.1",
                             start=date(2023, 11, 1), end=None),
            ),
        )
        assert other.fingerprint() != cfg.fingerprint()

    def test_operational_settings_are_not_in_the_fingerprint(self, cfg):
        fast = OperationalConfig(workers=16, ftp_slots=8)
        slow = OperationalConfig(workers=2, ftp_slots=1, max_runtime_minutes=30)
        assert fast != slow
        assert cfg.fingerprint() == cfg.fingerprint()
        # the operational object is not reachable from the scientific config
        assert not hasattr(cfg, "workers")


class TestValidation:
    def test_rejects_a_support_threshold_outside_zero_to_one(self):
        with pytest.raises(ValueError, match="support_threshold"):
            default_config(support_threshold=1.5)

    def test_rejects_an_out_of_range_month(self):
        with pytest.raises(ValueError, match="month"):
            default_config(months=(13,))

    def test_rejects_an_empty_tile_set(self):
        with pytest.raises(ValueError, match="tile"):
            default_config(tiles=())

    def test_rejects_a_negative_time_index(self):
        with pytest.raises(ValueError, match="model_time_index"):
            default_config(model_time_index=-1)


class TestOperationalDefaults:
    def test_matches_the_plan(self):
        op = OperationalConfig()
        assert op.workers == 16
        assert op.ftp_slots == 8

    def test_ftp_slots_may_not_exceed_the_archive_cap(self):
        with pytest.raises(ValueError, match="ftp_slots"):
            OperationalConfig(ftp_slots=10)

    def test_backoff_is_the_staggered_sequence_from_the_plan(self):
        assert OperationalConfig().ftp_backoff_seconds == (5, 10, 20)
