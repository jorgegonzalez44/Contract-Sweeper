"""Tests for scripts/ingest_active_contractors.py."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingest_active_contractors import (
    CONTRACTOR_COLUMNS,
    _map_col,
    _normalize_name,
    _parse_df,
    _run,
)


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------

class TestNormalizeName:
    def test_empty(self):
        assert _normalize_name("") == ""

    def test_none(self):
        assert _normalize_name(None) == ""

    def test_uppercase(self):
        assert _normalize_name("constructora ponce") == "CONSTRUCTORA PONCE"

    def test_strips_inc(self):
        assert _normalize_name("Tech Services Inc") == "TECH SERVICES"

    def test_strips_csp(self):
        assert _normalize_name("Servicios CSP") == "SERVICIOS"

    def test_strips_punctuation(self):
        assert _normalize_name("Corp. Solutions, Ltd.") == "CORP SOLUTIONS"


# ---------------------------------------------------------------------------
# _map_col
# ---------------------------------------------------------------------------

class TestMapCol:
    def test_exact_match(self):
        assert _map_col(["Nombre", "ID"], ["Nombre"]) == "Nombre"

    def test_case_insensitive(self):
        assert _map_col(["nombre", "id"], ["Nombre"]) == "nombre"

    def test_returns_none(self):
        assert _map_col(["unrelated", "col"], ["Nombre", "Name"]) is None

    def test_english_column_matched(self):
        assert _map_col(["Vendor Name", "ID"], ["Nombre", "Name", "Vendor Name"]) == "Vendor Name"


# ---------------------------------------------------------------------------
# _parse_df
# ---------------------------------------------------------------------------

import logging

def _logger():
    logger = logging.getLogger("test_active_contractors")
    logger.setLevel(logging.CRITICAL)
    return logger


class TestParseDf:
    def _raw(self, rows=None):
        cols = ["Nombre", "ID", "Fecha de Registro", "Tipo", "Municipio", "Estado"]
        if rows is None:
            rows = [
                ["Constructora ABC LLC", "001", "2022-01-15", "General", "San Juan", "Active"],
                ["Tech Solutions Inc", "002", "2022-03-10", "IT", "Ponce", "Active"],
            ]
        return pd.DataFrame(rows, columns=cols)

    def test_returns_contractor_columns(self):
        df = _parse_df(self._raw(), "test.csv", _logger())
        for col in CONTRACTOR_COLUMNS:
            assert col in df.columns

    def test_entity_normalized_populated(self):
        df = _parse_df(self._raw(), "test.csv", _logger())
        assert df["entity_normalized"].iloc[0] != ""

    def test_source_file_set(self):
        df = _parse_df(self._raw(), "contractors_2022.csv", _logger())
        assert all(df["source_file"] == "contractors_2022.csv")

    def test_empty_entity_rows_filtered(self):
        raw = pd.DataFrame([
            {"Nombre": "", "ID": "001"},
            {"Nombre": "Valid Corp", "ID": "002"},
        ])
        df = _parse_df(raw, "test.csv", _logger())
        assert len(df) == 1

    def test_empty_input_returns_empty(self):
        df = _parse_df(pd.DataFrame(), "empty.csv", _logger())
        assert len(df) == 0
        assert list(df.columns) == CONTRACTOR_COLUMNS

    def test_english_column_names_work(self):
        raw = pd.DataFrame([
            {"Name": "Island Corp Inc", "ID": "003",
             "Municipality": "Bayamon", "Status": "Active"},
        ])
        df = _parse_df(raw, "english.csv", _logger())
        assert "entity_name" in df.columns
        assert len(df) == 1


# ---------------------------------------------------------------------------
# _run() integration
# ---------------------------------------------------------------------------

class TestRunIntegration:
    def test_no_files_returns_zero_rows(self, tmp_path):
        result = _run(root=tmp_path, force=True)
        assert result["rows"] == 0

    def test_no_files_writes_csv_with_headers(self, tmp_path):
        _run(root=tmp_path, force=True)
        out = tmp_path / "data" / "staging" / "processed" / "pr_active_contractors.csv"
        assert out.exists()
        df = pd.read_csv(out)
        for col in CONTRACTOR_COLUMNS:
            assert col in df.columns

    def test_with_fixture_produces_rows(self, tmp_path):
        folder = tmp_path / "data" / "raw" / "Active Contractor Listing"
        folder.mkdir(parents=True)
        pd.DataFrame([
            {"Nombre": "Island Builders Corp", "ID": "PR-001",
             "Fecha de Registro": "2022-01-01", "Tipo": "Construction",
             "Municipio": "Mayaguez", "Estado": "Active"},
        ]).to_csv(folder / "contractors.csv", index=False)
        result = _run(root=tmp_path, force=True)
        assert result["rows"] >= 1

    def test_returns_dict_with_path(self, tmp_path):
        result = _run(root=tmp_path, force=True)
        assert "rows" in result
        assert "path" in result
