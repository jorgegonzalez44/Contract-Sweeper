"""Tests for scripts/download_promesa_creditors.py."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_promesa_creditors").setLevel(logging.CRITICAL)

from scripts.download_promesa_creditors import PROMESA_COLUMNS, KNOWN_CREDITORS, _normalize_name


class TestPromesaColumns:
    def test_has_creditor_name(self):
        assert "creditor_name" in PROMESA_COLUMNS

    def test_has_bond_series(self):
        assert "bond_series" in PROMESA_COLUMNS

    def test_has_claim_amount(self):
        assert "claim_amount_original" in PROMESA_COLUMNS

    def test_has_source_doc(self):
        assert "source_doc" in PROMESA_COLUMNS


class TestKnownCreditors:
    def test_non_empty(self):
        assert len(KNOWN_CREDITORS) > 0

    def test_all_have_creditor_name(self):
        for c in KNOWN_CREDITORS:
            assert "creditor_name" in c
            assert c["creditor_name"]

    def test_all_have_bond_series(self):
        for c in KNOWN_CREDITORS:
            assert "bond_series" in c


class TestNormalizeName:
    def test_uppercases(self):
        result = _normalize_name("Aurelius Capital")
        assert result == result.upper()

    def test_none_returns_empty(self):
        assert _normalize_name(None) == ""

    def test_strips_lp_suffix(self):
        result = _normalize_name("Aurelius Capital Management LP")
        assert "LP" not in result


class TestRunWithKnownData:
    def test_run_returns_rows(self, tmp_path):
        """run() always has KNOWN_CREDITORS as fallback."""
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        from unittest.mock import patch
        with patch("scripts.download_promesa_creditors._try_prime_clerk", return_value=None):
            from scripts.download_promesa_creditors import run
            result = run(root=tmp_path)
        assert result["rows"] > 0

    def test_cached_when_output_exists(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_promesa_creditors.csv"
        out.write_text("creditor_name\nAurelius Capital\n")
        from scripts.download_promesa_creditors import _run
        result = _run(root=tmp_path, force=False)
        assert result["rows"] >= 1
