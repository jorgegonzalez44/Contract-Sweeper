"""Tests for scripts/download_lihtc.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_lihtc").setLevel(logging.CRITICAL)

from scripts.download_lihtc import LIHTC_COLUMNS, _normalize_name


class TestLihtcColumns:
    def test_has_hud_id(self):
        assert "hud_id" in LIHTC_COLUMNS

    def test_has_proj_nm(self):
        assert "proj_nm" in LIHTC_COLUMNS

    def test_has_normalized_owner(self):
        assert "proj_own_nm_normalized" in LIHTC_COLUMNS


class TestNormalizeName:
    def test_uppercases(self):
        result = _normalize_name("Caribbean Corp")
        assert result == result.upper()

    def test_strips_llc(self):
        result = _normalize_name("Island Developers LLC")
        assert "LLC" not in result

    def test_none_returns_empty(self):
        assert _normalize_name(None) == ""

    def test_empty_returns_empty(self):
        assert _normalize_name("") == ""


class TestRunCaching:
    def test_existing_output_skips(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_lihtc_projects.csv"
        out.write_text("hud_id\nH001\n")
        with patch("scripts.download_lihtc._download_zip", return_value=None):
            from scripts.download_lihtc import run
            result = run(root=tmp_path)
        assert "rows" in result

    def test_result_has_rows(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_lihtc_projects.csv"
        out.write_text("hud_id\nH001\n")
        with patch("scripts.download_lihtc._download_zip", return_value=None):
            from scripts.download_lihtc import run
            result = run(root=tmp_path)
        assert result["rows"] >= 1
