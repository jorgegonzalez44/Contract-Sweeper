"""Tests for scripts/analyze_entity_profiles.py — normalize, safe_load, entity_master join."""

import csv
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_entity_profiles import _normalize, _safe_load, build_profiles


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_empty_returns_empty(self):
        assert _normalize("") == ""

    def test_nan_returns_empty(self):
        assert _normalize(float("nan")) == ""

    def test_none_returns_empty(self):
        assert _normalize(None) == ""

    def test_uppercases(self):
        assert _normalize("crowley") == "CROWLEY"

    def test_strips_trailing_inc(self):
        assert _normalize("Microsoft Inc") == "MICROSOFT"

    def test_strips_trailing_corp(self):
        assert _normalize("Acme Corp") == "ACME"

    def test_strips_punctuation(self):
        assert _normalize("Triple-S, Inc.") == "TRIPLE S"

    def test_strips_hospital_suffix(self):
        # HOSPITAL is in _SUFFIXES (added for cross-ref matching)
        assert _normalize("Centro Medico Hospital") == "CENTRO MEDICO"

    def test_strips_health_suffix(self):
        assert _normalize("Puerto Rico Health") == "PUERTO RICO"

    def test_collapses_whitespace(self):
        assert _normalize("  foo   bar  ") == "FOO BAR"


# ---------------------------------------------------------------------------
# _safe_load
# ---------------------------------------------------------------------------

class TestSafeLoad:
    def test_returns_none_for_missing_file(self, tmp_path, caplog):
        import logging
        logger = logging.getLogger("test")
        result = _safe_load(tmp_path / "nonexistent.csv", logger)
        assert result is None

    def test_loads_csv_when_present(self, tmp_path):
        import logging
        p = tmp_path / "data.csv"
        p.write_text("name,value\nFoo,1\nBar,2\n")
        logger = logging.getLogger("test")
        df = _safe_load(p, logger)
        assert df is not None
        assert len(df) == 2
        assert list(df.columns) == ["name", "value"]


# ---------------------------------------------------------------------------
# entity_master join — integration via run()
# ---------------------------------------------------------------------------

def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


