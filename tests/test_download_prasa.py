"""Tests for scripts/download_prasa.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_prasa").setLevel(logging.CRITICAL)

from scripts.download_prasa import PRASA_COLUMNS, _map_col, run


class TestMapCol:
    def test_exact_match(self):
        assert _map_col(["Vendor Name", "Amount"], ["Vendor Name"]) == "Vendor Name"

    def test_case_insensitive(self):
        assert _map_col(["vendor name"], ["Vendor Name"]) == "vendor name"

    def test_returns_none_when_not_found(self):
        assert _map_col(["foo", "bar"], ["Vendor Name"]) is None

    def test_first_candidate_wins(self):
        result = _map_col(["Amount", "Value"], ["Amount", "Value"])
        assert result == "Amount"


class TestPrasaColumns:
    def test_has_vendor_name(self):
        assert "vendor_name" in PRASA_COLUMNS

    def test_has_contract_value(self):
        assert "contract_value" in PRASA_COLUMNS

    def test_has_source_file(self):
        assert "source_file" in PRASA_COLUMNS


class TestRunCaching:
    def test_existing_output_skips(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_prasa_contracts.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path, force=False)
        assert result.get("status") == "CACHED"

    def test_result_has_status(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_prasa_contracts.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path, force=False)
        assert "status" in result
