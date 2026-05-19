"""Tests for scripts/link_fema_pa_to_contracts.py

Covers:
- Pure helper: _norm
- Core matching logic: _build_linkage (in-memory DataFrames)
- Integration via run(root=tmp_path):
    * missing v2 parquet → empty linkage CSV with correct columns
    * with fixture data → fema_178_pw_linkage.csv written with rows
    * caching behavior (CACHED / force overwrite)
    * unmatched portal PWs written to review dir
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.link_fema_pa_to_contracts import (
    _norm,
    _build_linkage,
    LINKAGE_COLUMNS,
    UNMATCHED_COLUMNS,
    run,
)
from scripts.parquet_utils import pq_write
from scripts import config as _cfg  # noqa: imported to access logger side-effects


# ---------------------------------------------------------------------------
# Helpers to create fixture directories under tmp_path
# ---------------------------------------------------------------------------

def _normalized_dir(root: Path) -> Path:
    d = root / "data" / "normalized"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _linked_dir(root: Path) -> Path:
    d = root / "data" / "linked"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _review_dir(root: Path) -> Path:
    d = root / "data" / "review"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _processed_dir(root: Path) -> Path:
    d = root / "data" / "staging" / "processed"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _prep_dirs(root: Path) -> None:
    """Pre-create all directories required by run()."""
    _normalized_dir(root)
    _linked_dir(root)
    _review_dir(root)
    _processed_dir(root)


def _write_v2(root: Path, rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    pq_write(df, _normalized_dir(root) / "fema_pa_projects_v2.parquet")


def _write_portal(root: Path, rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    pq_write(df, _normalized_dir(root) / "fema_pa_portal_178_pws.parquet")


# Minimal fake logger (duck-typed for _build_linkage)
class _FakeLogger:
    def info(self, *a, **kw): pass
    def warning(self, *a, **kw): pass
    def debug(self, *a, **kw): pass


_LOG = _FakeLogger()


# ===========================================================================
# _norm
# ===========================================================================

class TestNorm:
    def test_plain_string_uppercased(self):
        result = _norm("municipality of caguas")
        assert result == result.upper()

    def test_nan_returns_empty(self):
        assert _norm(float("nan")) == ""

    def test_none_returns_empty(self):
        assert _norm(None) == ""

    def test_empty_string_returns_empty(self):
        assert _norm("") == ""

    def test_whitespace_only_returns_empty(self):
        assert _norm("   ") == ""

    def test_strips_suffix(self):
        # _norm delegates to _normalize_name which strips common suffixes
        result = _norm("ACME CORP")
        assert "CORP" not in result


# ===========================================================================
# _build_linkage — in-memory DataFrame tests
# ===========================================================================

class TestBuildLinkage:
    def _empty_df(self):
        return pd.DataFrame()

    def test_empty_v2_returns_empty_linkage(self):
        df = _build_linkage(
            self._empty_df(), self._empty_df(),
            self._empty_df(), self._empty_df(), self._empty_df(),
            _LOG,
        )
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert list(df.columns) == LINKAGE_COLUMNS

    def test_v2_row_produces_linkage_row(self):
        df_v2 = pd.DataFrame([{
            "pw_number": "PW001",
            "disaster_number": "4339",
            "applicant_name": "Municipality of Guaynabo",
            "project_amount": 500_000,
            "federal_share_obligated": 375_000,
            "county": "Guaynabo",
            "category": "A",
        }])
        df = _build_linkage(df_v2, self._empty_df(), self._empty_df(),
                            self._empty_df(), self._empty_df(), _LOG)
        assert len(df) == 1
        assert df.iloc[0]["pw_number"] == "PW001"
        assert df.iloc[0]["disaster_number"] == "4339"

    def test_link_confidence_none_when_no_matches(self):
        df_v2 = pd.DataFrame([{
            "pw_number": "PW002",
            "disaster_number": "4339",
            "applicant_name": "Unmatched Entity",
            "project_amount": 0,
            "federal_share_obligated": 0,
            "county": "",
            "category": "B",
        }])
        df = _build_linkage(df_v2, self._empty_df(), self._empty_df(),
                            self._empty_df(), self._empty_df(), _LOG)
        assert df.iloc[0]["link_confidence"] == "none"
        assert df.iloc[0]["matched_cor3"] == False  # noqa: E712
        assert df.iloc[0]["matched_contract"] == False  # noqa: E712
        assert df.iloc[0]["matched_entity"] == False  # noqa: E712

    def test_link_confidence_partial_when_only_cor3_matches(self):
        applicant = "Municipality of Caguas"
        norm_key = _norm(applicant)

        df_v2 = pd.DataFrame([{
            "pw_number": "PW003",
            "disaster_number": "4339",
            "applicant_name": applicant,
            "project_amount": 1_000_000,
            "federal_share_obligated": 750_000,
            "county": "Caguas",
            "category": "C",
        }])
        df_cor3 = pd.DataFrame([{
            "applicant_normalized": norm_key,
            "project_id": "COR3-001",
            "total_approved": 1_000_000,
            "disbursement_rate": 0.75,
        }])
        df = _build_linkage(df_v2, self._empty_df(), df_cor3,
                            self._empty_df(), self._empty_df(), _LOG)
        assert df.iloc[0]["link_confidence"] == "partial"
        assert df.iloc[0]["matched_cor3"] == True  # noqa: E712
        assert df.iloc[0]["cor3_project_id"] == "COR3-001"

    def test_link_confidence_exact_when_contract_matches(self):
        applicant = "Puerto Rico Aqueduct Authority"
        norm_key = _norm(applicant)

        df_v2 = pd.DataFrame([{
            "pw_number": "PW004",
            "disaster_number": "4339",
            "applicant_name": applicant,
            "project_amount": 2_000_000,
            "federal_share_obligated": 1_500_000,
            "county": "San Juan",
            "category": "D",
        }])
        df_contracts = pd.DataFrame([{
            "recipient_name": applicant,
            "award_id": "AW-9999",
        }])
        df = _build_linkage(df_v2, self._empty_df(), self._empty_df(),
                            df_contracts, self._empty_df(), _LOG)
        assert df.iloc[0]["link_confidence"] == "exact"
        assert df.iloc[0]["matched_contract"] == True  # noqa: E712
        assert df.iloc[0]["contract_id"] == "AW-9999"

    def test_portal_data_merged_by_pw_and_disaster(self):
        df_v2 = pd.DataFrame([{
            "pw_number": "PW005",
            "disaster_number": "4339",
            "applicant_name": "Test Entity",
            "project_amount": 100_000,
            "federal_share_obligated": 75_000,
            "county": "Ponce",
            "category": "E",
        }])
        df_portal = pd.DataFrame([{
            "pw_number": "PW005",
            "disaster_number": "4339",
            "eligible_amount": "120000",
            "federal_share": "90000",
        }])
        df = _build_linkage(df_v2, df_portal, self._empty_df(),
                            self._empty_df(), self._empty_df(), _LOG)
        assert df.iloc[0]["portal_eligible_amount"] == "120000"
        assert df.iloc[0]["portal_federal_share"] == "90000"

    def test_portal_not_merged_when_key_mismatch(self):
        df_v2 = pd.DataFrame([{
            "pw_number": "PW006",
            "disaster_number": "4339",
            "applicant_name": "No Match",
            "project_amount": 0,
            "federal_share_obligated": 0,
            "county": "",
            "category": "",
        }])
        df_portal = pd.DataFrame([{
            "pw_number": "PW999",
            "disaster_number": "9999",
            "eligible_amount": "50000",
            "federal_share": "37500",
        }])
        df = _build_linkage(df_v2, df_portal, self._empty_df(),
                            self._empty_df(), self._empty_df(), _LOG)
        assert df.iloc[0]["portal_eligible_amount"] == ""

    def test_multiple_v2_rows_all_appear_in_output(self):
        df_v2 = pd.DataFrame([
            {"pw_number": "PW010", "disaster_number": "4339", "applicant_name": "Entity A",
             "project_amount": 100_000, "federal_share_obligated": 75_000, "county": "A", "category": "A"},
            {"pw_number": "PW011", "disaster_number": "4339", "applicant_name": "Entity B",
             "project_amount": 200_000, "federal_share_obligated": 150_000, "county": "B", "category": "B"},
            {"pw_number": "PW012", "disaster_number": "4340", "applicant_name": "Entity C",
             "project_amount": 300_000, "federal_share_obligated": 225_000, "county": "C", "category": "C"},
        ])
        df = _build_linkage(df_v2, self._empty_df(), self._empty_df(),
                            self._empty_df(), self._empty_df(), _LOG)
        assert len(df) == 3
        assert set(df["pw_number"]) == {"PW010", "PW011", "PW012"}

    def test_output_has_all_linkage_columns(self):
        df_v2 = pd.DataFrame([{
            "pw_number": "PW099",
            "disaster_number": "4339",
            "applicant_name": "Column Test",
            "project_amount": 0,
            "federal_share_obligated": 0,
            "county": "",
            "category": "",
        }])
        df = _build_linkage(df_v2, self._empty_df(), self._empty_df(),
                            self._empty_df(), self._empty_df(), _LOG)
        assert list(df.columns) == LINKAGE_COLUMNS


# ===========================================================================
# run() — missing v2 parquet
# ===========================================================================

def test_run_missing_v2_creates_empty_linkage_csv(tmp_path):
    """When fema_pa_projects_v2.parquet is absent, run() must write an empty CSV."""
    _prep_dirs(tmp_path)
    result = run(root=tmp_path)

    linked_path = tmp_path / "data" / "linked" / "fema_178_pw_linkage.csv"
    assert linked_path.exists(), "fema_178_pw_linkage.csv must be created even when v2 is missing"

    df = pd.read_csv(linked_path, dtype=str)
    assert list(df.columns) == LINKAGE_COLUMNS
    assert len(df) == 0


def test_run_missing_v2_returns_dict_with_expected_keys(tmp_path):
    """run() must return a dict with linkage_rows, unmatched_pws, matched_pct, status."""
    _prep_dirs(tmp_path)
    result = run(root=tmp_path)
    for key in ("linkage_rows", "unmatched_pws", "matched_pct", "status"):
        assert key in result, f"result missing key '{key}'"


def test_run_missing_v2_linkage_rows_zero(tmp_path):
    _prep_dirs(tmp_path)
    result = run(root=tmp_path)
    assert result["linkage_rows"] == 0


# ===========================================================================
# run() — with fixture data
# ===========================================================================

def test_run_with_v2_writes_linkage_csv(tmp_path):
    """With a v2 parquet fixture, run() writes fema_178_pw_linkage.csv with rows."""
    _prep_dirs(tmp_path)
    _write_v2(tmp_path, [
        {"pw_number": "PW001", "disaster_number": "4339", "applicant_name": "Test Muni",
         "project_amount": 500_000, "federal_share_obligated": 375_000, "county": "Test", "category": "A"},
    ])

    result = run(root=tmp_path)
    linked_path = tmp_path / "data" / "linked" / "fema_178_pw_linkage.csv"
    assert linked_path.exists()

    df = pd.read_csv(linked_path, dtype=str)
    assert len(df) >= 1
    assert result["linkage_rows"] >= 1


def test_run_with_v2_output_columns_correct(tmp_path):
    """Output CSV must always contain exactly the LINKAGE_COLUMNS."""
    _prep_dirs(tmp_path)
    _write_v2(tmp_path, [
        {"pw_number": "PW002", "disaster_number": "4339", "applicant_name": "Col Check",
         "project_amount": 0, "federal_share_obligated": 0, "county": "", "category": ""},
    ])
    run(root=tmp_path)
    df = pd.read_csv(tmp_path / "data" / "linked" / "fema_178_pw_linkage.csv", dtype=str)
    assert list(df.columns) == LINKAGE_COLUMNS


def test_run_with_portal_fixture_writes_unmatched(tmp_path):
    """Portal PW that doesn't appear in v2 must appear in unmatched review CSV."""
    _prep_dirs(tmp_path)
    # Portal has PW with no corresponding v2 row
    _write_portal(tmp_path, [
        {"pw_number": "PORTAL_ONLY", "disaster_number": "4339",
         "eligible_amount": "50000", "federal_share": "37500",
         "applicant_name": "Ghost Entity", "category": "A", "status": "Approved",
         "source_file": "test.csv"},
    ])
    _write_v2(tmp_path, [
        {"pw_number": "V2_ONLY", "disaster_number": "4339", "applicant_name": "V2 Entity",
         "project_amount": 100_000, "federal_share_obligated": 75_000, "county": "", "category": ""},
    ])

    run(root=tmp_path)
    unmatched_path = tmp_path / "data" / "review" / "fema_pa_unmatched_178_pws.csv"
    assert unmatched_path.exists()
    df_unmatched = pd.read_csv(unmatched_path, dtype=str)
    assert "PORTAL_ONLY" in df_unmatched["pw_number"].values


