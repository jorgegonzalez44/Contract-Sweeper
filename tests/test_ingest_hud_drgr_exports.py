"""
Tests for scripts/ingest_hud_drgr_exports.py

Covers:
  - _classify()    : detects activities / drawdowns / appropriations / default
  - _map_col()     : exact and case-insensitive column matching
  - _map_to_schema(): maps raw columns to canonical output schema
  - run()          : no-files path → empty parquets; CSV fixture → coerced schema
"""

import logging
import pandas as pd
import pytest
from pathlib import Path

from scripts.ingest_hud_drgr_exports import (
    _classify,
    _map_col,
    _map_to_schema,
    _find_raw_files,
    run,
    ACTIVITY_COLUMNS,
    DRAWDOWN_COLUMNS,
    APPROPRIATION_COLUMNS,
    ACTIVITY_COL_MAP,
    DRAWDOWN_COL_MAP,
    APPROPRIATION_COL_MAP,
)
from scripts.parquet_utils import pq_read


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _silent_logger():
    logger = logging.getLogger("test_hud_drgr")
    logger.setLevel(logging.CRITICAL)
    return logger


# ---------------------------------------------------------------------------
# _classify — type-detection based on filename stem + column names
# ---------------------------------------------------------------------------

def test_classify_activities_by_column():
    """DataFrame whose columns contain 'Activity' → classified as activities."""
    path = Path("hud_export.csv")
    df = pd.DataFrame(columns=["Activity ID", "Activity Name", "Status"])
    assert _classify(path, df) == "activities"


def test_classify_drawdowns_by_filename():
    """Filename containing 'drawdown' → classified as drawdowns."""
    path = Path("DRGR_drawdowns_2023.csv")
    df = pd.DataFrame(columns=["Draw ID", "Amount"])
    assert _classify(path, df) == "drawdowns"


def test_classify_drawdowns_by_column():
    """Column 'drawdown_date' triggers drawdowns classification."""
    path = Path("hud_payments.csv")
    df = pd.DataFrame(columns=["drawdown_date", "drawdown_amount"])
    assert _classify(path, df) == "drawdowns"


def test_classify_appropriations_by_filename():
    """Filename containing 'appropriat' → classified as appropriations."""
    path = Path("HUD_appropriations_FY22.csv")
    df = pd.DataFrame(columns=["Grant", "Amount"])
    assert _classify(path, df) == "appropriations"


def test_classify_appropriations_by_column():
    """Column 'allocation_date' triggers appropriations classification."""
    path = Path("grants.csv")
    df = pd.DataFrame(columns=["Appropriation Amount", "allocation_date"])
    assert _classify(path, df) == "appropriations"


def test_classify_default_to_activities():
    """File with no matching keywords → defaults to 'activities'."""
    path = Path("mystery_file.csv")
    df = pd.DataFrame(columns=["Col A", "Col B"])
    # scores all zero → falls back to 'activities'
    assert _classify(path, df) == "activities"


# ---------------------------------------------------------------------------
# _map_col — column resolution helper
# ---------------------------------------------------------------------------

def test_map_col_exact_match():
    cols = ["Activity ID", "Grant Number", "Status"]
    assert _map_col(cols, ["Activity ID", "Activity Number"]) == "Activity ID"


def test_map_col_case_insensitive():
    cols = ["activity id", "grant number"]
    assert _map_col(cols, ["Activity ID"]) == "activity id"


def test_map_col_returns_none_when_missing():
    cols = ["Column X", "Column Y"]
    assert _map_col(cols, ["Activity ID", "Activity Number"]) is None


def test_map_col_prefers_first_candidate():
    """When multiple candidates match, first listed should win."""
    cols = ["Activity Number", "Activity ID"]
    result = _map_col(cols, ["Activity ID", "Activity Number"])
    # First candidate that exists in df_cols is "Activity ID"
    assert result == "Activity ID"


# ---------------------------------------------------------------------------
# Column schema constants
# ---------------------------------------------------------------------------

def test_activity_columns_complete():
    for col in ("activity_id", "grant_number", "activity_name", "status",
                "responsible_org", "responsible_org_normalized",
                "total_budget", "amount_drawn", "source_file"):
        assert col in ACTIVITY_COLUMNS, f"Missing: {col}"


def test_drawdown_columns_complete():
    for col in ("drawdown_id", "grant_number", "activity_id",
                "drawdown_date", "drawdown_amount", "source_file"):
        assert col in DRAWDOWN_COLUMNS, f"Missing: {col}"


