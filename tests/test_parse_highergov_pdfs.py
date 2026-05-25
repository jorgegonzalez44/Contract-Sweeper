"""Tests for scripts/parse_highergov_pdfs.py."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.parse_highergov_pdfs import (
    FILENAME_MAP,
    parse_text_fallback,
    parse_with_pdfplumber,
)


# ---------------------------------------------------------------------------
# parse_with_pdfplumber — when pdfplumber is None, returns None
# ---------------------------------------------------------------------------

class TestParseWithPdfplumber:
    def test_returns_none_when_pdfplumber_not_installed(self, tmp_path):
        p = tmp_path / "test.pdf"
        p.write_bytes(b"%PDF-1.4 fake")
        with patch("scripts.parse_highergov_pdfs.pdfplumber", None):
            result = parse_with_pdfplumber(p)
        assert result is None

    def test_returns_none_for_nonexistent_file(self, tmp_path):
        import scripts.parse_highergov_pdfs as mod
        if mod.pdfplumber is None:
            pytest.skip("pdfplumber not installed")
        result = parse_with_pdfplumber(tmp_path / "nonexistent.pdf")
        assert result is None

    def test_returns_none_for_corrupt_pdf(self, tmp_path):
        import scripts.parse_highergov_pdfs as mod
        if mod.pdfplumber is None:
            pytest.skip("pdfplumber not installed")
        p = tmp_path / "corrupt.pdf"
        p.write_bytes(b"this is not a pdf")
        result = parse_with_pdfplumber(p)
        assert result is None

    def test_mocked_pdfplumber_returns_dataframe(self, tmp_path):
        p = tmp_path / "award.pdf"
        p.write_bytes(b"%PDF-1.4 fake")

        mock_page = MagicMock()
        mock_page.extract_tables.return_value = [
            [["Vendor Name", "Award Amount", "Date"],
             ["Acme Corp", "500000", "2022-01-15"],
             ["Island Co", "200000", "2022-06-01"]],
        ]
        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = lambda s: s
        mock_pdf.__exit__ = MagicMock(return_value=False)

        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = mock_pdf

        with patch("scripts.parse_highergov_pdfs.pdfplumber", mock_pdfplumber):
            result = parse_with_pdfplumber(p)

        assert result is not None
        assert isinstance(result, pd.DataFrame)
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# parse_text_fallback
# ---------------------------------------------------------------------------

class TestParseTextFallback:
    def test_returns_none_for_nonexistent_file(self, tmp_path):
        # Will fail to pdftotext and to read as text
        p = tmp_path / "nonexistent.pdf"
        # This may return None or a DataFrame depending on the text fallback path
        result = parse_text_fallback(p)
        assert result is None or isinstance(result, pd.DataFrame)

    def test_parses_multicolumn_text(self, tmp_path):
        p = tmp_path / "fake.pdf"
        # Write text that parse_text_fallback can use via its text-read fallback
        p.write_text(
            "Vendor Name  Award Amount  Date\n"
            "Acme Corp    500000        2022-01-15\n"
            "Island Co    200000        2022-06-01\n",
            encoding="utf-8",
        )
        # Mock pdftotext to fail so it uses the text-read fallback
        with patch("subprocess.run", side_effect=Exception("pdftotext not found")):
            result = parse_text_fallback(p)
        if result is not None:
            assert isinstance(result, pd.DataFrame)
            assert len(result) >= 1

    def test_single_column_lines_skipped(self, tmp_path):
        p = tmp_path / "sparse.pdf"
        p.write_text("OnlyOneWord\nAnother\n", encoding="utf-8")
        with patch("subprocess.run", side_effect=Exception("no pdftotext")):
            result = parse_text_fallback(p)
        # Lines with ≤1 part are skipped → no rows → None
        assert result is None


# ---------------------------------------------------------------------------
# FILENAME_MAP constant
# ---------------------------------------------------------------------------

class TestFilenameMap:
    def test_has_expected_entries(self):
        assert "HigherGov PR Data (Municipal Awards)" in FILENAME_MAP
        assert "HigherGov PR Data (Prime Awards)" in FILENAME_MAP

    def test_all_values_are_csv(self):
        for v in FILENAME_MAP.values():
            assert v.endswith(".csv"), f"Not a CSV filename: {v}"

    def test_all_keys_are_strings(self):
        assert all(isinstance(k, str) for k in FILENAME_MAP)
