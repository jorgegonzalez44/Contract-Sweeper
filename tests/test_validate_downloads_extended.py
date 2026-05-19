"""Extended tests for scripts/validate_downloads.py — mixed statuses, validate_all."""

import logging
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.validate_downloads import validate_all, validate_file


@pytest.fixture
def logger():
    return logging.getLogger("test_validate_ext")


# ---------------------------------------------------------------------------
# validate_file — additional edge cases
# ---------------------------------------------------------------------------

class TestValidateFileExtended:
    def test_status_is_string(self, tmp_path, logger):
        result = validate_file(tmp_path / "missing.csv", logger)
        assert isinstance(result["status"], str)

    def test_result_has_all_expected_keys(self, tmp_path, logger):
        result = validate_file(tmp_path / "missing.csv", logger)
        required_keys = {"exists", "rows", "status", "errors", "warnings",
                         "date_col", "vendor_col", "agency_col", "amount_col"}
        assert required_keys.issubset(result.keys())

    def test_pass_status_only_when_all_columns_and_rows(self, tmp_path, logger):
        p = tmp_path / "complete.csv"
        lines = ["PIID,Date Signed,Vendor Name,Contracting Agency Name,Dollars Obligated\n"]
        lines += [f"C{i:04d},2022-01-01,Vendor {i},Army,{i*1000}\n" for i in range(60)]
        p.write_text("".join(lines))
        result = validate_file(p, logger)
        assert result["status"] == "PASS"

    def test_warn_status_when_columns_missing(self, tmp_path, logger):
        p = tmp_path / "partial.csv"
        lines = ["some_col,other_col\n"] + ["x,y\n"] * 60
        p.write_text("".join(lines))
        result = validate_file(p, logger)
        assert result["status"] == "WARN"

    def test_fail_status_for_missing_file(self, tmp_path, logger):
        result = validate_file(tmp_path / "nofile.csv", logger)
        assert result["status"] == "FAIL"

    def test_fail_status_for_empty_file(self, tmp_path, logger):
        p = tmp_path / "empty.csv"
        p.write_text("col_a,col_b\n")
        result = validate_file(p, logger)
        assert result["status"] == "FAIL"
        assert result["rows"] == 0

    def test_file_with_contract_id_column(self, tmp_path, logger):
        p = tmp_path / "piid.csv"
        lines = ["PIID,Date Signed,Vendor Name,Contracting Agency Name,Dollars Obligated\n"]
        lines += [f"C{i:04d},2022-01-01,Corp {i},Army,{i*100}\n" for i in range(55)]
        p.write_text("".join(lines))
        result = validate_file(p, logger)
        assert result["exists"] is True
        assert result["rows"] == 55


# ---------------------------------------------------------------------------
# validate_all — integration
# ---------------------------------------------------------------------------

class TestValidateAll:
    def test_returns_list(self, tmp_path):
        results = validate_all(root=tmp_path)
        assert isinstance(results, list)

    def test_missing_files_all_fail(self, tmp_path):
        results = validate_all(root=tmp_path)
        for r in results:
            assert r["status"] == "FAIL"
            assert r["exists"] is False

    def test_result_count_matches_manifest(self, tmp_path):
        from scripts.config import DOWNLOAD_MANIFEST
        results = validate_all(root=tmp_path)
        assert len(results) == len(DOWNLOAD_MANIFEST)

    def test_with_one_file_present_changes_status(self, tmp_path):
        from scripts.config import DOWNLOAD_MANIFEST
        if not DOWNLOAD_MANIFEST:
            pytest.skip("No manifest entries")
        first_entry = DOWNLOAD_MANIFEST[0]
        expansion_dir = tmp_path / "data" / "staging" / "expansion"
        expansion_dir.mkdir(parents=True)
        p = expansion_dir / first_entry["filename"]
        lines = ["PIID,Date Signed,Vendor Name,Contracting Agency Name,Dollars Obligated\n"]
        lines += [f"C{i:04d},2022-01-01,Corp {i},Army,{i*100}\n" for i in range(60)]
        p.write_text("".join(lines))

        results = validate_all(root=tmp_path)
        # The first file should now be PASS or WARN, not FAIL
        first = next(r for r in results if r["filename"] == first_entry["filename"])
        assert first["status"] != "FAIL"
        assert first["exists"] is True
