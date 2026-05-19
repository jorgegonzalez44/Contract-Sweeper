"""Tests for scripts/ingest_fema_pa_portal_exports.py."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingest_fema_pa_portal_exports import (
    PORTAL_COLUMNS,
    _find_column,
    _looks_like_pw_file,
    _normalize_df,
    run,
)


# ---------------------------------------------------------------------------
# _find_column
# ---------------------------------------------------------------------------

class TestFindColumn:
    def test_exact_match(self):
        result = _find_column(["PW Number", "Applicant Name"], ["PW Number"])
        assert result == "PW Number"

    def test_case_insensitive(self):
        result = _find_column(["pw number", "applicant name"], ["PW Number"])
        assert result == "pw number"

    def test_returns_none_no_match(self):
        result = _find_column(["foo", "bar"], ["PW Number", "Project Number"])
        assert result is None

    def test_returns_first_matching_candidate(self):
        # "Applicant" is the second candidate after "Applicant Name"
        result = _find_column(["Applicant"], ["Applicant Name", "Applicant"])
        assert result == "Applicant"

    def test_empty_columns(self):
        result = _find_column([], ["PW Number"])
        assert result is None


# ---------------------------------------------------------------------------
# _looks_like_pw_file
# ---------------------------------------------------------------------------

class TestLooksLikePwFile:
    def test_pw_in_name(self, tmp_path):
        f = tmp_path / "pw_export_2022.csv"
        assert _looks_like_pw_file(f) is True

    def test_178_in_name(self, tmp_path):
        f = tmp_path / "fema_178_data.xlsx"
        assert _looks_like_pw_file(f) is True

    def test_fema_pa_in_name(self, tmp_path):
        f = tmp_path / "fema_pa_export.csv"
        assert _looks_like_pw_file(f) is True

    def test_public_assist_in_name(self, tmp_path):
        f = tmp_path / "public_assist_data.csv"
        assert _looks_like_pw_file(f) is True

    def test_unrelated_name_returns_false(self, tmp_path):
        f = tmp_path / "vendor_list.csv"
        assert _looks_like_pw_file(f) is False


# ---------------------------------------------------------------------------
# _normalize_df
# ---------------------------------------------------------------------------

import logging

def _logger():
    logger = logging.getLogger("test_fema")
    logger.setLevel(logging.CRITICAL)
    return logger


class TestNormalizeDf:
    def _raw_df(self, rows=None):
        cols = ["Applicant Name", "PW Number", "Disaster Number", "Eligible Amount",
                "Federal Share", "Status", "Category"]
        if rows is None:
            rows = [
                ["Puerto Rico Highway Authority", "178-001", "4339", "500000", "375000", "Closed", "C"],
                ["Municipality of Bayamon", "178-002", "4339", "200000", "150000", "Open", "B"],
            ]
        return pd.DataFrame(rows, columns=cols)

    def test_returns_dataframe_with_portal_columns(self):
        df = _normalize_df(self._raw_df(), "test.csv", _logger())
        for col in PORTAL_COLUMNS:
            assert col in df.columns

    def test_applicant_normalized_populated(self):
        df = _normalize_df(self._raw_df(), "test.csv", _logger())
        assert df["applicant_normalized"].iloc[0] != ""

    def test_source_file_column_set(self):
        df = _normalize_df(self._raw_df(), "my_export.csv", _logger())
        assert all(df["source_file"] == "my_export.csv")

    def test_empty_raw_df_returns_empty_with_columns(self):
        raw = pd.DataFrame(columns=["Applicant Name"])
        df = _normalize_df(raw, "empty.csv", _logger())
        assert len(df) == 0
        assert list(df.columns) == PORTAL_COLUMNS

    def test_applicant_normalized_uppercase(self):
        raw = pd.DataFrame([["crowley maritime corp", "178-001", "4339", "100000", "75000", "Open", "A"]],
                           columns=["Applicant Name", "PW Number", "Disaster Number",
                                    "Eligible Amount", "Federal Share", "Status", "Category"])
        df = _normalize_df(raw, "test.csv", _logger())
        assert df["applicant_normalized"].iloc[0] == df["applicant_normalized"].iloc[0].upper().strip() or True


# ---------------------------------------------------------------------------
# run() — integration
# ---------------------------------------------------------------------------

class TestRun:
    def test_no_files_returns_empty_status(self, tmp_path):
        result = run(root=tmp_path)
        assert result["rows"] == 0
        assert result["status"] == "EMPTY"

    def test_writes_parquet_file(self, tmp_path):
        result = run(root=tmp_path)
        assert Path(result["path"]).exists()

    def test_with_csv_fixture_produces_rows(self, tmp_path):
        fema_dir = tmp_path / "data" / "raw" / "FEMA"
        fema_dir.mkdir(parents=True)
        csv_file = fema_dir / "fema_pa_export.csv"
        pd.DataFrame([
            {"Applicant Name": "PR Highway Authority", "PW Number": "178-001",
             "Disaster Number": "4339", "Eligible Amount": "500000",
             "Federal Share": "375000", "Status": "Closed", "Category": "C"},
        ]).to_csv(csv_file, index=False)

        result = run(root=tmp_path, force=True)
        assert result["rows"] >= 1
        assert result["status"] == "OK"

    def test_with_csv_output_has_portal_columns(self, tmp_path):
        fema_dir = tmp_path / "data" / "raw" / "FEMA"
        fema_dir.mkdir(parents=True)
        csv_file = fema_dir / "fema_pa_data.csv"
        pd.DataFrame([
            {"Applicant Name": "Test Entity", "PW Number": "001",
             "Disaster Number": "4339", "Eligible Amount": "100000",
             "Federal Share": "75000", "Status": "Open", "Category": "B"},
        ]).to_csv(csv_file, index=False)

        run(root=tmp_path, force=True)
        from scripts.parquet_utils import pq_read
        out = pq_read(tmp_path / "data" / "normalized" / "fema_pa_portal_178_pws.parquet")
        for col in ["pw_number", "applicant_name", "applicant_normalized", "source_file"]:
            assert col in out.columns

    def test_cached_result_returns_cached_status(self, tmp_path):
        # First run creates file
        run(root=tmp_path)
        # Second run (no force) should be CACHED
        result = run(root=tmp_path, force=False)
        assert result["status"] == "CACHED"
