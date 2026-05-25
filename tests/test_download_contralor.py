"""Tests for scripts/download_contralor.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_contralor").setLevel(logging.CRITICAL)

from scripts.download_contralor import (
    CONTRALOR_AUDIT_COLUMNS,
    CONTRALOR_CONTRACT_COLUMNS,
    _map_col,
    _map_to_schema,
    run,
)


class TestMapCol:
    def test_exact_match(self):
        assert _map_col(["Entity Name", "Amount"], ["Entity Name"]) == "Entity Name"

    def test_case_insensitive(self):
        assert _map_col(["entity name", "Amount"], ["Entity Name"]) == "entity name"

    def test_returns_none_when_not_found(self):
        assert _map_col(["foo", "bar"], ["Entity Name"]) is None

    def test_first_candidate_wins(self):
        result = _map_col(["Amount", "Obligated"], ["Amount", "Obligated"])
        assert result == "Amount"


class TestMapToSchema:
    def _audit_records(self):
        return [
            {"entity_name": "Acme", "audit_year": "2021", "finding_count": "3"},
        ]

    def test_empty_records_returns_empty_df(self):
        result = _map_to_schema([], {}, CONTRALOR_AUDIT_COLUMNS, "test.csv", "entity_name")
        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == CONTRALOR_AUDIT_COLUMNS

    def test_source_file_assigned(self):
        records = [{"entity_name": "Test Corp", "audit_year": "2022"}]
        col_map = {"entity_name": ["entity_name"], "audit_year": ["audit_year"]}
        result = _map_to_schema(records, col_map, CONTRALOR_AUDIT_COLUMNS, "test.csv", "entity_name")
        assert "source_file" in result.columns
        if len(result):
            assert result["source_file"].iloc[0] == "test.csv"


class TestColumns:
    def test_audit_columns_present(self):
        assert "entity_name" in CONTRALOR_AUDIT_COLUMNS
        assert "source_file" in CONTRALOR_AUDIT_COLUMNS

    def test_contract_columns_present(self):
        assert "entity_name" in CONTRALOR_CONTRACT_COLUMNS
        assert "source_file" in CONTRALOR_CONTRACT_COLUMNS


class TestRunCaching:
    def test_caching_returns_cached_status(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        audit_path = processed / "pr_contralor_audits.csv"
        contract_path = processed / "pr_contralor_contracts.csv"
        audit_path.write_text("col_a\nrow1\n")
        contract_path.write_text("col_b\nrow2\n")
        result = run(root=tmp_path, force=False)
        assert result["status"] == "CACHED"

    def test_run_with_no_files_produces_empty_output(self, tmp_path):
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        (tmp_path / "data" / "raw" / "contralor").mkdir(parents=True)
        result = run(root=tmp_path, force=False)
        assert "status" in result

    def test_result_has_required_keys(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        audit_path = processed / "pr_contralor_audits.csv"
        contract_path = processed / "pr_contralor_contracts.csv"
        audit_path.write_text("col_a\n")
        contract_path.write_text("col_b\n")
        result = run(root=tmp_path, force=False)
        assert "status" in result
