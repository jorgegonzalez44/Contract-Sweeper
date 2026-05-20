"""Tests for scripts/download_medicaid_fmap.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_medicaid_fmap").setLevel(logging.CRITICAL)

from scripts.download_medicaid_fmap import MEDICAID_COLUMNS, run


class TestMedicaidColumns:
    def test_has_fiscal_year(self):
        assert "fiscal_year" in MEDICAID_COLUMNS

    def test_has_federal_share(self):
        assert "federal_share" in MEDICAID_COLUMNS

    def test_has_fmap_rate(self):
        assert "fmap_rate" in MEDICAID_COLUMNS


class TestRunCaching:
    def test_existing_output_skips(self, tmp_path):
        out_dir = tmp_path / "data" / "staging" / "processed"
        out_dir.mkdir(parents=True)
        out = out_dir / "pr_medicaid_fmap.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path, force=False)
        assert result.get("status") == "CACHED"

    def test_result_has_status(self, tmp_path):
        out_dir = tmp_path / "data" / "staging" / "processed"
        out_dir.mkdir(parents=True)
        out = out_dir / "pr_medicaid_fmap.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path, force=False)
        assert "status" in result

    def test_run_mocked_no_data(self, tmp_path):
        out_dir = tmp_path / "data" / "staging" / "processed"
        out_dir.mkdir(parents=True)
        with patch("scripts.download_medicaid_fmap._get", return_value=None), \
             patch("scripts.download_medicaid_fmap._session", return_value=MagicMock()):
            result = run(root=tmp_path, force=True)
        assert "status" in result
