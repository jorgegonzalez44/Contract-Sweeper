"""Tests for scripts/download_cabilderos.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_cabilderos").setLevel(logging.CRITICAL)

from scripts.download_cabilderos import CABILDEROS_COLUMNS, _map_col


class TestCabilderoColumns:
    def test_has_lobbyist_name(self):
        assert "lobbyist_name" in CABILDEROS_COLUMNS

    def test_has_client_name(self):
        assert "client_name" in CABILDEROS_COLUMNS

    def test_has_source_file(self):
        assert "source_file" in CABILDEROS_COLUMNS


class TestMapCol:
    def test_exact_match(self):
        result = _map_col(["Nombre del Cabildero", "Other"], ["Nombre del Cabildero"])
        assert result == "Nombre del Cabildero"

    def test_case_insensitive(self):
        result = _map_col(["nombre del cabildero"], ["Nombre del Cabildero"])
        assert result == "nombre del cabildero"

    def test_returns_none_when_not_found(self):
        result = _map_col(["foo", "bar"], ["Nombre del Cabildero"])
        assert result is None


class TestRunCaching:
    def test_cached_when_output_exists(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_cabilderos.csv"
        out.write_text("lobbyist_name\nJose Rodriguez\n")
        from scripts.download_cabilderos import run
        result = run(root=tmp_path, force=False)
        assert result.get("status") == "CACHED"

    def test_result_has_rows_key(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_cabilderos.csv"
        out.write_text("lobbyist_name\nJose Rodriguez\n")
        from scripts.download_cabilderos import run
        result = run(root=tmp_path, force=False)
        assert "rows" in result
