"""Tests for scripts/download_prepa_contracts.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_prepa_contracts").setLevel(logging.CRITICAL)

from scripts.download_prepa_contracts import PREPA_COLUMNS, KNOWN_CONTRACTS, run


class TestPrepaColumns:
    def test_has_vendor_name(self):
        assert "vendor_name" in PREPA_COLUMNS

    def test_has_contract_value(self):
        assert "contract_value" in PREPA_COLUMNS

    def test_has_source_doc(self):
        assert "source_doc" in PREPA_COLUMNS


class TestKnownContracts:
    def test_non_empty(self):
        assert len(KNOWN_CONTRACTS) > 0

    def test_luma_contract_present(self):
        contract_ids = {c["contract_id"] for c in KNOWN_CONTRACTS}
        assert "LUMA-OM-2021" in contract_ids

    def test_all_have_vendor_name(self):
        for c in KNOWN_CONTRACTS:
            assert "vendor_name" in c

    def test_all_have_contract_value(self):
        for c in KNOWN_CONTRACTS:
            assert "contract_value" in c
            assert c["contract_value"] > 0


class TestRunCaching:
    def test_existing_output_skips(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_prepa_contracts.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path)
        assert "rows" in result

    def test_result_has_rows(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_prepa_contracts.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path)
        assert result["rows"] >= 1
