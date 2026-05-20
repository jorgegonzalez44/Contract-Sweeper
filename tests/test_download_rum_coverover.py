"""Tests for scripts/download_rum_coverover.py."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_rum_coverover").setLevel(logging.CRITICAL)

from scripts.download_rum_coverover import RUM_COLUMNS


class TestRumColumns:
    def test_has_fiscal_year(self):
        assert "fiscal_year" in RUM_COLUMNS

    def test_has_coverover_amount(self):
        assert "coverover_amount_pr" in RUM_COLUMNS

    def test_has_source_doc(self):
        assert "source_doc" in RUM_COLUMNS


class TestRunWithKnownData:
    def test_run_returns_rows(self, tmp_path):
        """run() falls back to KNOWN_COVEROVER so always returns > 0 rows."""
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        from unittest.mock import patch
        with patch("scripts.download_rum_coverover._try_treasury_api", return_value=[]):
            from scripts.download_rum_coverover import run
            result = run(root=tmp_path)
        assert result["rows"] > 0

    def test_run_result_has_path(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        from unittest.mock import patch
        with patch("scripts.download_rum_coverover._try_treasury_api", return_value=[]):
            from scripts.download_rum_coverover import run
            result = run(root=tmp_path)
        assert "path" in result

    def test_cached_when_output_exists(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_rum_coverover.csv"
        out.write_text("fiscal_year\n2022\n")
        from scripts.download_rum_coverover import _run
        result = _run(root=tmp_path, force=False)
        assert result["rows"] >= 1
