"""Tests for scripts/download_research.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_research").setLevel(logging.CRITICAL)

from scripts.download_research import MASTER_COLUMNS, run


class TestMasterColumns:
    def test_has_award_id(self):
        assert "award_id" in MASTER_COLUMNS

    def test_has_pi_name(self):
        assert "pi_name" in MASTER_COLUMNS

    def test_has_source_dataset(self):
        assert "source_dataset" in MASTER_COLUMNS

    def test_has_fiscal_year(self):
        assert "fiscal_year" in MASTER_COLUMNS


class TestRunWithMocks:
    def _empty_df(self):
        return pd.DataFrame(columns=MASTER_COLUMNS)

    def test_returns_dict_with_expected_keys(self, tmp_path):
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        (tmp_path / "data" / "staging" / "raw" / "research").mkdir(parents=True)
        with patch("scripts.download_research.download_nih", return_value=self._empty_df()), \
             patch("scripts.download_research.download_nsf", return_value=self._empty_df()):
            result = run(root=tmp_path)
        for key in ("nih_rows", "nsf_rows", "total_rows", "master_path"):
            assert key in result

    def test_result_nih_rows_is_int(self, tmp_path):
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        (tmp_path / "data" / "staging" / "raw" / "research").mkdir(parents=True)
        with patch("scripts.download_research.download_nih", return_value=self._empty_df()), \
             patch("scripts.download_research.download_nsf", return_value=self._empty_df()):
            result = run(root=tmp_path)
        assert isinstance(result["nih_rows"], int)
        assert isinstance(result["nsf_rows"], int)
