"""Extended tests for scripts/validate_expansion_coverage.py — edge cases."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.validate_expansion_coverage import (
    COVERAGE_YEARS,
    build_coverage_matrix,
    check_2007_gap,
    check_file_coverage,
    report_coverage,
)


# ---------------------------------------------------------------------------
# check_file_coverage — edge cases
# ---------------------------------------------------------------------------

import logging

def _logger():
    logger = logging.getLogger("test_coverage_ext")
    logger.setLevel(logging.CRITICAL)
    return logger


class TestCheckFileCoverageExtended:
    def test_zero_rows_returns_zero_not_nan(self, tmp_path):
        p = tmp_path / "header_only.csv"
        p.write_text("fiscal_year,vendor_name\n", encoding="utf-8")
        result = check_file_coverage(p)
        assert result["rows"] == 0
        # Explicitly not NaN — rows is an integer
        assert isinstance(result["rows"], int)

    def test_file_with_no_fiscal_year_column(self, tmp_path):
        p = tmp_path / "no_fy.csv"
        pd.DataFrame([{"vendor": "Corp A", "amount": "100"}]).to_csv(p, index=False)
        result = check_file_coverage(p)
        assert result["exists"] is True
        assert result["fiscal_years"] == set()

    def test_fiscal_year_out_of_range_excluded(self, tmp_path):
        p = tmp_path / "old.csv"
        pd.DataFrame([
            {"fiscal_year": "1999", "vendor": "Old Corp"},
            {"fiscal_year": "2022", "vendor": "New Corp"},
        ]).to_csv(p, index=False)
        result = check_file_coverage(p)
        assert 1999 not in result["fiscal_years"]
        assert 2022 in result["fiscal_years"]

    def test_non_numeric_fiscal_year_handled(self, tmp_path):
        p = tmp_path / "bad_fy.csv"
        pd.DataFrame([
            {"fiscal_year": "N/A", "vendor": "Corp A"},
            {"fiscal_year": "2021", "vendor": "Corp B"},
        ]).to_csv(p, index=False)
        result = check_file_coverage(p)
        # N/A should be coerced away; 2021 should remain
        assert 2021 in result["fiscal_years"]

    def test_result_dict_has_required_keys(self, tmp_path):
        result = check_file_coverage(tmp_path / "nonexistent.csv")
        assert "exists" in result
        assert "rows" in result
        assert "fiscal_years" in result
        assert "errors" in result


# ---------------------------------------------------------------------------
# check_2007_gap — edge cases
# ---------------------------------------------------------------------------

class TestCheck2007GapExtended:
    def test_empty_matrix_returns_false(self):
        assert check_2007_gap({}) is False

    def test_file_not_tracked_returns_false(self):
        # None entry for a critical file
        from scripts.validate_expansion_coverage import CRITICAL_2007_FILES
        if not CRITICAL_2007_FILES:
            pytest.skip("No critical files defined")
        fname = CRITICAL_2007_FILES[0]
        matrix = {fname: None}
        assert check_2007_gap(matrix) is False

    def test_file_with_2007_covered(self):
        from scripts.validate_expansion_coverage import CRITICAL_2007_FILES
        if not CRITICAL_2007_FILES:
            pytest.skip("No critical files defined")
        matrix = {f: {"exists": True, "rows": 100, "fiscal_years": {2007, 2008}, "errors": []}
                  for f in CRITICAL_2007_FILES}
        assert check_2007_gap(matrix) is True

    def test_one_file_missing_2007(self):
        from scripts.validate_expansion_coverage import CRITICAL_2007_FILES
        if len(CRITICAL_2007_FILES) < 2:
            pytest.skip("Need at least 2 critical files")
        matrix = {f: {"exists": True, "rows": 100, "fiscal_years": {2007}, "errors": []}
                  for f in CRITICAL_2007_FILES}
        # Remove 2007 from first file
        matrix[CRITICAL_2007_FILES[0]]["fiscal_years"] = {2008}
        assert check_2007_gap(matrix) is False


# ---------------------------------------------------------------------------
# build_coverage_matrix — integration
# ---------------------------------------------------------------------------

class TestBuildCoverageMatrix:
    def test_returns_dict(self, tmp_path):
        result = build_coverage_matrix(tmp_path)
        assert isinstance(result, dict)

    def test_all_files_missing_returns_not_exists(self, tmp_path):
        result = build_coverage_matrix(tmp_path)
        for info in result.values():
            assert info["exists"] is False

    def test_matrix_keys_are_strings(self, tmp_path):
        result = build_coverage_matrix(tmp_path)
        assert all(isinstance(k, str) for k in result)

    def test_no_target_in_registry_is_graceful(self, tmp_path):
        # Should not crash even when processed dir doesn't exist
        result = build_coverage_matrix(tmp_path)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# COVERAGE_YEARS constant
# ---------------------------------------------------------------------------

class TestCoverageYears:
    def test_is_a_list(self):
        assert isinstance(COVERAGE_YEARS, list)

    def test_includes_2007(self):
        assert 2007 in COVERAGE_YEARS

    def test_includes_recent_year(self):
        assert any(y >= 2020 for y in COVERAGE_YEARS)

    def test_all_are_ints(self):
        assert all(isinstance(y, int) for y in COVERAGE_YEARS)
