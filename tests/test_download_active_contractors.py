"""Tests for scripts/download_active_contractors.py."""
import logging
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_active_contractors").setLevel(logging.CRITICAL)

from scripts.download_active_contractors import CONTRACTOR_COLUMNS, _map_col, _normalize_df


class TestContractorColumns:
    def test_has_entity_name(self):
        assert "entity_name" in CONTRACTOR_COLUMNS

    def test_has_status(self):
        assert "status" in CONTRACTOR_COLUMNS

    def test_has_source_file(self):
        assert "source_file" in CONTRACTOR_COLUMNS


class TestMapCol:
    def test_exact_match(self):
        result = _map_col(["Nombre", "Other"], ["Nombre"])
        assert result == "Nombre"

    def test_case_insensitive(self):
        result = _map_col(["nombre"], ["Nombre"])
        assert result == "nombre"

    def test_returns_none_when_not_found(self):
        result = _map_col(["xyz"], ["Nombre"])
        assert result is None


class TestNormalizeDf:
    def test_output_has_canonical_columns(self):
        df = pd.DataFrame({"Nombre": ["Acme Corp"], "Estado": ["Activo"]})
        out = _normalize_df(df, "test.csv")
        assert "source_file" in out.columns
        assert out.iloc[0]["source_file"] == "test.csv"

    def test_entity_normalized_uppercased(self):
        df = pd.DataFrame({"Nombre": ["Island Builders Inc"], "Estado": ["Active"]})
        out = _normalize_df(df, "test.csv")
        if "entity_normalized" in out.columns:
            assert out.iloc[0]["entity_normalized"] == out.iloc[0]["entity_normalized"].upper()


class TestRunCaching:
    def test_cached_when_output_exists(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_active_contractors.csv"
        out.write_text("entity_name\nAcme Corp\n")
        from scripts.download_active_contractors import run
        result = run(root=tmp_path, force=False)
        assert result.get("status") == "CACHED"

    def test_result_has_rows_key(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_active_contractors.csv"
        out.write_text("entity_name\nAcme Corp\n")
        from scripts.download_active_contractors import run
        result = run(root=tmp_path, force=False)
        assert "rows" in result