def test_appropriation_columns_complete():
    for col in ("appropriation_id", "grant_number", "program_type",
                "appropriation_amount", "grantee_name", "source_file"):
        assert col in APPROPRIATION_COLUMNS, f"Missing: {col}"


# ---------------------------------------------------------------------------
# _map_to_schema — schema coercion
# ---------------------------------------------------------------------------

def test_map_to_schema_activity_canonical_cols():
    """_map_to_schema returns all ACTIVITY_COLUMNS in the correct order."""
    df = pd.DataFrame({
        "Activity ID":     ["ACT-001"],
        "Grant Number":    ["B-20-DC-72-0001"],
        "Activity Name":   ["Housing Rehab"],
        "Status":          ["Open"],
        "Responsible Org": ["Municipality of San Juan"],
        "Total Budget":    ["500000"],
        "Amount Drawn":    ["150000"],
    })
    result = _map_to_schema(df, ACTIVITY_COL_MAP, ACTIVITY_COLUMNS, "test.csv")
    assert list(result.columns) == ACTIVITY_COLUMNS


def test_map_to_schema_drawdown_canonical_cols():
    df = pd.DataFrame({
        "Drawdown ID":     ["DD-001"],
        "Grant Number":    ["B-20-DC-72-0001"],
        "Activity ID":     ["ACT-001"],
        "Drawdown Date":   ["2023-06-01"],
        "Drawdown Amount": ["25000"],
    })
    result = _map_to_schema(df, DRAWDOWN_COL_MAP, DRAWDOWN_COLUMNS, "test.csv")
    assert list(result.columns) == DRAWDOWN_COLUMNS


def test_map_to_schema_fills_missing_cols_with_empty():
    """Columns not present in source DataFrame are filled with empty string."""
    df = pd.DataFrame({"Activity ID": ["A1"]})
    result = _map_to_schema(df, ACTIVITY_COL_MAP, ACTIVITY_COLUMNS, "test.csv")
    assert set(result.columns) == set(ACTIVITY_COLUMNS)
    # activity_name should be empty (not in source)
    assert result.iloc[0]["activity_name"] == ""


def test_map_to_schema_source_file_column():
    df = pd.DataFrame({"Activity ID": ["A1"]})
    result = _map_to_schema(df, ACTIVITY_COL_MAP, ACTIVITY_COLUMNS, "myfile.csv")
    assert (result["source_file"] == "myfile.csv").all()


# ---------------------------------------------------------------------------
# run() — no-files scenario: writes empty parquets with correct schemas
# ---------------------------------------------------------------------------

def test_run_no_files_returns_ok_status(tmp_path):
    result = run(root=tmp_path, force=True)
    assert result["status"] == "OK"


def test_run_no_files_zero_rows(tmp_path):
    result = run(root=tmp_path, force=True)
    assert result["activity_rows"] == 0
    assert result["drawdown_rows"] == 0
    assert result["appropriation_rows"] == 0


def test_run_no_files_activities_parquet_exists(tmp_path):
    run(root=tmp_path, force=True)
    norm = tmp_path / "data" / "normalized"
    assert (norm / "hud_drgr_activities.parquet").exists() or \
           (norm / "hud_drgr_activities.csv").exists()


def test_run_no_files_drawdowns_parquet_exists(tmp_path):
    run(root=tmp_path, force=True)
    norm = tmp_path / "data" / "normalized"
    assert (norm / "hud_drgr_drawdowns.parquet").exists() or \
           (norm / "hud_drgr_drawdowns.csv").exists()


def test_run_no_files_appropriations_parquet_exists(tmp_path):
    run(root=tmp_path, force=True)
    norm = tmp_path / "data" / "normalized"
    assert (norm / "hud_drgr_appropriations.parquet").exists() or \
           (norm / "hud_drgr_appropriations.csv").exists()


def test_run_no_files_activities_schema(tmp_path):
    """Empty activities parquet must carry the canonical column set."""
    run(root=tmp_path, force=True)
    norm = tmp_path / "data" / "normalized"
    df = pq_read(norm / "hud_drgr_activities.parquet")
    for col in ACTIVITY_COLUMNS:
        assert col in df.columns, f"Missing column: {col}"


def test_run_no_files_drawdowns_schema(tmp_path):
    run(root=tmp_path, force=True)
    norm = tmp_path / "data" / "normalized"
    df = pq_read(norm / "hud_drgr_drawdowns.parquet")
    for col in DRAWDOWN_COLUMNS:
        assert col in df.columns, f"Missing column: {col}"


