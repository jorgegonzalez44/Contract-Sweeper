"""Tests for scripts/validate_expansion_coverage.py — expansion coverage validation."""

import logging
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.validate_expansion_coverage import (
    COVERAGE_YEARS,
    CRITICAL_2007_FILES,
    build_coverage_matrix,
    check_2007_gap,
    check_file_coverage,
    main,
    report_coverage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_csv(path: Path, years: list, extra_cols: dict = None) -> Path:
    """Write a minimal CSV with a fiscal_year column and optional extra columns."""
    data = {"fiscal_year": years}
    if extra_cols:
        data.update(extra_cols)
    pd.DataFrame(data).to_csv(path, index=False)
    return path


@pytest.fixture
def logger():
    """Return a silent test logger."""
    log = logging.getLogger("test_expansion_coverage")
    log.setLevel(logging.DEBUG)
    if not log.handlers:
        log.addHandler(logging.NullHandler())
    return log


# ---------------------------------------------------------------------------
# TestCheckFileCoverage
# ---------------------------------------------------------------------------

class TestCheckFileCoverage:
    def test_missing_file_returns_exists_false(self, tmp_path):
        result = check_file_coverage(tmp_path / "does_not_exist.csv")
        assert result["exists"] is False

    def test_missing_file_returns_empty_fiscal_years(self, tmp_path):
        result = check_file_coverage(tmp_path / "does_not_exist.csv")
        assert result["fiscal_years"] == set()

    def test_missing_file_has_error_message(self, tmp_path):
        result = check_file_coverage(tmp_path / "does_not_exist.csv")
        assert len(result["errors"]) > 0

    def test_missing_file_zero_rows(self, tmp_path):
        result = check_file_coverage(tmp_path / "does_not_exist.csv")
        assert result["rows"] == 0

    def test_file_with_no_rows_exists_but_zero_rows(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("fiscal_year,vendor_name\n", encoding="utf-8")
        result = check_file_coverage(p)
        assert result["exists"] is True
        assert result["rows"] == 0
        assert result["fiscal_years"] == set()

    def test_file_with_fiscal_years_reports_them(self, tmp_path):
        p = _make_csv(tmp_path / "data.csv", [2005, 2006, 2007, 2008])
        result = check_file_coverage(p)
        assert result["fiscal_years"] == {2005, 2006, 2007, 2008}

    def test_row_count_is_accurate(self, tmp_path):
        p = _make_csv(tmp_path / "data.csv", [2005, 2006, 2007])
        result = check_file_coverage(p)
        assert result["rows"] == 3

    def test_out_of_range_years_excluded(self, tmp_path):
        # 1999 below 2000, 2027 above 2026 — both should be excluded
        p = _make_csv(tmp_path / "data.csv", [1999, 2005, 2027])
        result = check_file_coverage(p)
        assert 2005 in result["fiscal_years"]
        assert 1999 not in result["fiscal_years"]
        assert 2027 not in result["fiscal_years"]

    def test_duplicate_years_collapsed_to_set(self, tmp_path):
        p = _make_csv(tmp_path / "data.csv", [2010, 2010, 2010, 2011])
        result = check_file_coverage(p)
        assert result["fiscal_years"] == {2010, 2011}

    def test_no_fiscal_year_column_returns_empty_set(self, tmp_path):
        p = tmp_path / "no_fy.csv"
        pd.DataFrame({"vendor_name": ["A", "B"], "amount": [1, 2]}).to_csv(p, index=False)
        result = check_file_coverage(p)
        assert result["exists"] is True
        assert result["fiscal_years"] == set()

    def test_year_2026_boundary_included(self, tmp_path):
        # Boundary: 2000 <= y <= 2026 is the filter in check_file_coverage
        p = _make_csv(tmp_path / "data.csv", [2000, 2026])
        result = check_file_coverage(p)
        assert 2000 in result["fiscal_years"]
        assert 2026 in result["fiscal_years"]

    def test_non_numeric_fiscal_year_coerced_to_nan(self, tmp_path):
        p = tmp_path / "mixed.csv"
        pd.DataFrame({"fiscal_year": ["2010", "N/A", "2011"]}).to_csv(p, index=False)
        result = check_file_coverage(p)
        # N/A coerces to NaN and is dropped; 2010 and 2011 remain
        assert 2010 in result["fiscal_years"]
        assert 2011 in result["fiscal_years"]


# ---------------------------------------------------------------------------
# TestCheck2007Gap
# ---------------------------------------------------------------------------

class TestCheck2007Gap:
    def test_returns_true_when_2007_in_both_critical_files(self):
        matrix = {
            CRITICAL_2007_FILES[0]: {"exists": True, "fiscal_years": {2005, 2006, 2007, 2008}},
            CRITICAL_2007_FILES[1]: {"exists": True, "fiscal_years": {2005, 2006, 2007, 2008}},
        }
        assert check_2007_gap(matrix) is True

    def test_returns_false_when_2007_missing_in_first_file(self):
        matrix = {
            CRITICAL_2007_FILES[0]: {"exists": True, "fiscal_years": {2005, 2006, 2008}},
            CRITICAL_2007_FILES[1]: {"exists": True, "fiscal_years": {2005, 2006, 2007, 2008}},
        }
        assert check_2007_gap(matrix) is False

    def test_returns_false_when_2007_missing_in_second_file(self):
        matrix = {
            CRITICAL_2007_FILES[0]: {"exists": True, "fiscal_years": {2005, 2006, 2007, 2008}},
            CRITICAL_2007_FILES[1]: {"exists": True, "fiscal_years": {2005, 2006, 2008}},
        }
        assert check_2007_gap(matrix) is False

    def test_returns_false_when_2007_missing_in_both_files(self):
        matrix = {
            CRITICAL_2007_FILES[0]: {"exists": True, "fiscal_years": {2005, 2006, 2008}},
            CRITICAL_2007_FILES[1]: {"exists": True, "fiscal_years": {2005, 2006, 2008}},
        }
        assert check_2007_gap(matrix) is False

    def test_returns_false_when_matrix_is_empty(self):
        assert check_2007_gap({}) is False

    def test_returns_false_when_one_critical_file_missing_from_matrix(self):
        matrix = {
            CRITICAL_2007_FILES[0]: {"exists": True, "fiscal_years": {2005, 2006, 2007, 2008}},
            # CRITICAL_2007_FILES[1] absent entirely
        }
        assert check_2007_gap(matrix) is False

    def test_returns_false_when_file_recorded_as_not_existing(self):
        matrix = {
            CRITICAL_2007_FILES[0]: {"exists": False, "fiscal_years": set()},
            CRITICAL_2007_FILES[1]: {"exists": True, "fiscal_years": {2005, 2006, 2007, 2008}},
        }
        assert check_2007_gap(matrix) is False

    def test_critical_2007_files_constant_has_both_fpds_files(self):
        assert len(CRITICAL_2007_FILES) == 2
        assert all("fpds_2005_2008" in f for f in CRITICAL_2007_FILES)
        assert any("direct" in f for f in CRITICAL_2007_FILES)
        assert any("vendor" in f for f in CRITICAL_2007_FILES)


# ---------------------------------------------------------------------------
# TestCoverageYears
# ---------------------------------------------------------------------------

class TestCoverageYears:
    def test_coverage_years_starts_at_2000(self):
        assert COVERAGE_YEARS[0] == 2000

    def test_coverage_years_ends_at_2025(self):
        assert COVERAGE_YEARS[-1] == 2025

    def test_coverage_years_has_26_years(self):
        assert len(COVERAGE_YEARS) == 26

    def test_coverage_years_is_contiguous(self):
        assert COVERAGE_YEARS == list(range(2000, 2026))


# ---------------------------------------------------------------------------
# TestBuildCoverageMatrix
# ---------------------------------------------------------------------------

class TestBuildCoverageMatrix:
    def test_returns_dict_keyed_by_normalized_filename(self, tmp_path):
        # processed_dir has no files — all entries should show exists=False
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)
        matrix = build_coverage_matrix(tmp_path)
        assert isinstance(matrix, dict)
        assert len(matrix) > 0

    def test_missing_files_all_report_not_exists(self, tmp_path):
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)
        matrix = build_coverage_matrix(tmp_path)
        assert all(not info["exists"] for info in matrix.values())

    def test_present_file_detected_as_existing(self, tmp_path):
        from scripts.config import DOWNLOAD_MANIFEST, get_normalized_filename
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)
        # Create one normalized file
        first_entry = DOWNLOAD_MANIFEST[0]
        norm_name = get_normalized_filename(first_entry["filename"])
        _make_csv(processed_dir / norm_name, [2000, 2001, 2002])
        matrix = build_coverage_matrix(tmp_path)
        assert matrix[norm_name]["exists"] is True
        assert matrix[norm_name]["rows"] == 3

    def test_matrix_keys_use_normalized_prefix(self, tmp_path):
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)
        matrix = build_coverage_matrix(tmp_path)
        assert all(k.startswith("normalized_") for k in matrix.keys())


