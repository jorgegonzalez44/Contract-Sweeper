"""Tests for scripts/link_hud_drgr_to_assets.py.

Covers:
- _clean_muni     – accent stripping, whitespace normalisation
- _match_municipality – exact/partial/no match
- _classify_asset_type – keyword routing
- run()           – missing inputs → empty CSV, with fixtures → populated CSV
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.link_hud_drgr_to_assets import (
    _clean_muni,
    _match_municipality,
    _classify_asset_type,
    ASSET_LINKAGE_COLUMNS,
    run,
)
from scripts.parquet_utils import pq_write


# ---------------------------------------------------------------------------
# _clean_muni
# ---------------------------------------------------------------------------

class TestCleanMuni:
    def test_empty_string(self):
        assert _clean_muni("") == ""

    def test_none(self):
        assert _clean_muni(None) == ""

    def test_nan(self):
        assert _clean_muni(float("nan")) == ""

    def test_uppercase(self):
        assert _clean_muni("san juan") == "SAN JUAN"

    def test_accent_stripping(self):
        # á → a, é → e, etc.
        assert _clean_muni("Mayagüez") == "MAYAGUEZ"

    def test_extra_whitespace_collapsed(self):
        assert _clean_muni("  SAN   JUAN  ") == "SAN JUAN"

    def test_mixed_accents_and_case(self):
        assert _clean_muni("añasco") == "ANASCO"


# ---------------------------------------------------------------------------
# _match_municipality
# ---------------------------------------------------------------------------

class TestMatchMunicipality:
    def test_exact_match(self):
        assert _match_municipality("SAN JUAN") == "SAN JUAN"

    def test_case_insensitive(self):
        assert _match_municipality("ponce") == "PONCE"

    def test_accent_then_match(self):
        # Mayagüez → MAYAGUEZ which is in the set
        assert _match_municipality("Mayagüez") == "MAYAGUEZ"

    def test_partial_match_contained(self):
        # "CAGUAS MUNICIPALITY" should still resolve to CAGUAS
        result = _match_municipality("CAGUAS MUNICIPALITY")
        assert result == "CAGUAS"

    def test_no_match_returns_empty(self):
        assert _match_municipality("WASHINGTON DC") == ""

    def test_none_returns_empty(self):
        # None/NaN input should not raise and should produce a non-error result
        result = _match_municipality(None)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _classify_asset_type
# ---------------------------------------------------------------------------

class TestClassifyAssetType:
    def test_housing_keyword(self):
        assert _classify_asset_type("Homeowner Assistance", "") == "housing"

    def test_infrastructure_keyword(self):
        assert _classify_asset_type("Road Repair Project", "") == "infrastructure"

    def test_economic_keyword(self):
        assert _classify_asset_type("Business Recovery Grant", "") == "economic"

    def test_planning_keyword(self):
        assert _classify_asset_type("Environmental Assessment", "") == "planning"

    def test_activity_type_used_when_name_empty(self):
        assert _classify_asset_type("", "water grid utility") == "infrastructure"

    def test_unknown_falls_back_to_other(self):
        assert _classify_asset_type("General Support Services", "misc") == "other"

    def test_case_insensitive_match(self):
        assert _classify_asset_type("RENTAL HOUSING REHABILITATION", "") == "housing"


# ---------------------------------------------------------------------------
# run() – missing inputs → graceful empty CSV, no exception
# ---------------------------------------------------------------------------

class TestRunMissingInputs:
    def test_missing_activities_writes_empty_csv(self, tmp_path):
        """When hud_drgr_activities.parquet is absent the run returns EMPTY status
        and creates an empty CSV with the expected columns."""
        result = run(root=tmp_path)
        assert result["status"] == "EMPTY"
        assert result["linkage_rows"] == 0

        out = tmp_path / "data" / "linked" / "hud_drgr_asset_linkage.csv"
        assert out.exists(), "Output CSV should be created even when no activities exist"

        df = pd.read_csv(out, dtype=str)
        assert list(df.columns) == ASSET_LINKAGE_COLUMNS
        assert len(df) == 0

    def test_missing_supplementary_files_still_runs(self, tmp_path):
        """Activities present but no COR3/municipal CSVs — should still produce output."""
        norm_dir = tmp_path / "data" / "normalized"
        norm_dir.mkdir(parents=True)
        df_act = pd.DataFrame([{
            "activity_id": "A001",
            "grant_number": "B-16-DL-72-0002",
            "activity_name": "Housing Repair",
            "activity_type": "housing",
            "municipality": "PONCE",
            "county": "",
            "total_budget": "100000",
            "amount_drawn": "50000",
        }])
        pq_write(df_act, norm_dir / "hud_drgr_activities.parquet")

        result = run(root=tmp_path, force=True)
        assert result["status"] == "OK"
        assert result["linkage_rows"] == 1
        assert result["municipalities_matched"] >= 1


# ---------------------------------------------------------------------------
# run() – with full fixture data → correct join / output
# ---------------------------------------------------------------------------

class TestRunWithFixtures:
    def _write_activities(self, norm_dir, rows):
        df = pd.DataFrame(rows)
        pq_write(df, norm_dir / "hud_drgr_activities.parquet")

    def _write_municipal(self, proc_dir, rows):
        proc_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(proc_dir / "pr_municipal_finance.csv", index=False)

    def _write_cor3(self, proc_dir, rows):
        proc_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_csv(proc_dir / "pr_cor3_projects.csv", index=False)

    def test_output_has_expected_columns(self, tmp_path):
        norm_dir = tmp_path / "data" / "normalized"
        norm_dir.mkdir(parents=True)
        self._write_activities(norm_dir, [{
            "activity_id": "A001", "grant_number": "GR1",
            "activity_name": "Road Repair", "activity_type": "infrastructure",
            "municipality": "BAYAMON", "county": "BAYAMON",
            "total_budget": "200000", "amount_drawn": "100000",
        }])
        run(root=tmp_path, force=True)
        df = pd.read_csv(tmp_path / "data" / "linked" / "hud_drgr_asset_linkage.csv", dtype=str)
        assert list(df.columns) == ASSET_LINKAGE_COLUMNS

    def test_municipality_matched_field_correct(self, tmp_path):
        norm_dir = tmp_path / "data" / "normalized"
        norm_dir.mkdir(parents=True)
        self._write_activities(norm_dir, [{
            "activity_id": "A002", "grant_number": "GR2",
            "activity_name": "Water System", "activity_type": "infrastructure",
            "municipality": "arecibo", "county": "",
            "total_budget": "50000", "amount_drawn": "25000",
        }])
        run(root=tmp_path, force=True)
        df = pd.read_csv(tmp_path / "data" / "linked" / "hud_drgr_asset_linkage.csv", dtype=str)
        assert df.iloc[0]["municipality_matched"] == "ARECIBO"

    def test_asset_type_classified(self, tmp_path):
        norm_dir = tmp_path / "data" / "normalized"
        norm_dir.mkdir(parents=True)
        self._write_activities(norm_dir, [{
            "activity_id": "A003", "grant_number": "GR3",
            "activity_name": "Homeowner Assistance Program", "activity_type": "",
            "municipality": "SAN JUAN", "county": "",
            "total_budget": "300000", "amount_drawn": "150000",
        }])
        run(root=tmp_path, force=True)
        df = pd.read_csv(tmp_path / "data" / "linked" / "hud_drgr_asset_linkage.csv", dtype=str)
        assert df.iloc[0]["asset_type"] == "housing"

    def test_cor3_lookup_joined(self, tmp_path):
        norm_dir = tmp_path / "data" / "normalized"
        proc_dir = tmp_path / "data" / "staging" / "processed"
        norm_dir.mkdir(parents=True)
        self._write_activities(norm_dir, [{
            "activity_id": "A004", "grant_number": "GR4",
            "activity_name": "Bridge Repair", "activity_type": "infrastructure",
            "municipality": "CAGUAS", "county": "",
            "total_budget": "500000", "amount_drawn": "250000",
        }])
        self._write_cor3(proc_dir, [{
            "municipality": "CAGUAS",
            "project_id": "COR3-001",
            "total_approved": "9999999",
        }])
        run(root=tmp_path, force=True)
        df = pd.read_csv(tmp_path / "data" / "linked" / "hud_drgr_asset_linkage.csv", dtype=str)
        assert df.iloc[0]["cor3_project_id"] == "COR3-001"
        assert df.iloc[0]["cor3_total_approved"] == "9999999"

    def test_municipal_finance_grade_joined(self, tmp_path):
        norm_dir = tmp_path / "data" / "normalized"
        proc_dir = tmp_path / "data" / "staging" / "processed"
        norm_dir.mkdir(parents=True)
        self._write_activities(norm_dir, [{
            "activity_id": "A005", "grant_number": "GR5",
            "activity_name": "Economic Zone", "activity_type": "economic",
            "municipality": "PONCE", "county": "",
            "total_budget": "100000", "amount_drawn": "80000",
        }])
        self._write_municipal(proc_dir, [{
            "municipality": "PONCE",
            "abre_grade": "B+",
        }])
        run(root=tmp_path, force=True)
        df = pd.read_csv(tmp_path / "data" / "linked" / "hud_drgr_asset_linkage.csv", dtype=str)
        assert df.iloc[0]["municipal_finance_grade"] == "B+"

    def test_unmatched_municipality_leaves_empty_fields(self, tmp_path):
        norm_dir = tmp_path / "data" / "normalized"
        norm_dir.mkdir(parents=True)
        self._write_activities(norm_dir, [{
            "activity_id": "A006", "grant_number": "GR6",
            "activity_name": "Generic Project", "activity_type": "",
            "municipality": "UNKNOWN PLACE XYZ", "county": "",
            "total_budget": "10000", "amount_drawn": "5000",
        }])
        run(root=tmp_path, force=True)
        df = pd.read_csv(tmp_path / "data" / "linked" / "hud_drgr_asset_linkage.csv", dtype=str).fillna("")
        assert df.iloc[0]["municipality_matched"] == ""
        assert df.iloc[0]["cor3_project_id"] == ""

    def test_multiple_activities_all_written(self, tmp_path):
        norm_dir = tmp_path / "data" / "normalized"
        norm_dir.mkdir(parents=True)
        activities = [
            {"activity_id": f"A{i:03d}", "grant_number": "GR7",
             "activity_name": f"Project {i}", "activity_type": "planning",
             "municipality": muni, "county": "",
             "total_budget": "1000", "amount_drawn": "500"}
            for i, muni in enumerate(["BAYAMON", "CAGUAS", "CAROLINA", "GUAYNABO", "LOIZA"])
        ]
        self._write_activities(norm_dir, activities)
        result = run(root=tmp_path, force=True)
        assert result["linkage_rows"] == 5
        df = pd.read_csv(tmp_path / "data" / "linked" / "hud_drgr_asset_linkage.csv", dtype=str)
        assert len(df) == 5

    def test_cached_result_when_not_force(self, tmp_path):
        """Second call without force=True should return CACHED status."""
        norm_dir = tmp_path / "data" / "normalized"
        norm_dir.mkdir(parents=True)
        self._write_activities(norm_dir, [{
            "activity_id": "A007", "grant_number": "GR8",
            "activity_name": "Rental Housing", "activity_type": "housing",
            "municipality": "MAYAGUEZ", "county": "",
            "total_budget": "200000", "amount_drawn": "100000",
        }])
        run(root=tmp_path, force=True)
        result2 = run(root=tmp_path, force=False)
        assert result2["status"] == "CACHED"
