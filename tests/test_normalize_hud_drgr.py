"""Tests for scripts/normalize_hud_drgr.py — HUD DRGR normalization."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.normalize_hud_drgr import (
    ORG_COLUMNS,
    PROJECT_COLUMNS,
    _build_projects,
    _build_responsible_orgs,
    _load,
    run,
)
from scripts.parquet_utils import pq_write


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _logger():
    m = MagicMock()
    m.info = MagicMock()
    m.warning = MagicMock()
    return m


def _write_parquet(root: Path, filename: str, df: pd.DataFrame) -> Path:
    path = root / "data" / "normalized" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    pq_write(df, path)
    return path


def _grants_df(**extras) -> pd.DataFrame:
    base = {
        "grant_number": ["B-19-DG-001"],
        "grantee_name": ["Municipality of San Juan"],
        "grantee_normalized": ["MUNICIPALITY SAN JUAN"],
        "disaster_number": ["DR-4339"],
        "grant_amount": [5_000_000.0],
        "amount_drawn": [2_500_000.0],
        "program_type": ["CDBG-DR"],
    }
    base.update(extras)
    return pd.DataFrame(base)


def _activities_df(**extras) -> pd.DataFrame:
    base = {
        "grant_number": ["B-19-DG-001", "B-19-DG-001"],
        "responsible_org": ["Dept of Housing", "Dept of Housing"],
        "amount_drawn": [500_000.0, 300_000.0],
        "total_budget": [600_000.0, 400_000.0],
        "status": ["COMPLETED", "OPEN"],
    }
    base.update(extras)
    return pd.DataFrame(base)


# ---------------------------------------------------------------------------
# _load
# ---------------------------------------------------------------------------

class TestLoad:
    def test_returns_empty_df_when_file_missing(self, tmp_path):
        missing = tmp_path / "data" / "normalized" / "missing.parquet"
        result = _load(missing, _logger())
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_returns_empty_df_on_read_error(self, tmp_path):
        bad = tmp_path / "data" / "normalized" / "bad.parquet"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_bytes(b"not a parquet file at all")
        result = _load(bad, _logger())
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_returns_loaded_dataframe(self, tmp_path):
        df = pd.DataFrame({"col_a": [1, 2], "col_b": ["x", "y"]})
        path = _write_parquet(tmp_path, "sample.parquet", df)
        result = _load(path, _logger())
        assert len(result) == 2
        assert "col_a" in result.columns


# ---------------------------------------------------------------------------
# _build_projects
# ---------------------------------------------------------------------------

class TestBuildProjects:
    def test_returns_project_columns(self):
        df_projects = _build_projects(_grants_df(), pd.DataFrame(), pd.DataFrame(), _logger())
        for col in PROJECT_COLUMNS:
            assert col in df_projects.columns

    def test_disbursement_rate_calculation(self):
        grants = pd.DataFrame({
            "grant_number": ["G001"],
            "grantee_name": ["Municipality A"],
            "grant_amount": [1_000_000.0],
            "amount_drawn": [250_000.0],
            "program_type": ["CDBG-DR"],
            "disaster_number": ["DR-1"],
        })
        result = _build_projects(grants, pd.DataFrame(), pd.DataFrame(), _logger())
        assert result.iloc[0]["disbursement_rate"] == pytest.approx(0.25, abs=0.001)

    def test_zero_grant_amount_disbursement_rate_is_zero(self):
        grants = pd.DataFrame({
            "grant_number": ["G002"],
            "grantee_name": ["Org B"],
            "grant_amount": [0.0],
            "amount_drawn": [0.0],
            "program_type": ["CDBG"],
            "disaster_number": [""],
        })
        result = _build_projects(grants, pd.DataFrame(), pd.DataFrame(), _logger())
        assert result.iloc[0]["disbursement_rate"] == 0.0

    def test_activity_count_populated_from_activities(self):
        grants = _grants_df()
        activities = _activities_df()
        result = _build_projects(grants, pd.DataFrame(), activities, _logger())
        assert result.iloc[0]["activity_count"] == 2

    def test_completed_activity_count(self):
        grants = _grants_df()
        activities = _activities_df()
        result = _build_projects(grants, pd.DataFrame(), activities, _logger())
        assert result.iloc[0]["completed_activity_count"] == 1

    def test_empty_grants_returns_empty_df(self):
        result = _build_projects(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), _logger())
        assert result.empty or len(result) == 0

    def test_grantee_name_preserved(self):
        grants = _grants_df()
        result = _build_projects(grants, pd.DataFrame(), pd.DataFrame(), _logger())
        assert result.iloc[0]["grantee_name"] == "Municipality of San Juan"

    def test_source_system_is_hud_drgr(self):
        grants = _grants_df()
        result = _build_projects(grants, pd.DataFrame(), pd.DataFrame(), _logger())
        assert result.iloc[0]["source_system"] == "hud_drgr"


# ---------------------------------------------------------------------------
# _build_responsible_orgs
# ---------------------------------------------------------------------------

class TestBuildResponsibleOrgs:
    def test_returns_org_columns(self):
        activities = _activities_df()
        result = _build_responsible_orgs(activities, _logger())
        for col in ORG_COLUMNS:
            assert col in result.columns

    def test_aggregates_by_org(self):
        activities = _activities_df()
        result = _build_responsible_orgs(activities, _logger())
        assert len(result) == 1
        assert result.iloc[0]["responsible_org"] == "Dept of Housing"

    def test_activity_count_correct(self):
        activities = _activities_df()
        result = _build_responsible_orgs(activities, _logger())
        assert result.iloc[0]["activity_count"] == 2

    def test_total_drawn_summed(self):
        activities = _activities_df()
        result = _build_responsible_orgs(activities, _logger())
        assert result.iloc[0]["total_drawn"] == pytest.approx(800_000.0, abs=1)

    def test_empty_activities_returns_empty(self):
        result = _build_responsible_orgs(pd.DataFrame(), _logger())
        assert result.empty

    def test_skips_empty_org_names(self):
        activities = pd.DataFrame({
            "grant_number": ["G001", "G001"],
            "responsible_org": ["Dept A", ""],
            "amount_drawn": [100_000.0, 50_000.0],
            "total_budget": [200_000.0, 100_000.0],
        })
        result = _build_responsible_orgs(activities, _logger())
        assert len(result) == 1
        assert result.iloc[0]["responsible_org"] == "Dept A"

    def test_sorted_descending_by_total_budget(self):
        activities = pd.DataFrame({
            "grant_number": ["G001", "G002"],
            "responsible_org": ["Small Org", "Big Org"],
            "amount_drawn": [10_000.0, 500_000.0],
            "total_budget": [20_000.0, 1_000_000.0],
        })
        result = _build_responsible_orgs(activities, _logger())
        assert result.iloc[0]["responsible_org"] == "Big Org"


# ---------------------------------------------------------------------------
# run() integration
# ---------------------------------------------------------------------------

class TestRunIntegration:
    def test_run_writes_projects_parquet(self, tmp_path):
        _write_parquet(tmp_path, "hud_drgr_grants.parquet", _grants_df())
        result = run(root=tmp_path, force=True)
        project_path = tmp_path / "data" / "normalized" / "hud_drgr_projects.parquet"
        assert project_path.exists()
        assert result["status"] == "OK"

    def test_run_writes_orgs_parquet(self, tmp_path):
        _write_parquet(tmp_path, "hud_drgr_grants.parquet", _grants_df())
        _write_parquet(tmp_path, "hud_drgr_activities.parquet", _activities_df())
        run(root=tmp_path, force=True)
        org_path = tmp_path / "data" / "normalized" / "hud_drgr_responsible_orgs_resolved.parquet"
        assert org_path.exists()

    def test_run_no_inputs_returns_ok_with_zero_rows(self, tmp_path):
        result = run(root=tmp_path, force=True)
        assert result["status"] == "OK"
        assert result["project_rows"] == 0

    def test_run_cached_skips_rebuild(self, tmp_path):
        _write_parquet(tmp_path, "hud_drgr_grants.parquet", _grants_df())
        run(root=tmp_path, force=True)
        # Second call without force → should use cache
        result = run(root=tmp_path, force=False)
        assert result["status"] == "CACHED"

    def test_run_force_rebuilds(self, tmp_path):
        _write_parquet(tmp_path, "hud_drgr_grants.parquet", _grants_df())
        run(root=tmp_path, force=True)
        result = run(root=tmp_path, force=True)
        assert result["status"] == "OK"

    def test_disbursement_rate_in_output(self, tmp_path):
        grants = pd.DataFrame({
            "grant_number": ["G001"],
            "grantee_name": ["Test Grantee"],
            "grant_amount": [2_000_000.0],
            "amount_drawn": [1_000_000.0],
            "program_type": ["CDBG-DR"],
            "disaster_number": ["DR-1"],
        })
        _write_parquet(tmp_path, "hud_drgr_grants.parquet", grants)
        run(root=tmp_path, force=True)
        from scripts.parquet_utils import pq_read
        df = pq_read(tmp_path / "data" / "normalized" / "hud_drgr_projects.parquet")
        assert df.iloc[0]["disbursement_rate"] == pytest.approx(0.5, abs=0.001)