# ---------------------------------------------------------------------------
# TestReportCoverage
# ---------------------------------------------------------------------------

class TestReportCoverage:
    def test_returns_dict_with_expected_keys(self, logger):
        matrix = {
            "normalized_expansion_fpds_2000_2004_direct.csv": {
                "exists": True, "rows": 100, "fiscal_years": {2000, 2001, 2002, 2003, 2004}, "errors": []
            },
        }
        summary = report_coverage(matrix, logger)
        assert "total_files" in summary
        assert "files_exist" in summary
        assert "files_with_rows" in summary
        assert "covered_years" in summary
        assert "missing_years" in summary
        assert "gap_2007_ok" in summary
        assert "timeline_gaps" in summary

    def test_total_files_count(self, logger):
        matrix = {
            "file_a.csv": {"exists": True, "rows": 10, "fiscal_years": {2005}, "errors": []},
            "file_b.csv": {"exists": False, "rows": 0, "fiscal_years": set(), "errors": []},
        }
        summary = report_coverage(matrix, logger)
        assert summary["total_files"] == 2

    def test_files_exist_count(self, logger):
        matrix = {
            "file_a.csv": {"exists": True, "rows": 10, "fiscal_years": {2005}, "errors": []},
            "file_b.csv": {"exists": False, "rows": 0, "fiscal_years": set(), "errors": []},
        }
        summary = report_coverage(matrix, logger)
        assert summary["files_exist"] == 1

    def test_covered_years_aggregated_across_files(self, logger):
        matrix = {
            "file_a.csv": {"exists": True, "rows": 5, "fiscal_years": {2000, 2001}, "errors": []},
            "file_b.csv": {"exists": True, "rows": 5, "fiscal_years": {2002, 2003}, "errors": []},
        }
        summary = report_coverage(matrix, logger)
        assert 2000 in summary["covered_years"]
        assert 2001 in summary["covered_years"]
        assert 2002 in summary["covered_years"]
        assert 2003 in summary["covered_years"]

    def test_missing_years_reported(self, logger):
        # Only 2010 covered → everything else is missing
        matrix = {
            "file_a.csv": {"exists": True, "rows": 1, "fiscal_years": {2010}, "errors": []},
        }
        summary = report_coverage(matrix, logger)
        assert 2000 in summary["missing_years"]
        assert 2010 not in summary["missing_years"]

    def test_gap_2007_ok_false_when_critical_files_absent(self, logger):
        # Matrix has no critical files → 2007 gap not verified
        matrix = {
            "normalized_expansion_other_file.csv": {
                "exists": True, "rows": 5, "fiscal_years": {2005, 2006, 2007, 2008}, "errors": []
            },
        }
        summary = report_coverage(matrix, logger)
        assert summary["gap_2007_ok"] is False

    def test_timeline_gaps_detected(self, logger):
        # Cover 2000 and 2002 but not 2001 → gap at 2001
        matrix = {
            "file_a.csv": {"exists": True, "rows": 2, "fiscal_years": {2000, 2002}, "errors": []},
        }
        summary = report_coverage(matrix, logger)
        assert 2001 in summary["timeline_gaps"]

    def test_no_timeline_gaps_when_contiguous(self, logger):
        matrix = {
            "file_a.csv": {"exists": True, "rows": 3, "fiscal_years": {2000, 2001, 2002}, "errors": []},
        }
        summary = report_coverage(matrix, logger)
        assert summary["timeline_gaps"] == []


