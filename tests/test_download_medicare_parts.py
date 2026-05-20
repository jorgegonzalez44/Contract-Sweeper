"""Tests for scripts/download_medicare_parts.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_medicare_parts").setLevel(logging.CRITICAL)

from scripts.download_medicare_parts import MEDICARE_PARTS_COLUMNS, run


class TestMedicareColumns:
    def test_required_columns_present(self):
        for col in ("calendar_year", "total_payments", "source_doc"):
            assert col in MEDICARE_PARTS_COLUMNS


class TestRunCaching:
    def test_cached_when_output_exists(self, tmp_path):
        out_dir = tmp_path / "data" / "staging" / "processed"
        out_dir.mkdir(parents=True)
        out = out_dir / "pr_medicare_parts.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path, force=False)
        assert result["status"] == "CACHED"

    def test_result_has_status(self, tmp_path):
        out_dir = tmp_path / "data" / "staging" / "processed"
        out_dir.mkdir(parents=True)
        out = out_dir / "pr_medicare_parts.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path, force=False)
        assert "status" in result

    def test_run_with_no_data_writes_empty(self, tmp_path):
        out_dir = tmp_path / "data" / "staging" / "processed"
        out_dir.mkdir(parents=True)
        with patch("scripts.download_medicare_parts._fetch_cms_catalog", return_value=[]), \
             patch("scripts.download_medicare_parts._fetch_resource", return_value=[]):
            result = run(root=tmp_path, force=True)
        assert "status" in result