def test_run_no_files_appropriations_schema(tmp_path):
    run(root=tmp_path, force=True)
    norm = tmp_path / "data" / "normalized"
    df = pq_read(norm / "hud_drgr_appropriations.parquet")
    for col in APPROPRIATION_COLUMNS:
        assert col in df.columns, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# run() — with CSV fixture
# ---------------------------------------------------------------------------

def _make_hud_dir(tmp_path):
    hud_dir = tmp_path / "data" / "raw" / "HUD DRGR"
    hud_dir.mkdir(parents=True, exist_ok=True)
    return hud_dir


def test_run_with_activity_csv_rows(tmp_path):
    """run() ingests a well-formed activity CSV and returns correct row count."""
    hud_dir = _make_hud_dir(tmp_path)
    df = pd.DataFrame({
        "Activity ID":           ["ACT-001", "ACT-002"],
        "Grant Number":          ["B-20-DC-72-0001"] * 2,
        "Activity Name":         ["Rehab A", "Rehab B"],
        "Status":                ["Open", "Closed"],
        "Responsible Organization": ["City of Ponce", "City of Mayaguez"],
        "Total Budget":          ["500000", "250000"],
        "Amount Drawn":          ["150000", "100000"],
    })
    df.to_csv(hud_dir / "activities_export.csv", index=False)

    result = run(root=tmp_path, force=True)
    assert result["activity_rows"] == 2
    assert result["status"] == "OK"


def test_run_with_activity_csv_schema_coercion(tmp_path):
    """Output parquet contains all ACTIVITY_COLUMNS even from partial CSV."""
    hud_dir = _make_hud_dir(tmp_path)
    df = pd.DataFrame({
        "Activity ID":  ["ACT-001"],
        "Grant Number": ["B-20-DC-72-0001"],
        "Activity Name": ["Infrastructure Repair"],
    })
    df.to_csv(hud_dir / "activities_partial.csv", index=False)

    run(root=tmp_path, force=True)
    norm = tmp_path / "data" / "normalized"
    out = pq_read(norm / "hud_drgr_activities.parquet")
    assert set(ACTIVITY_COLUMNS).issubset(set(out.columns))


def test_run_with_drawdown_csv_rows(tmp_path):
    """Drawdown CSV is classified correctly and rows are saved."""
    hud_dir = _make_hud_dir(tmp_path)
    df = pd.DataFrame({
        "Drawdown ID":     ["DD-001", "DD-002", "DD-003"],
        "Grant Number":    ["B-20-DC-72-0001"] * 3,
        "Activity ID":     ["ACT-001", "ACT-001", "ACT-002"],
        "Drawdown Date":   ["2023-01-15", "2023-03-20", "2023-06-01"],
        "Drawdown Amount": ["25000", "30000", "15000"],
    })
    df.to_csv(hud_dir / "drawdowns_report.csv", index=False)

    result = run(root=tmp_path, force=True)
    assert result["drawdown_rows"] == 3


def test_run_with_appropriation_csv_rows(tmp_path):
    """Appropriations CSV is classified correctly and rows are saved."""
    hud_dir = _make_hud_dir(tmp_path)
    df = pd.DataFrame({
        "Appropriation ID":     ["AP-001"],
        "Grant Number":         ["B-20-DC-72-0001"],
        "Program Type":         ["CDBG-DR"],
        "Appropriation Amount": ["1000000000"],
        "Grantee Name":         ["Government of Puerto Rico"],
    })
    df.to_csv(hud_dir / "appropriations_list.csv", index=False)

    result = run(root=tmp_path, force=True)
    assert result["appropriation_rows"] == 1


def test_run_cached_returns_cached_status(tmp_path):
    """Second run() without force=True returns CACHED status."""
    run(root=tmp_path, force=True)
    result2 = run(root=tmp_path, force=False)
    assert result2["status"] == "CACHED"


def test_run_responsible_org_normalized(tmp_path):
    """responsible_org_normalized column is populated for activity rows."""
    hud_dir = _make_hud_dir(tmp_path)
    df = pd.DataFrame({
        "Activity ID":             ["ACT-001"],
        "Responsible Organization": ["Fluor Corporation Inc"],
    })
    df.to_csv(hud_dir / "activities_org.csv", index=False)

    run(root=tmp_path, force=True)
    norm = tmp_path / "data" / "normalized"
    out = pq_read(norm / "hud_drgr_activities.parquet")
    assert "responsible_org_normalized" in out.columns
    val = out.iloc[0]["responsible_org_normalized"]
    assert isinstance(val, str) and len(val) > 0
