"""Tests for scripts/parquet_utils.py — parquet read/write with CSV fallback."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.parquet_utils as pq_mod
from scripts.parquet_utils import pq_read, pq_write


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_df() -> pd.DataFrame:
    return pd.DataFrame({
        "name": ["Alpha Corp", "Beta LLC", "Gamma Inc"],
        "amount": [100.0, 200.5, 300.0],
        "year": [2020, 2021, 2022],
    })


# ---------------------------------------------------------------------------
# pq_write
# ---------------------------------------------------------------------------

class TestPqWrite:
    def test_returns_path_that_exists(self, tmp_path):
        df = _sample_df()
        out = tmp_path / "test.parquet"
        result = pq_write(df, out)
        assert result.exists()

    def test_creates_parent_directories(self, tmp_path):
        df = _sample_df()
        out = tmp_path / "nested" / "deep" / "test.parquet"
        result = pq_write(df, out)
        assert result.exists()

    def test_written_file_is_nonempty(self, tmp_path):
        df = _sample_df()
        out = tmp_path / "test.parquet"
        result = pq_write(df, out)
        assert result.stat().st_size > 0

    def test_write_empty_dataframe(self, tmp_path):
        df = pd.DataFrame({"col_a": [], "col_b": []})
        out = tmp_path / "empty.parquet"
        result = pq_write(df, out)
        assert result.exists()

    def test_accepts_path_as_string(self, tmp_path):
        df = _sample_df()
        out = str(tmp_path / "str_path.parquet")
        result = pq_write(df, out)
        assert Path(result).exists()


# ---------------------------------------------------------------------------
# pq_read
# ---------------------------------------------------------------------------

class TestPqRead:
    def test_roundtrip_preserves_columns(self, tmp_path):
        df = _sample_df()
        out = tmp_path / "rt.parquet"
        pq_write(df, out)
        result = pq_read(out)
        assert list(result.columns) == list(df.columns)

    def test_roundtrip_preserves_row_count(self, tmp_path):
        df = _sample_df()
        out = tmp_path / "rt.parquet"
        pq_write(df, out)
        result = pq_read(out)
        assert len(result) == len(df)

    def test_roundtrip_preserves_values(self, tmp_path):
        df = _sample_df()
        out = tmp_path / "rt.parquet"
        pq_write(df, out)
        result = pq_read(out)
        assert result["name"].tolist() == df["name"].tolist()

    def test_missing_file_returns_empty_dataframe(self, tmp_path):
        out = tmp_path / "nonexistent.parquet"
        result = pq_read(out)
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_missing_file_does_not_raise(self, tmp_path):
        out = tmp_path / "does_not_exist.parquet"
        result = pq_read(out)  # must not raise
        assert isinstance(result, pd.DataFrame)

    def test_columns_subset_selection(self, tmp_path):
        df = _sample_df()
        out = tmp_path / "subset.parquet"
        pq_write(df, out)
        result = pq_read(out, columns=["name", "year"])
        assert list(result.columns) == ["name", "year"]
        assert "amount" not in result.columns


# ---------------------------------------------------------------------------
# CSV fallback path
# ---------------------------------------------------------------------------

class TestCsvFallback:
    def test_fallback_reads_csv_when_parquet_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pq_mod, "_PARQUET_OK", False)
        df = _sample_df()
        csv_path = tmp_path / "test.csv"
        df.to_csv(csv_path, index=False)
        result = pq_read(tmp_path / "test.parquet")  # parquet path, falls back to .csv
        assert len(result) == len(df)
        assert "name" in result.columns

    def test_fallback_write_creates_csv(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pq_mod, "_PARQUET_OK", False)
        df = _sample_df()
        out = tmp_path / "fallback.parquet"
        result = pq_write(df, out)
        assert result.suffix == ".csv"
        assert result.exists()

    def test_fallback_csv_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pq_mod, "_PARQUET_OK", False)
        df = _sample_df()
        out = tmp_path / "roundtrip.parquet"
        pq_write(df, out)
        result = pq_read(out)
        assert list(result.columns) == list(df.columns)
        assert len(result) == len(df)

    def test_fallback_missing_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pq_mod, "_PARQUET_OK", False)
        result = pq_read(tmp_path / "missing.parquet")
        assert isinstance(result, pd.DataFrame)
        assert result.empty
