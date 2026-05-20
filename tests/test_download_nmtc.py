"""Tests for scripts/download_nmtc.py."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_nmtc").setLevel(logging.CRITICAL)

from scripts.download_nmtc import NMTC_COLUMNS, _normalize_name, run


class TestNormalizeName:
    def test_uppercases(self):
        assert _normalize_name("Island Corp") == _normalize_name("Island Corp").upper()

    def test_strips_suffix(self):
        result = _normalize_name("Caribbean LLC")
        assert "LLC" not in result

    def test_none_returns_empty(self):
        assert _normalize_name(None) == ""

    def test_empty_returns_empty(self):
        assert _normalize_name("") == ""


class TestNmtcColumns:
    def test_has_allocatee_name(self):
        assert "allocatee_name" in NMTC_COLUMNS

    def test_has_allocation_amount(self):
        assert "allocation_amount" in NMTC_COLUMNS


class TestRunCaching:
    def test_existing_output_skips(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_nmtc_allocations.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path)
        assert "rows" in result

    def test_result_has_rows_key(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_nmtc_allocations.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path)
        assert result["rows"] >= 1
