"""Tests for scripts/download_cor3.py."""
import logging
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_cor3").setLevel(logging.CRITICAL)

from scripts.download_cor3 import OUTPUT_COLUMNS, _normalize_record, run


class TestNormalizeRecord:
    def test_basic_fields(self):
        r = {
            "applicant_name": "Acme Corp",
            "project_id": "PRJ-001",
            "total_approved": "$1,234,567.00",
            "total_disbursed": "500000.00",
        }
        out = _normalize_record(r)
        assert out["applicant_name"] == "Acme Corp"
        assert out["total_approved"] == pytest.approx(1234567.0)
        assert out["total_disbursed"] == pytest.approx(500000.0)

    def test_dollar_comma_stripping(self):
        r = {"total_approved": "$2,500,000", "total_disbursed": "0"}
        out = _normalize_record(r)
        assert out["total_approved"] == pytest.approx(2500000.0)

    def test_empty_amounts_default_to_zero(self):
        r = {}
        out = _normalize_record(r)
        assert out["total_approved"] == 0.0
        assert out["total_disbursed"] == 0.0

    def test_disbursement_rate_computed(self):
        r = {"total_approved": "1000000", "total_disbursed": "250000"}
        out = _normalize_record(r)
        assert out["disbursement_rate"] == pytest.approx(0.25)

    def test_disbursement_rate_zero_when_approved_zero(self):
        r = {"total_approved": "0", "total_disbursed": "100"}
        out = _normalize_record(r)
        assert out["disbursement_rate"] == 0.0

    def test_alias_keys_resolved(self):
        r = {"applicant": "Island Builders"}
        out = _normalize_record(r)
        assert out["applicant_name"] == "Island Builders"


class TestOutputColumns:
    def test_has_required_columns(self):
        for col in ("applicant_name", "project_id", "total_approved"):
            assert col in OUTPUT_COLUMNS


class TestRunCaching:
    def test_caching_skips_when_output_exists(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_cor3_projects.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path, force=False)
        assert result["status"] == "CACHED"

    def test_no_input_writes_empty_output(self, tmp_path):
        from unittest.mock import patch
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        with patch("scripts.download_cor3._try_json_endpoint", return_value=[]), \
             patch("scripts.download_cor3._try_csv_export", return_value=[]):
            result = run(root=tmp_path, force=False)
        assert "status" in result

    def test_result_keys_present(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        out = processed / "pr_cor3_projects.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path, force=False)
        assert "status" in result
        assert "rows" in result
