"""Tests for scripts/download_eqb.py."""
import logging
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_eqb").setLevel(logging.CRITICAL)

from scripts.download_eqb import OUTPUT_COLUMNS, _build_rows, run


class TestBuildRows:
    def _make_df(self, **kwargs):
        defaults = {
            "FAC_NAME": "Test Facility",
            "NPDES_ID": "PRW123",
            "PERMIT_ISSUE_DATE": "2020-01-01",
            "PERMIT_EXPIRATION_DATE": "2025-01-01",
            "VIOL_CNT": "0",
            "INSP_CNT": "3",
            "FAC_STATE": "PR",
        }
        defaults.update(kwargs)
        return pd.DataFrame([defaults])

    def test_basic_fields_mapped(self):
        df = self._make_df()
        rows = _build_rows(df, "air")
        assert len(rows) == 1
        assert rows[0]["facility_name"] == "Test Facility"
        assert rows[0]["permit_id"] == "PRW123"

    def test_permit_type_assigned(self):
        rows = _build_rows(self._make_df(), "water")
        assert rows[0]["permit_type"] == "water"

    def test_violation_count_numeric(self):
        df = self._make_df(**{"VIOL_CNT": "5"})
        rows = _build_rows(df, "air")
        assert rows[0]["violation_count"] == 5

    def test_inspection_count_numeric(self):
        df = self._make_df(**{"INSP_CNT": "7"})
        rows = _build_rows(df, "water")
        assert rows[0]["inspection_count"] == 7

    def test_empty_df_returns_empty_list(self):
        rows = _build_rows(pd.DataFrame(), "air")
        assert rows == []

    def test_facility_normalized_uppercased(self):
        df = self._make_df(**{"FAC_NAME": "caribbean water corp"})
        rows = _build_rows(df, "air")
        assert rows[0]["facility_normalized"] == rows[0]["facility_normalized"].upper()


class TestOutputColumns:
    def test_has_permit_id(self):
        assert "permit_id" in OUTPUT_COLUMNS

    def test_has_facility_name(self):
        assert "facility_name" in OUTPUT_COLUMNS

    def test_has_violation_count(self):
        assert "violation_count" in OUTPUT_COLUMNS


class TestRunCaching:
    def test_existing_output_returns_cached(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_eqb_permits.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path, force=False)
        assert result["status"] == "CACHED"

    def test_result_has_status_key(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_eqb_permits.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path, force=False)
        assert "status" in result
        assert "rows" in result