class TestEntityMasterJoin:
    def _setup_root(self, tmp_path: Path) -> Path:
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        (tmp_path / "data" / "logs").mkdir(parents=True)
        return processed

    def test_entity_type_column_present_in_output(self, tmp_path):
        """entity_type column appears in pr_entity_profiles.csv when entity_master exists."""
        run = build_profiles

        processed = self._setup_root(tmp_path)

        # Minimal awards master
        _write_csv(
            processed / "pr_all_awards_master.csv",
            [{"award_id": "A1", "recipient_name": "Hospital Damas Inc",
              "obligated_amount": "1000000", "source_dataset": "contracts",
              "award_date": "2020-01-01", "fiscal_year": "2020",
              "recipient_uei": "", "awarding_agency": "HHS", "awarding_sub_agency": "",
              "pop_state": "PR", "pop_county": "", "description": "",
              "source_file": "test.csv", "award_category": "grant",
              "recipient_name_normalized": "HOSPITAL DAMAS"}],
            ["award_id", "recipient_name", "obligated_amount", "source_dataset",
             "award_date", "fiscal_year", "recipient_uei", "awarding_agency",
             "awarding_sub_agency", "pop_state", "pop_county", "description",
             "source_file", "award_category", "recipient_name_normalized"],
        )

        # entity_master with entity_type
        _write_csv(
            processed / "entity_master.csv",
            [{"entity_key": "HOSPITAL DAMAS", "entity_type": "nonprofit",
              "canonical_name": "Hospital Damas Inc", "recipient_uei": "HDMC7P3K9L2N",
              "total_obligated": "1000000", "award_count": "1",
              "source_datasets": "contracts", "awarding_agencies": "HHS",
              "first_award_date": "2020-01-01", "last_award_date": "2020-01-01",
              "fiscal_year_range": "2020"}],
            ["entity_key", "entity_type", "canonical_name", "recipient_uei",
             "total_obligated", "award_count", "source_datasets", "awarding_agencies",
             "first_award_date", "last_award_date", "fiscal_year_range"],
        )

        run(root=tmp_path)

        profiles = pd.read_csv(processed / "pr_entity_profiles.csv", dtype=str)
        assert "entity_type" in profiles.columns

    def test_entity_type_value_from_entity_master(self, tmp_path):
        """entity_type value is correctly joined from entity_master."""
        run = build_profiles

        processed = self._setup_root(tmp_path)

        _write_csv(
            processed / "pr_all_awards_master.csv",
            [{"award_id": "A1", "recipient_name": "Municipality of San Juan",
              "obligated_amount": "500000", "source_dataset": "grants",
              "award_date": "2021-06-01", "fiscal_year": "2021",
              "recipient_uei": "", "awarding_agency": "FEMA", "awarding_sub_agency": "",
              "pop_state": "PR", "pop_county": "", "description": "",
              "source_file": "test.csv", "award_category": "grant",
              "recipient_name_normalized": "MUNICIPALITY SAN JUAN"}],
            ["award_id", "recipient_name", "obligated_amount", "source_dataset",
             "award_date", "fiscal_year", "recipient_uei", "awarding_agency",
             "awarding_sub_agency", "pop_state", "pop_county", "description",
             "source_file", "award_category", "recipient_name_normalized"],
        )

        _write_csv(
            processed / "entity_master.csv",
            # entity_key must match _normalize("Municipality of San Juan") = "MUNICIPALITY OF SAN JUAN"
            # ("OF" is in _SUFFIXES but is not the trailing token, so it is preserved)
            [{"entity_key": "MUNICIPALITY OF SAN JUAN", "entity_type": "government",
              "canonical_name": "Municipality of San Juan", "recipient_uei": "",
              "total_obligated": "500000", "award_count": "1",
              "source_datasets": "grants", "awarding_agencies": "FEMA",
              "first_award_date": "2021-06-01", "last_award_date": "2021-06-01",
              "fiscal_year_range": "2021"}],
            ["entity_key", "entity_type", "canonical_name", "recipient_uei",
             "total_obligated", "award_count", "source_datasets", "awarding_agencies",
             "first_award_date", "last_award_date", "fiscal_year_range"],
        )

        run(root=tmp_path)

        profiles = pd.read_csv(processed / "pr_entity_profiles.csv", dtype=str)
        row = profiles[profiles["recipient_name"] == "Municipality of San Juan"].iloc[0]
        assert row["entity_type"] == "government"

    def test_entity_type_defaults_to_unknown_without_entity_master(self, tmp_path):
        """When entity_master.csv is absent, entity_type defaults to 'unknown'."""
        run = build_profiles

        processed = self._setup_root(tmp_path)

        _write_csv(
            processed / "pr_all_awards_master.csv",
            [{"award_id": "A1", "recipient_name": "Acme Corp",
              "obligated_amount": "100000", "source_dataset": "contracts",
              "award_date": "2022-01-01", "fiscal_year": "2022",
              "recipient_uei": "", "awarding_agency": "DoD", "awarding_sub_agency": "",
              "pop_state": "PR", "pop_county": "", "description": "",
              "source_file": "test.csv", "award_category": "contract",
              "recipient_name_normalized": "ACME"}],
            ["award_id", "recipient_name", "obligated_amount", "source_dataset",
             "award_date", "fiscal_year", "recipient_uei", "awarding_agency",
             "awarding_sub_agency", "pop_state", "pop_county", "description",
             "source_file", "award_category", "recipient_name_normalized"],
        )

        # No entity_master.csv written

        run(root=tmp_path)

        profiles = pd.read_csv(processed / "pr_entity_profiles.csv", dtype=str)
        assert "entity_type" in profiles.columns
        assert profiles["entity_type"].iloc[0] == "unknown"
