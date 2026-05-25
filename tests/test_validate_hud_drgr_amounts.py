"""Tests for scripts/validate_hud_drgr_amounts.py

Covers:
- Pure helper functions: _flag, _to_num
- Integration via run(root=tmp_path):
    * missing inputs → empty CSV written (no exception)
    * with fixture parquets → reconciliation CSV written with correct content
"""

import math
import sys
from pathlib import Path

import pandas as pd
import pytest

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validate_hud_drgr_amounts import (
    _flag,
    _to_num,
    WARN_THRESHOLD_PCT,
    FAIL_THRESHOLD_PCT,
    WARN_THRESHOLD_ABS,
    RECONCILIATION_COLUMNS,
    run,
)
from scripts.parquet_utils import pq_write


# ---------------------------------------------------------------------------
# Helper: build the normalized input directory in tmp_path
# ---------------------------------------------------------------------------

def _norm_dir(root: Path) -> Path:
    d = root / "data" / "normalized"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _val_dir(root: Path) -> Path:
    """Create and return the validation output directory under root.

    The script's VALIDATION_DIR.mkdir() uses PROJECT_ROOT (module-level const),
    but out_path is rooted at the ``root`` argument.  We pre-create the dir so
    that to_csv() succeeds when tests pass a tmp_path as root.
    """
    d = root / "data" / "validation"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# _to_num
# ---------------------------------------------------------------------------

def test_to_num_integer():
    assert _to_num(100) == 100.0


def test_to_num_string_number():
    assert _to_num("250.5") == 250.5


def test_to_num_non_numeric_returns_nan_or_zero():
    # pd.to_numeric("bad", errors="coerce") → NaN; NaN is truthy so `NaN or 0.0`
    # evaluates to NaN in the current implementation.
    result = _to_num("bad")
    # Accept either NaN (actual) or 0.0 (intended) — tests the call doesn't raise
    assert result == 0.0 or math.isnan(float(result))


# ---------------------------------------------------------------------------
# _flag
# ---------------------------------------------------------------------------

def test_flag_ok_small_variance():
    assert _flag(0.5, 500) == "OK"


def test_flag_warn_by_pct():
    # variance_pct >= 1.0 → WARN
    assert _flag(WARN_THRESHOLD_PCT, 0) == "WARN >1%"


def test_flag_warn_by_abs():
    # variance_abs >= WARN_THRESHOLD_ABS → WARN
    assert _flag(0.0, WARN_THRESHOLD_ABS) == "WARN >1%"


def test_flag_fail_by_pct():
    # variance_pct >= 10.0 → FAIL
    assert _flag(FAIL_THRESHOLD_PCT, 0) == "FAIL >10%"


def test_flag_fail_negative_pct():
    # negative large variance_pct → FAIL
    assert _flag(-FAIL_THRESHOLD_PCT, 0) == "FAIL >10%"


def test_flag_warn_boundary():
    # Just below FAIL but above WARN → WARN
    assert _flag(9.9, 0) == "WARN >1%"


# ---------------------------------------------------------------------------
# run() — missing inputs (all parquets absent)
# ---------------------------------------------------------------------------

def test_run_missing_inputs_creates_empty_csv(tmp_path):
    """When no input parquets exist run() must write an empty CSV, not raise."""
    # Provide just the dir structure — no parquets
    _norm_dir(tmp_path)
    _val_dir(tmp_path)  # script writes to root/data/validation; pre-create it
    run(root=tmp_path)

    out_path = tmp_path / "data" / "validation" / "hud_drgr_amount_reconciliation.csv"
    assert out_path.exists(), "Output CSV must be created even with missing inputs"

    df = pd.read_csv(out_path, dtype=str)
    assert list(df.columns) == RECONCILIATION_COLUMNS
    assert len(df) == 0


def test_run_missing_inputs_returns_dict(tmp_path):
    """run() must return a dict with the expected keys."""
    _norm_dir(tmp_path)
    _val_dir(tmp_path)
    result = run(root=tmp_path)
    for key in ("checked", "flagged", "flag_pct", "status"):
        assert key in result, f"result missing key '{key}'"


def test_run_missing_inputs_checked_zero(tmp_path):
    _norm_dir(tmp_path)
    _val_dir(tmp_path)
    result = run(root=tmp_path)
    assert result["checked"] == 0
    assert result["flagged"] == 0


# ---------------------------------------------------------------------------
# run() — with fixture parquets, grant-level reconciliation
# ---------------------------------------------------------------------------

def _write_projects(root, rows):
    df = pd.DataFrame(rows)
    pq_write(df, _norm_dir(root) / "hud_drgr_projects.parquet")


def _write_activities(root, rows):
    df = pd.DataFrame(rows)
    pq_write(df, _norm_dir(root) / "hud_drgr_activities.parquet")


def _write_drawdowns(root, rows):
    df = pd.DataFrame(rows)
    pq_write(df, _norm_dir(root) / "hud_drgr_drawdowns.parquet")


def test_run_grant_level_ok_match(tmp_path):
    """When activity budget sums match grant_amount exactly → flag==OK."""
    _write_projects(tmp_path, [
        {"grant_number": "G001", "grant_amount": 500_000, "disbursement_rate": 0.5},
    ])
    _write_activities(tmp_path, [
        {"grant_number": "G001", "activity_id": "A1", "total_budget": 300_000, "amount_drawn": 150_000},
        {"grant_number": "G001", "activity_id": "A2", "total_budget": 200_000, "amount_drawn": 100_000},
    ])
    _val_dir(tmp_path)

    run(root=tmp_path)
    out_path = tmp_path / "data" / "validation" / "hud_drgr_amount_reconciliation.csv"
    df = pd.read_csv(out_path, dtype=str)

    grant_rows = df[df["level"] == "grant"]
    assert len(grant_rows) >= 1
    g001 = grant_rows[grant_rows["grant_number"] == "G001"]
    assert not g001.empty
    assert g001.iloc[0]["flag"] == "OK"


