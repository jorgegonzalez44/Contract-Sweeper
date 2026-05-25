"""Tests for scripts/ingest_cabilderos.py."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingest_cabilderos import (
    CABILDEROS_COLUMNS,
    _map_col,
    _normalize_name,
    _parse_df,
    _run,
)


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------

class TestNormalizeName:
    def test_empty_string(self):
        assert _normalize_name("") == ""

    def test_none(self):
        assert _normalize_name(None) == ""

    def test_uppercase(self):
        assert _normalize_name("juan rodriguez") == "JUAN RODRIGUEZ"

    def test_strips_punctuation(self):
        assert _normalize_name("Acme, Corp.") == "ACME"

    def test_strips_trailing_inc(self):
        assert _normalize_name("Consulting Group Inc") == "CONSULTING GROUP"

    def test_strips_spanish_suffixes(self):
        # CSP and SE are in the suffix set
        assert _normalize_name("Empresa CSP") == "EMPRESA"

    def test_strips_multiple_suffixes(self):
        assert _normalize_name("Corp LLC") == ""


# ---------------------------------------------------------------------------
# _map_col
# ---------------------------------------------------------------------------

class TestMapCol:
    def test_exact_match(self):
        result = _map_col(["Cliente", "Honorarios"], ["Cliente"])
        assert result == "Cliente"

    def test_case_insensitive(self):
        result = _map_col(["cliente", "honorarios"], ["Cliente"])
        assert result == "cliente"

    def test_returns_none_no_match(self):
        result = _map_col(["foo", "bar"], ["Cliente", "Client Name"])
        assert result is None

    def test_returns_first_matching_candidate(self):
        result = _map_col(["Client Name", "Cliente"], ["Cliente", "Client Name"])
        assert result == "Cliente"


# ---------------------------------------------------------------------------
# _parse_df
# ---------------------------------------------------------------------------

import logging

def _logger():
    logger = logging.getLogger("test_cabilderos")
    logger.setLevel(logging.CRITICAL)
    return logger


class TestParseDf:
    def _raw(self, rows=None):
        cols = ["Nombre Cabildero", "Cliente", "Año", "Asunto", "Agencia", "Honorarios"]
        if rows is None:
            rows = [
                ["Maria Rodriguez", "Acme Corp PR", "2022", "Infrastructure", "Legislature", "5000"],
                ["Juan Perez LLC", "Tech Solutions Inc", "2022", "Telecom", "DTRH", "3000"],
            ]
        return pd.DataFrame(rows, columns=cols)

    def test_returns_cabilderos_columns(self):
        df = _parse_df(self._raw(), "test.csv", _logger())
        for col in CABILDEROS_COLUMNS:
            assert col in df.columns

    def test_lobbyist_normalized_populated(self):
        df = _parse_df(self._raw(), "test.csv", _logger())
        assert df["lobbyist_normalized"].iloc[0] != ""

    def test_client_normalized_populated(self):
        df = _parse_df(self._raw(), "test.csv", _logger())
        assert df["client_normalized"].iloc[0] != ""

    def test_source_file_set(self):
        df = _parse_df(self._raw(), "cabilderos_2022.csv", _logger())
        assert all(df["source_file"] == "cabilderos_2022.csv")

    def test_empty_client_rows_filtered(self):
        rows = [
            ["Maria Rodriguez", "", "2022", "", "", ""],
            ["Juan Perez", "Valid Client", "2022", "", "", ""],
        ]
        raw = pd.DataFrame(rows, columns=["Nombre Cabildero", "Cliente", "Año",
                                          "Asunto", "Agencia", "Honorarios"])
        df = _parse_df(raw, "test.csv", _logger())
        assert len(df) == 1
        assert df["client_name"].iloc[0] == "Valid Client"

    def test_empty_input_returns_empty_with_columns(self):
        raw = pd.DataFrame()
        df = _parse_df(raw, "empty.csv", _logger())
        assert len(df) == 0
        assert list(df.columns) == CABILDEROS_COLUMNS


# ---------------------------------------------------------------------------
# _run() integration
# ---------------------------------------------------------------------------

class TestRun:
    def test_no_files_returns_zero_rows(self, tmp_path):
        result = _run(root=tmp_path, force=True)
        assert result["rows"] == 0

    def test_no_files_writes_empty_csv(self, tmp_path):
        _run(root=tmp_path, force=True)
        out = tmp_path / "data" / "staging" / "processed" / "pr_cabilderos.csv"
        assert out.exists()
        df = pd.read_csv(out)
        assert len(df) == 0

    def test_with_fixture_produces_output(self, tmp_path):
        cab_dir = tmp_path / "data" / "raw" / "Cabilderos"
        cab_dir.mkdir(parents=True)
        pd.DataFrame([
            {"Nombre Cabildero": "Ana Lopez", "Cliente": "Island Corp",
             "Año": "2022", "Asunto": "Infrastructure", "Agencia": "OGP", "Honorarios": "4000"},
        ]).to_csv(cab_dir / "cabilderos_2022.csv", index=False)

        result = _run(root=tmp_path, force=True)
        assert result["rows"] >= 1

    def test_output_has_required_columns(self, tmp_path):
        cab_dir = tmp_path / "data" / "raw" / "Cabilderos"
        cab_dir.mkdir(parents=True)
        pd.DataFrame([
            {"Nombre Cabildero": "Pedro Martinez", "Cliente": "Tech PR Inc",
             "Año": "2023", "Asunto": "Technology", "Agencia": "PRITS", "Honorarios": "6000"},
        ]).to_csv(cab_dir / "cabilderos_2023.csv", index=False)

        _run(root=tmp_path, force=True)
        out = pd.read_csv(tmp_path / "data" / "staging" / "processed" / "pr_cabilderos.csv")
        for col in ["lobbyist_name", "client_name", "source_file", "lobbyist_normalized"]:
            assert col in out.columns

    def test_returns_dict(self, tmp_path):
        result = _run(root=tmp_path, force=True)
        assert isinstance(result, dict)
        assert "rows" in result
        assert "path" in result
