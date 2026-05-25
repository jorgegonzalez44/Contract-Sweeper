"""Tests for scripts/download_ssa.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_ssa").setLevel(logging.CRITICAL)

from scripts.download_ssa import SSA_COLUMNS


class TestSsaColumns:
    def test_has_calendar_year(self):
        assert "calendar_year" in SSA_COLUMNS

    def test_has_total_payments(self):
        assert "total_payments" in SSA_COLUMNS

    def test_has_program_type(self):
        assert "program_type" in SSA_COLUMNS

    def test_has_source_doc(self):
        assert "source_doc" in SSA_COLUMNS


class TestRunCaching:
    def test_cached_when_output_exists(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_ssa_benefits.csv"
        out.write_text("calendar_year\n2022\n")
        from scripts.download_ssa import run
        result = run(root=tmp_path, force=False)
        assert result.get("status") == "CACHED"

    def test_result_has_rows(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_ssa_benefits.csv"
        out.write_text("calendar_year\n2022\n")
        from scripts.download_ssa import run
        result = run(root=tmp_path, force=False)
        assert "rows" in result

    def test_empty_when_no_data(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        with patch("scripts.download_ssa._fetch_ssa_open_data", return_value=[]), \
             patch("scripts.download_ssa._fetch_ssa_state_tables", return_value=[]):
            from scripts.download_ssa import run
            result = run(root=tmp_path, force=True)
        assert result.get("status") == "EMPTY"
        assert result["rows"] == 0
