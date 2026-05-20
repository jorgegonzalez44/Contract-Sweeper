"""Tests for scripts/download_pr_pensions.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_pr_pensions").setLevel(logging.CRITICAL)

from scripts.download_pr_pensions import PENSION_COLUMNS, run


class TestPensionColumns:
    def test_has_fiscal_year(self):
        assert "fiscal_year" in PENSION_COLUMNS

    def test_has_funded_ratio(self):
        assert "funded_ratio" in PENSION_COLUMNS

    def test_has_fund_name(self):
        assert "fund_name" in PENSION_COLUMNS

    def test_has_source_doc(self):
        assert "source_doc" in PENSION_COLUMNS


class TestRunCaching:
    def test_existing_output_returns_cached(self, tmp_path):
        out_dir = tmp_path / "data" / "staging" / "processed"
        out_dir.mkdir(parents=True)
        out = out_dir / "pr_pension_funds.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path, force=False)
        assert result["status"] == "CACHED"

    def test_cached_rows_correct(self, tmp_path):
        out_dir = tmp_path / "data" / "staging" / "processed"
        out_dir.mkdir(parents=True)
        out = out_dir / "pr_pension_funds.csv"
        out.write_text("fiscal_year,fund_name\n2021,ERS\n2022,TRS\n")
        result = run(root=tmp_path, force=False)
        assert result["rows"] == 2

    def test_result_has_status_key(self, tmp_path):
        out_dir = tmp_path / "data" / "staging" / "processed"
        out_dir.mkdir(parents=True)
        out = out_dir / "pr_pension_funds.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path, force=False)
        assert "status" in result
