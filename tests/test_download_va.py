"""Tests for scripts/download_va.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_va").setLevel(logging.CRITICAL)

from scripts.download_va import VA_COLUMNS


class TestVaColumns:
    def test_has_fiscal_year(self):
        assert "fiscal_year" in VA_COLUMNS

    def test_has_source_doc(self):
        assert "source_doc" in VA_COLUMNS

    def test_non_empty(self):
        assert len(VA_COLUMNS) >= 4


class TestRunCaching:
    def test_cached_when_output_exists(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_va_benefits.csv"
        out.write_text("fiscal_year\n2022\n")
        from scripts.download_va import run
        result = run(root=tmp_path, force=False)
        assert result.get("status") == "CACHED"

    def test_result_has_rows_key(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_va_benefits.csv"
        out.write_text("fiscal_year\n2022\n")
        from scripts.download_va import run
        result = run(root=tmp_path, force=False)
        assert "rows" in result

    def test_empty_when_no_data(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        with patch("scripts.download_va._fetch_usaspending_va", return_value=[]), \
             patch("scripts.download_va._fetch_va_open_data", return_value=[]):
            from scripts.download_va import run
            result = run(root=tmp_path, force=True)
        assert result.get("status") == "EMPTY"
        assert result["rows"] == 0