# ---------------------------------------------------------------------------
# TestMainIntegration
# ---------------------------------------------------------------------------

class TestMainIntegration:
    def _setup_dirs(self, tmp_path: Path) -> Path:
        """Create directory structure expected by main()."""
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / "logs").mkdir(parents=True, exist_ok=True)
        return tmp_path

    def test_main_missing_processed_dir_returns_nonzero(self, tmp_path):
        """main() with no processed dir and no files should return 1 (graceful skip)."""
        # Only create logs dir; no processed dir
        (tmp_path / "data" / "logs").mkdir(parents=True, exist_ok=True)
        result = main(root=tmp_path)
        assert result == 1

    def test_main_no_files_returns_nonzero(self, tmp_path):
        """main() with empty processed dir returns 1."""
        self._setup_dirs(tmp_path)
        result = main(root=tmp_path)
        assert result == 1

    def test_main_with_some_files_returns_integer(self, tmp_path):
        """main() with fixture CSVs runs without crashing and returns int."""
        from scripts.config import DOWNLOAD_MANIFEST, get_normalized_filename
        processed_dir = self._setup_dirs(tmp_path) / "data" / "staging" / "processed"
        # Create enough files with broad year coverage to get a result
        years_batches = [
            list(range(2000, 2005)),
            list(range(2005, 2009)),
            list(range(2009, 2017)),
            list(range(2017, 2026)),
        ]
        for i, entry in enumerate(DOWNLOAD_MANIFEST[:8]):
            norm_name = get_normalized_filename(entry["filename"])
            batch = years_batches[i // 2]
            _make_csv(processed_dir / norm_name, batch)
        result = main(root=tmp_path)
        assert isinstance(result, int)

    def test_main_returns_0_when_full_coverage_with_2007(self, tmp_path):
        """main() returns 0 only when all years covered and 2007 present."""
        from scripts.config import DOWNLOAD_MANIFEST, get_normalized_filename
        processed_dir = self._setup_dirs(tmp_path) / "data" / "staging" / "processed"
        all_years = list(range(2000, 2026))
        for entry in DOWNLOAD_MANIFEST:
            norm_name = get_normalized_filename(entry["filename"])
            _make_csv(processed_dir / norm_name, all_years)
        result = main(root=tmp_path)
        assert result == 0

    def test_main_returns_1_when_missing_years(self, tmp_path):
        """main() returns 1 when coverage is incomplete."""
        from scripts.config import DOWNLOAD_MANIFEST, get_normalized_filename
        processed_dir = self._setup_dirs(tmp_path) / "data" / "staging" / "processed"
        # Only cover 2010-2020, leaving many years missing
        partial_years = list(range(2010, 2021))
        for entry in DOWNLOAD_MANIFEST:
            norm_name = get_normalized_filename(entry["filename"])
            _make_csv(processed_dir / norm_name, partial_years)
        result = main(root=tmp_path)
        assert result == 1

    def test_main_does_not_crash_without_manifest(self, tmp_path):
        """main() with missing processed dir doesn't raise, returns non-zero gracefully."""
        # No processed dir at all — main should handle it gracefully
        (tmp_path / "data" / "logs").mkdir(parents=True, exist_ok=True)
        try:
            result = main(root=tmp_path)
            assert isinstance(result, int)
        except SystemExit as e:
            # sys.exit() is acceptable
            assert e.code in (0, 1)
