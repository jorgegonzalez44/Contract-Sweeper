"""Tests for scripts/build_financial_flows_master.py — financial flows synthesis."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.build_financial_flows_master import (
    FLOW_COLUMNS,
    _ingest_contracts,
    _ingest_cor3,
    _ingest_fema_pa,
    _ingest_hud_drgr,
    _ingest_pr_procurement,
    run,
)
from scripts.parquet_utils import pq_read, pq_write


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _logger():
    m = MagicMock()
    m.info = MagicMock()
    m.warning = MagicMock()
    return m


def _write_parquet(root: Path, rel: str, df: pd.DataFrame) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    pq_write(df, path)
    return path


def _write_csv(root: Path, rel: str, df: pd.DataFrame) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# FLOW_COLUMNS completeness
# ---------------------------------------------------------------------------

class TestFlowColumns:
    _REQUIRED = [
        "flow_id", "flow_type", "source_system", "source_file",
        "funding_source", "prime_vendor", "amount", "amount_type",
        "grant_number", "disaster_number",
    ]

    def test_required_columns_present(self):
        for col in self._REQUIRED:
            assert col in FLOW_COLUMNS, f"Missing required column: {col}"

    def test_flow_id_in_columns(self):
        assert "flow_id" in FLOW_COLUMNS

    def test_no_duplicate_columns(self):
        assert len(FLOW_COLUMNS) == len(set(FLOW_COLUMNS))


# ---------------------------------------------------------------------------
# _ingest_contracts
# ---------------------------------------------------------------------------

class TestIngestContracts:
    def test_empty_df_returns_empty_list(self):
        rows = _ingest_contracts(pd.DataFrame(), _logger())
        assert rows == []

    def test_each_row_has_all_flow_columns(self):
        df = pd.DataFrame([{
            "recipient_name": "Vendor A", "obligated_amount": "500000",
            "award_id": "AWD001", "source_dataset": "usaspending",
        }])
        rows = _ingest_contracts(df, _logger())
        assert len(rows) == 1
        for col in FLOW_COLUMNS:
            assert col in rows[0]

    def test_flow_type_is_federal_contract(self):
        df = pd.DataFrame([{"recipient_name": "V", "obligated_amount": "1000"}])
        rows = _ingest_contracts(df, _logger())
        assert rows[0]["flow_type"] == "federal_contract"

    def test_flow_id_is_unique_per_row(self):
        df = pd.DataFrame([
            {"recipient_name": "V1", "obligated_amount": "1000"},
            {"recipient_name": "V2", "obligated_amount": "2000"},
        ])
        rows = _ingest_contracts(df, _logger())
        ids = [r["flow_id"] for r in rows]
        assert len(set(ids)) == 2


# ---------------------------------------------------------------------------
# _ingest_hud_drgr
# ---------------------------------------------------------------------------

class TestIngestHudDrgr:
    def test_empty_inputs_return_empty_list(self):
        rows = _ingest_hud_drgr(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), _logger())
        assert rows == []

    def test_project_rows_produce_grant_flows(self):
        df_proj = pd.DataFrame([{
            "grant_number": "B-19-001", "grantee_name": "Test Grantee",
            "grant_amount": "5000000", "program_type": "CDBG-DR",
            "disaster_number": "DR-4339",
        }])
        rows = _ingest_hud_drgr(df_proj, pd.DataFrame(), pd.DataFrame(), _logger())
        assert len(rows) == 1
        assert rows[0]["flow_type"] == "federal_cdbg_grant"
        assert rows[0]["grant_number"] == "B-19-001"

    def test_drawdown_rows_included(self):
        df_draws = pd.DataFrame([{
            "grant_number": "B-19-001", "activity_id": "ACT001",
            "drawdown_amount": "100000", "drawdown_date": "2022-01-01",
        }])
        rows = _ingest_hud_drgr(pd.DataFrame(), pd.DataFrame(), df_draws, _logger())
        assert len(rows) == 1
        assert rows[0]["flow_type"] == "hud_drgr_drawdown"


# ---------------------------------------------------------------------------
# _ingest_fema_pa
# ---------------------------------------------------------------------------

class TestIngestFemaPa:
    def test_empty_df_returns_empty_list(self):
        rows = _ingest_fema_pa(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), _logger())
        assert rows == []

    def test_flow_type_is_federal_disaster_grant(self):
        df = pd.DataFrame([{
            "pw_number": "PW-001", "disaster_number": "DR-4339",
            "applicant_name": "Applicant X", "federal_share_obligated": "200000",
        }])
        rows = _ingest_fema_pa(df, pd.DataFrame(), pd.DataFrame(), _logger())
        assert rows[0]["flow_type"] == "federal_disaster_grant"

    def test_linkage_lookup_applied(self):
        df_v2 = pd.DataFrame([{
            "pw_number": "PW-001", "disaster_number": "DR-4339",
            "applicant_name": "Applicant X", "federal_share_obligated": "200000",
        }])
        df_linkage = pd.DataFrame([{
            "pw_number": "PW-001", "disaster_number": "DR-4339",
            "recipient_name": "Linked Vendor", "contract_id": "CTR001",
            "link_confidence": "high",
        }])
        rows = _ingest_fema_pa(df_v2, pd.DataFrame(), df_linkage, _logger())
        assert rows[0]["prime_vendor"] == "Linked Vendor"


# ---------------------------------------------------------------------------
# _ingest_cor3
# ---------------------------------------------------------------------------

class TestIngestCor3:
    def test_empty_df_returns_empty(self):
        assert _ingest_cor3(pd.DataFrame(), _logger()) == []

    def test_flow_type(self):
        df = pd.DataFrame([{"project_id": "P001", "applicant_name": "Muni",
                            "total_approved": "300000", "program": "FEMA_PA"}])
        rows = _ingest_cor3(df, _logger())
        assert rows[0]["flow_type"] == "pr_recovery_project"


# ---------------------------------------------------------------------------
# _ingest_pr_procurement
# ---------------------------------------------------------------------------

class TestIngestPrProcurement:
    def test_empty_dfs_return_empty(self):
        rows = _ingest_pr_procurement(pd.DataFrame(), pd.DataFrame(), _logger())
        assert rows == []

    def test_vendor_name_column_detected(self):
        df = pd.DataFrame([{"vendor_name": "PRASA Vendor", "contract_value": "50000"}])
        rows = _ingest_pr_procurement(df, pd.DataFrame(), _logger())
        assert rows[0]["prime_vendor"] == "PRASA Vendor"

    def test_flow_type_is_pr_procurement(self):
        df = pd.DataFrame([{"vendor_name": "V", "contract_value": "50000"}])
        rows = _ingest_pr_procurement(df, pd.DataFrame(), _logger())
        assert rows[0]["flow_type"] == "pr_procurement"


# ---------------------------------------------------------------------------
# run() integration
# ---------------------------------------------------------------------------

class TestRunIntegration:
    def test_no_inputs_writes_empty_parquet(self, tmp_path):
        result = run(root=tmp_path, force=True)
        assert result["status"] == "OK"
        assert result["rows"] == 0
        out = tmp_path / "data" / "normalized" / "financial_flows_master.parquet"
        assert out.exists()

    def test_output_has_flow_columns(self, tmp_path):
        run(root=tmp_path, force=True)
        out = tmp_path / "data" / "normalized" / "financial_flows_master.parquet"
        df = pq_read(out)
        for col in FLOW_COLUMNS:
            assert col in df.columns

    def test_flow_id_uniqueness_with_data(self, tmp_path):
        df_contracts = pd.DataFrame([
            {"recipient_name": "Corp A", "obligated_amount": "500000",
             "award_id": "AWD001", "source_dataset": "usaspending"},
            {"recipient_name": "Corp B", "obligated_amount": "300000",
             "award_id": "AWD002", "source_dataset": "usaspending"},
        ])
        _write_csv(tmp_path, "data/staging/processed/pr_contracts_master.csv", df_contracts)
        run(root=tmp_path, force=True)
        df = pq_read(tmp_path / "data" / "normalized" / "financial_flows_master.parquet")
        assert df["flow_id"].nunique() == len(df)

    def test_idempotency_force_false_returns_cached(self, tmp_path):
        run(root=tmp_path, force=True)
        result = run(root=tmp_path, force=False)
        assert result["status"] == "CACHED"

    def test_force_true_rebuilds(self, tmp_path):
        run(root=tmp_path, force=True)
        result = run(root=tmp_path, force=True)
        assert result["status"] == "OK"

    def test_contracts_ingested_in_output(self, tmp_path):
        df_contracts = pd.DataFrame([{
            "recipient_name": "Test Corp", "obligated_amount": "750000",
            "award_id": "AWD001", "source_dataset": "usaspending",
        }])
        _write_csv(tmp_path, "data/staging/processed/pr_contracts_master.csv", df_contracts)
        result = run(root=tmp_path, force=True)
        assert result["rows"] == 1

    def test_hud_data_increases_row_count(self, tmp_path):
        df_proj = pd.DataFrame([{
            "grant_number": "B-19-001", "grantee_name": "Grantee",
            "grant_amount": "5000000", "program_type": "CDBG-DR", "disaster_number": "DR-1",
        }])
        _write_parquet(tmp_path, "data/normalized/hud_drgr_projects.parquet", df_proj)
        result = run(root=tmp_path, force=True)
        assert result["rows"] >= 1
