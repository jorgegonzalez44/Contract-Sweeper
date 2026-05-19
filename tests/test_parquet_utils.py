"""Tests for scripts/parquet_utils.py — pq_write, pq_read, CSV fallback."""

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.parquet_utils import pq_read, pq_write


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame({
        "name": ["Alice", "Bob", "Carol"],
        "amount": [1000.0, 2000.0, 3000.0],
        "year": [2020, 2021, 2022],
    })


# ---------------------------------------------------------------------------
# pq_write
# ---------------------------------------------------------------------------

class TestPqWrite:
    def test_returns_path_object(self, tmp_path):
        df = _sample_df()
        result = pq_write(df, tmp_path / "out.parquet")
        assert isinstance(result, Path)

    def test_written_file_exists_on_disk(self, tmp_path):
        df = _sample_df()
        out = pq_write(df, tmp_path / "out.parquet")
        assert out.exists()

    def test_creates_parent_directories(self, tmp_path):
        df = _sample_df()
        nested = tmp_path / "a" / "b" / "c" / "out.parquet"
        pq_write(df, nested)
        assert nested.exists() or nested.with_suffix(".csv").exists()

    def test_dataframe_roundtrips_correctly(self, tmp_path):
        df = _sample_df()
        out = pq_write(df, tmp_path / "out.parquet")
        df2 = pq_read(out)
        assert list(df2.columns) == list(df.columns)
        assert len(df2) == len(df)

    def test_row_values_preserved_after_roundtrip(self, tmp_path):
        df = _sample_df()
        out = pq_write(df, tmp_path / "data.parquet")
        df2 = pq_read(out)
        names = list(df2["name"].astype(str))
        assert "Alice" in names
        assert "Bob" in names
        assert "Carol" in names

    def test_empty_dataframe_written_without_error(self, tmp_path):
        df = pd.DataFrame(columns=["a", "b"])
        out = pq_write(df, tmp_path / "empty.parquet")
        assert out.exists()

    def test_csv_fallback_when_parquet_unavailable(self, tmp_path):
        df = _sample_df()
        path = tmp_path / "out.parquet"
        with patch("scripts.parquet_utils._PARQUET_OK", False):
            result = pq_write(df, path)
        assert result.suffix == ".csv"
        assert result.exists()

    def test_csv_fallback_content_correct(self, tmp_path):
        df = _sample_df()
        path = tmp_path / "fallback.parquet"
        with patch("scripts.parquet_utils._PARQUET_OK", False):
            result = pq_write(df, path)
        df2 = pd.read_csv(result)
        assert len(df2) == 3
        assert "name" in df2.columns


# ---------------------------------------------------------------------------
# pq_read
# ---------------------------------------------------------------------------

class TestPqRead:
    def test_returns_dataframe(self, tmp_path):
        df = _sample_df()
        out = pq_write(df, tmp_path / "data.parquet")
        result = pq_read(out)
        assert isinstance(result, pd.DataFrame)

    def test_returns_empty_df_for_missing_file(self, tmp_path):
        result = pq_read(tmp_path / "nonexistent.parquet")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_empty_df_for_missing_has_no_columns(self, tmp_path):
        result = pq_read(tmp_path / "ghost.parquet")
        assert result.empty

    def test_reads_csv_fallback_when_parquet_absent(self, tmp_path):
        df = _sample_df()
        csv_path = tmp_path / "data.csv"
        df.to_csv(csv_path, index=False)
        # pq_read with a .parquet path falls back to the .csv sibling
        result = pq_read(tmp_path / "data.parquet")
        assert len(result) == 3
        assert "name" in result.columns

    def test_columns_subset_filter(self, tmp_path):
        df = _sample_df()
        out = pq_write(df, tmp_path / "data.parquet")
        result = pq_read(out, columns=["name", "year"])
        assert "name" in result.columns
        assert "year" in result.columns
        assert "amount" not in result.columns

    def test_returns_empty_on_corrupt_file(self, tmp_path):
        bad = tmp_path / "corrupt.parquet"
        bad.write_bytes(b"not a parquet file")
        # Also remove any CSV sibling so both paths fail
        result = pq_read(bad)
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_roundtrip_preserves_row_count(self, tmp_path):
        df = pd.DataFrame({"x": range(100)})
        out = pq_write(df, tmp_path / "hundred.parquet")
        result = pq_read(out)
        assert len(result) == 100

    def test_csv_fallback_read_when_parquet_flag_off(self, tmp_path):
        df = _sample_df()
        csv_path = (tmp_path / "data.parquet").with_suffix(".csv")
        df.to_csv(csv_path, index=False)
        with patch("scripts.parquet_utils._PARQUET_OK", False):
            result = pq_read(tmp_path / "data.parquet")
        assert len(result) == 3
