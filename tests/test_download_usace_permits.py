"""Tests for scripts/download_usace_permits.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_usace_permits").setLevel(logging.CRITICAL)

from scripts.download_usace_permits import OUTPUT_COLUMNS, _filter_pr, _build_output


class TestOutputColumns:
    def test_has_permit_id(self):
        assert "permit_id" in OUTPUT_COLUMNS

    def test_has_state(self):
        assert "state" in OUTPUT_COLUMNS

    def test_has_applicant_name(self):
        assert "applicant_name" in OUTPUT_COLUMNS


class TestFilterPr:
    def test_filters_to_pr_only(self, caplog):
        import logging
        df = pd.DataFrame({
            "STATE_CODE": ["PR", "FL", "PR", "TX"],
            "applicant": ["A", "B", "C", "D"],
        })
        result = _filter_pr(df, logging.getLogger("test"))
        assert len(result) == 2

    def test_empty_input_returns_empty(self, caplog):
        import logging
        df = pd.DataFrame({"STATE_CODE": pd.Series([], dtype=str), "applicant": pd.Series([], dtype=str)})
        result = _filter_pr(df, logging.getLogger("test"))
        assert result.empty


class TestBuildOutput:
    def test_output_has_required_columns(self):
        df = pd.DataFrame({
            "STATE_CODE": ["PR"],
            "PERMIT_ID": ["P001"],
            "PERMIT_TYPE": ["Section 404"],
            "APPLICANT": ["Acme Corp"],
            "ISSUED_DATE": ["2022-01-01"],
            "EXPIRY_DATE": ["2027-01-01"],
            "PROJECT_DESC": ["Bridge construction"],
            "COUNTY_CODE": ["127"],
            "STATUS_CODE": ["ACT"],
            "VIOLATION_FLAG": ["N"],
        })
        out = _build_output(df)
        for col in ("permit_id", "applicant_name", "state"):
            assert col in out.columns


class TestRunCaching:
    def test_cached_when_output_exists(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        (tmp_path / "data" / "staging" / "raw" / "usace").mkdir(parents=True)
        out = processed / "pr_usace_permits.csv"
        out.write_text("permit_id\nP001\n")
        from scripts.download_usace_permits import run
        result = run(root=tmp_path, force=False)
        assert result.get("status") == "CACHED"

    def test_empty_when_download_fails(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        (tmp_path / "data" / "staging" / "raw" / "usace").mkdir(parents=True)
        with patch("scripts.download_usace_permits._download_zip", return_value=None):
            from scripts.download_usace_permits import run
            result = run(root=tmp_path, force=True)
        assert result.get("status") == "EMPTY"
