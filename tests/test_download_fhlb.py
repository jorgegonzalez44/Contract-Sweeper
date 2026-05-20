"""Tests for scripts/download_fhlb.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_fhlb").setLevel(logging.CRITICAL)

from scripts.download_fhlb import FHLB_COLUMNS, _file_has_data, _normalize_name, run


class TestNormalizeName:
    def test_uppercase(self):
        assert _normalize_name("Banco Popular") == "BANCO POPULAR"

    def test_strips_corp_suffix(self):
        result = _normalize_name("First Bank Corp")
        assert "CORP" not in result

    def test_none_returns_empty(self):
        assert _normalize_name(None) == ""

    def test_empty_returns_empty(self):
        assert _normalize_name("") == ""

    def test_collapses_whitespace(self):
        assert "  " not in _normalize_name("Banco   Popular")


class TestFileHasData:
    def test_missing_false(self, tmp_path):
        assert _file_has_data(tmp_path / "missing.csv") is False

    def test_header_only_false(self, tmp_path):
        p = tmp_path / "h.csv"
        p.write_text("col\n")
        assert _file_has_data(p) is False

    def test_with_data_true(self, tmp_path):
        p = tmp_path / "d.csv"
        p.write_text("col\nrow\n")
        assert _file_has_data(p) is True


class TestFhlbColumns:
    def test_required_columns_present(self):
        for col in ("institution_name", "advances_outstanding", "source"):
            assert col in FHLB_COLUMNS


class TestRunCaching:
    def test_existing_output_returns_cached(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_fhlb_advances.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path)
        assert result["rows"] >= 1

    def test_result_has_expected_keys(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_fhlb_advances.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path)
        assert "rows" in result
        assert "errors" in result
