"""Tests for scripts/download_slfrf.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_slfrf").setLevel(logging.CRITICAL)

from scripts.download_slfrf import MASTER_COLUMNS, _derive_fiscal_year, _file_has_data


class TestDeriveFiscalYear:
    def test_october_advances(self):
        assert _derive_fiscal_year("2021-10-01") == "2022"

    def test_september_same(self):
        assert _derive_fiscal_year("2021-09-30") == "2021"

    def test_none_empty(self):
        assert _derive_fiscal_year(None) == ""

    def test_invalid_empty(self):
        assert _derive_fiscal_year("bad") == ""


class TestFileHasData:
    def test_missing_false(self, tmp_path):
        assert _file_has_data(tmp_path / "x.csv") is False

    def test_header_only_false(self, tmp_path):
        p = tmp_path / "h.csv"
        p.write_text("col\n")
        assert _file_has_data(p) is False

    def test_with_data_true(self, tmp_path):
        p = tmp_path / "d.csv"
        p.write_text("col\nrow\n")
        assert _file_has_data(p) is True


class TestMasterColumns:
    def test_has_award_id(self):
        assert "award_id" in MASTER_COLUMNS

    def test_has_source_dataset(self):
        assert "source_dataset" in MASTER_COLUMNS

    def test_has_fiscal_year(self):
        assert "fiscal_year" in MASTER_COLUMNS


class TestRunCaching:
    def test_run_with_mocked_paginate(self, tmp_path):
        (tmp_path / "data" / "staging" / "raw" / "slfrf").mkdir(parents=True)
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        with patch("scripts.download_slfrf._paginate", return_value=[]), \
             patch("scripts.download_slfrf._session", return_value=MagicMock()):
            from scripts.download_slfrf import _run
            result = _run(root=tmp_path, force=False)
        assert "rows" in result