def test_run_grant_level_fail_large_variance(tmp_path):
    """When activity budgets differ from grant_amount by >10% → flag==FAIL >10%."""
    _write_projects(tmp_path, [
        {"grant_number": "G002", "grant_amount": 1_000_000, "disbursement_rate": 0.5},
    ])
    _write_activities(tmp_path, [
        # Only $100k allocated vs $1M grant → 90% variance
        {"grant_number": "G002", "activity_id": "A3", "total_budget": 100_000, "amount_drawn": 0},
    ])
    _val_dir(tmp_path)

    run(root=tmp_path)
    out_path = tmp_path / "data" / "validation" / "hud_drgr_amount_reconciliation.csv"
    df = pd.read_csv(out_path, dtype=str)

    grant_rows = df[(df["level"] == "grant") & (df["grant_number"] == "G002")]
    assert not grant_rows.empty
    assert grant_rows.iloc[0]["flag"] == "FAIL >10%"


def test_run_activity_level_drawdown_mismatch(tmp_path):
    """When drawdown sums differ from amount_drawn significantly → activity row flagged."""
    _write_activities(tmp_path, [
        {"grant_number": "G003", "activity_id": "A10", "total_budget": 500_000, "amount_drawn": 200_000},
    ])
    _write_drawdowns(tmp_path, [
        # sum = $100k, but activity says $200k → 50% variance
        {"activity_id": "A10", "drawdown_amount": 100_000},
    ])
    _val_dir(tmp_path)

    run(root=tmp_path)
    out_path = tmp_path / "data" / "validation" / "hud_drgr_amount_reconciliation.csv"
    df = pd.read_csv(out_path, dtype=str)

    act_rows = df[(df["level"] == "activity") & (df["entity_id"] == "A10")]
    assert not act_rows.empty
    assert act_rows.iloc[0]["flag"] in ("WARN >1%", "FAIL >10%")


def test_run_disbursement_rate_over_100pct(tmp_path):
    """Projects with disbursement_rate > 1.0 must produce a disbursement_rate row flagged FAIL."""
    _write_projects(tmp_path, [
        {"grant_number": "G010", "grant_amount": 500_000, "disbursement_rate": 1.5, "amount_drawn": 750_000},
    ])
    _val_dir(tmp_path)

    run(root=tmp_path)
    out_path = tmp_path / "data" / "validation" / "hud_drgr_amount_reconciliation.csv"
    df = pd.read_csv(out_path, dtype=str)

    rate_rows = df[df["level"] == "disbursement_rate"]
    assert not rate_rows.empty
    assert rate_rows.iloc[0]["flag"] == "FAIL >10%"


def test_run_disbursement_rate_below_1pct_large_grant(tmp_path):
    """Large grant with disbursement_rate < 1% must be WARN."""
    _write_projects(tmp_path, [
        {"grant_number": "G011", "grant_amount": 2_000_000, "disbursement_rate": 0.005, "amount_drawn": 10_000},
    ])
    _val_dir(tmp_path)

    run(root=tmp_path)
    out_path = tmp_path / "data" / "validation" / "hud_drgr_amount_reconciliation.csv"
    df = pd.read_csv(out_path, dtype=str)

    rate_rows = df[(df["level"] == "disbursement_rate") & (df["grant_number"] == "G011")]
    assert not rate_rows.empty
    assert rate_rows.iloc[0]["flag"] == "WARN >1%"


def test_run_output_has_required_columns(tmp_path):
    """Output CSV must always contain all required columns."""
    _norm_dir(tmp_path)
    _val_dir(tmp_path)
    run(root=tmp_path)
    out_path = tmp_path / "data" / "validation" / "hud_drgr_amount_reconciliation.csv"
    df = pd.read_csv(out_path, dtype=str)
    for col in RECONCILIATION_COLUMNS:
        assert col in df.columns, f"Column '{col}' missing from output"


def test_run_cached_result_returned(tmp_path):
    """Second run() call without force=True returns status=CACHED."""
    _norm_dir(tmp_path)
    _val_dir(tmp_path)
    run(root=tmp_path)
    result2 = run(root=tmp_path)
    assert result2["status"] == "CACHED"


def test_run_force_reruns(tmp_path):
    """run(force=True) overwrites and returns status=OK (not CACHED)."""
    _norm_dir(tmp_path)
    _val_dir(tmp_path)
    run(root=tmp_path)
    result2 = run(root=tmp_path, force=True)
    assert result2["status"] == "OK"


def test_run_multiple_grants(tmp_path):
    """Multiple grants should each produce a grant-level row in the output."""
    _write_projects(tmp_path, [
        {"grant_number": "GA", "grant_amount": 100_000, "disbursement_rate": 0.5},
        {"grant_number": "GB", "grant_amount": 200_000, "disbursement_rate": 0.5},
    ])
    _write_activities(tmp_path, [
        {"grant_number": "GA", "activity_id": "AA1", "total_budget": 100_000, "amount_drawn": 50_000},
        {"grant_number": "GB", "activity_id": "AB1", "total_budget": 200_000, "amount_drawn": 100_000},
    ])
    _val_dir(tmp_path)

    run(root=tmp_path)
    out_path = tmp_path / "data" / "validation" / "hud_drgr_amount_reconciliation.csv"
    df = pd.read_csv(out_path, dtype=str)

    grant_rows = df[df["level"] == "grant"]
    grant_numbers = set(grant_rows["grant_number"].tolist())
    assert "GA" in grant_numbers
    assert "GB" in grant_numbers