def test_run_unmatched_has_required_columns(tmp_path):
    """Unmatched PWs CSV must have exactly the UNMATCHED_COLUMNS."""
    _prep_dirs(tmp_path)
    run(root=tmp_path)
    unmatched_path = tmp_path / "data" / "review" / "fema_pa_unmatched_178_pws.csv"
    assert unmatched_path.exists()
    df = pd.read_csv(unmatched_path, dtype=str)
    for col in UNMATCHED_COLUMNS:
        assert col in df.columns, f"Column '{col}' missing from unmatched output"


def test_run_returns_status_ok_on_new_run(tmp_path):
    _prep_dirs(tmp_path)
    result = run(root=tmp_path)
    assert result["status"] == "OK"


def test_run_caching_returns_cached_on_second_call(tmp_path):
    """Second run() without force=True returns status=CACHED."""
    _prep_dirs(tmp_path)
    run(root=tmp_path)
    result2 = run(root=tmp_path)
    assert result2["status"] == "CACHED"


def test_run_force_reruns_when_cached(tmp_path):
    """run(force=True) overwrites existing output and returns status=OK."""
    _prep_dirs(tmp_path)
    _write_v2(tmp_path, [
        {"pw_number": "PW010", "disaster_number": "4339", "applicant_name": "Force Test",
         "project_amount": 100_000, "federal_share_obligated": 75_000, "county": "", "category": ""},
    ])
    run(root=tmp_path)
    result2 = run(root=tmp_path, force=True)
    assert result2["status"] == "OK"


def test_run_matched_pct_positive_when_contract_present(tmp_path):
    """When contracts file matches applicant name, matched_pct > 0."""
    _prep_dirs(tmp_path)
    applicant = "Puerto Rico Electric Power Authority"
    _write_v2(tmp_path, [
        {"pw_number": "PW020", "disaster_number": "4339", "applicant_name": applicant,
         "project_amount": 5_000_000, "federal_share_obligated": 3_750_000,
         "county": "San Juan", "category": "F"},
    ])
    # Write a contracts CSV that matches by recipient_name
    df_contracts = pd.DataFrame([{
        "recipient_name": applicant,
        "award_id": "PREPA-001",
    }])
    df_contracts.to_csv(
        tmp_path / "data" / "staging" / "processed" / "pr_contracts_master.csv",
        index=False,
    )

    result = run(root=tmp_path)
    assert result["matched_pct"] > 0
