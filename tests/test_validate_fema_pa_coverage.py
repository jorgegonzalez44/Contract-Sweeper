"""Tests for scripts/validate_fema_pa_coverage.py — gap report, diff, high-value unresolved."""

import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.parquet_utils import pq_write
from scripts.validate_fema_pa_coverage import (
    DIFF_COLUMNS,
    GAP_COLUMNS,
    HIGH_VALUE_COLUMNS,
    HIGH_VALUE_THRESHOLD,
    PW_TARGET,
    _build_v1_v2_diff,
    _load_csv,
    _load_parquet,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_logger():
    return logging.getLogger("test_validate_fema_pa")


def _write_v2_parquet(path: Path, rows: list[dict]) -> None:
    """Write fema_pa_projects_v2 parquet fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    pq_write(df, path)


def _write_portal_parquet(path: Path, rows: list[dict]) -> None:
    """Write fema_pa_portal_178_pws parquet fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    pq_write(df, path)


def _write_linkage_csv(path: Path, rows: list[dict]) -> None:
    """Write fema_178_pw_linkage CSV fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")


def _setup_dirs(tmp_path: Path):
    """Create required subdirectories under tmp_path."""
    for sub in ["data/normalized", "data/validation", "data/review", "data/linked"]:
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# _load_parquet
# ---------------------------------------------------------------------------

class TestLoadParquet:
    def test_missing_file_returns_empty(self, tmp_path):
        logger = _make_logger()
        df = _load_parquet(tmp_path / "nonexistent.parquet", logger)
        assert df.empty

    def test_existing_parquet_loads_correctly(self, tmp_path):
        path = tmp_path / "test.parquet"
        df_src = pd.DataFrame({"pw_number": ["PW-001", "PW-002"], "project_amount": [500.0, 1000.0]})
        pq_write(df_src, path)
        logger = _make_logger()
        df = _load_parquet(path, logger)
        assert len(df) == 2
        assert "pw_number" in df.columns


# ---------------------------------------------------------------------------
# _load_csv
# ---------------------------------------------------------------------------

class TestLoadCsv:
    def test_missing_file_returns_empty(self, tmp_path):
        logger = _make_logger()
        df = _load_csv(tmp_path / "nonexistent.csv", logger)
        assert df.empty

    def test_existing_csv_loads_correctly(self, tmp_path):
        path = tmp_path / "linkage.csv"
        path.write_text("pw_number,link_confidence\nPW-001,high\nPW-002,none\n", encoding="utf-8")
        logger = _make_logger()
        df = _load_csv(path, logger)
        assert len(df) == 2
        assert "link_confidence" in df.columns


# ---------------------------------------------------------------------------
# _build_v1_v2_diff  (pure computation — mock network call)
# ---------------------------------------------------------------------------

class TestBuildV1V2Diff:
    def _mock_fetch(self, *args, **kwargs):
        """Return a stub (count, amount) without hitting the network."""
        return (500, 12345678.90)

    def test_returns_dataframe_with_correct_columns(self):
        logger = _make_logger()
        df_v2 = pd.DataFrame({
            "pw_number": ["PW-001"],
            "project_amount": [5_000_000.0],
        })
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", self._mock_fetch):
            result = _build_v1_v2_diff(df_v2, logger)
        assert list(result.columns) == DIFF_COLUMNS

    def test_returns_three_rows(self):
        logger = _make_logger()
        df_v2 = pd.DataFrame({"pw_number": ["PW-001"], "project_amount": [100.0]})
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", self._mock_fetch):
            result = _build_v1_v2_diff(df_v2, logger)
        assert len(result) == 3

    def test_first_row_metric_is_record_count_pr(self):
        logger = _make_logger()
        df_v2 = pd.DataFrame({"pw_number": ["PW-001"], "project_amount": [100.0]})
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", self._mock_fetch):
            result = _build_v1_v2_diff(df_v2, logger)
        assert result.iloc[0]["metric"] == "record_count_pr"

    def test_v2_count_matches_dataframe_length(self):
        logger = _make_logger()
        df_v2 = pd.DataFrame({"pw_number": ["PW-001", "PW-002", "PW-003"], "project_amount": [100.0, 200.0, 300.0]})
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", self._mock_fetch):
            result = _build_v1_v2_diff(df_v2, logger)
        assert result.iloc[0]["v2_value"] == 3.0

    def test_empty_v2_yields_zero_count(self):
        logger = _make_logger()
        df_v2 = pd.DataFrame()
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", self._mock_fetch):
            result = _build_v1_v2_diff(df_v2, logger)
        assert result.iloc[0]["v2_value"] == 0.0

    def test_note_row_has_no_numeric_diff(self):
        logger = _make_logger()
        df_v2 = pd.DataFrame({"pw_number": ["PW-001"], "project_amount": [100.0]})
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", self._mock_fetch):
            result = _build_v1_v2_diff(df_v2, logger)
        note_row = result[result["metric"] == "note"].iloc[0]
        assert note_row["difference"] is None or pd.isna(note_row["difference"])


# ---------------------------------------------------------------------------
# run() — missing inputs → empty gap report written, no exception
# ---------------------------------------------------------------------------

class TestRunMissingInputs:
    def test_run_creates_gap_csv_when_inputs_missing(self, tmp_path):
        """With no input files, run() must write the gap CSV (possibly empty) without raising."""
        _setup_dirs(tmp_path)
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(None, None)):
            run(root=tmp_path)
        gap_path = tmp_path / "data" / "validation" / "fema_pa_gap_report.csv"
        assert gap_path.exists(), "gap report CSV must be created even with missing inputs"

    def test_run_returns_dict_when_inputs_missing(self, tmp_path):
        _setup_dirs(tmp_path)
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(None, None)):
            result = run(root=tmp_path)
        assert isinstance(result, dict)
        assert "gap_count" in result
        assert "pw_coverage" in result
        assert "status" in result

    def test_run_gap_count_zero_when_no_v2_data(self, tmp_path):
        _setup_dirs(tmp_path)
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(None, None)):
            result = run(root=tmp_path)
        assert result["gap_count"] == 0

    def test_run_pw_coverage_zero_when_no_portal_data(self, tmp_path):
        _setup_dirs(tmp_path)
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(None, None)):
            result = run(root=tmp_path)
        assert result["pw_coverage"] == 0

    def test_run_coverage_pass_false_when_no_portal_data(self, tmp_path):
        _setup_dirs(tmp_path)
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(None, None)):
            result = run(root=tmp_path)
        assert result["coverage_pass"] is False

    def test_run_writes_gap_csv_with_correct_columns(self, tmp_path):
        _setup_dirs(tmp_path)
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(None, None)):
            run(root=tmp_path)
        gap_path = tmp_path / "data" / "validation" / "fema_pa_gap_report.csv"
        df_gap = pd.read_csv(gap_path)
        for col in GAP_COLUMNS:
            assert col in df_gap.columns, f"Missing column '{col}' in gap report"

    def test_run_writes_diff_csv_when_inputs_missing(self, tmp_path):
        _setup_dirs(tmp_path)
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(None, None)):
            run(root=tmp_path)
        diff_path = tmp_path / "data" / "validation" / "fema_pa_v1_v2_diff_report.csv"
        assert diff_path.exists(), "diff CSV must be written even with missing inputs"


# ---------------------------------------------------------------------------
# run() — with fixture parquets → expected outputs written
# ---------------------------------------------------------------------------

class TestRunWithFixtures:
    def _setup_v2(self, tmp_path):
        """Write a v2 parquet with 5 rows, 2 of which are in portal."""
        rows = [
            {"pw_number": "PW-001", "disaster_number": "4339", "applicant_name": "Town A", "category": "A", "project_amount": 500_000.0},
            {"pw_number": "PW-002", "disaster_number": "4339", "applicant_name": "Town B", "category": "B", "project_amount": 1_500_000.0},
            {"pw_number": "PW-003", "disaster_number": "4339", "applicant_name": "Town C", "category": "C", "project_amount": 250_000.0},
            {"pw_number": "PW-004", "disaster_number": "4339", "applicant_name": "Town D", "category": "D", "project_amount": 2_000_000.0},
            {"pw_number": "",       "disaster_number": "4339", "applicant_name": "Town E", "category": "E", "project_amount": 750_000.0},
        ]
        path = tmp_path / "data" / "normalized" / "fema_pa_projects_v2.parquet"
        _write_v2_parquet(path, rows)

    def _setup_portal(self, tmp_path, pw_numbers):
        """Write portal parquet with given pw_numbers."""
        rows = [{"pw_number": pw} for pw in pw_numbers]
        path = tmp_path / "data" / "normalized" / "fema_pa_portal_178_pws.parquet"
        _write_portal_parquet(path, rows)

    def _setup_linkage(self, tmp_path):
        """Write linkage CSV with one high-value row with confidence=none."""
        rows = [
            {"pw_number": "PW-002", "disaster_number": "4339", "applicant_name": "Town B",
             "v2_project_amount": "1500000", "link_confidence": "none"},
            {"pw_number": "PW-004", "disaster_number": "4339", "applicant_name": "Town D",
             "v2_project_amount": "2000000", "link_confidence": "none"},
            {"pw_number": "PW-001", "disaster_number": "4339", "applicant_name": "Town A",
             "v2_project_amount": "500000", "link_confidence": "high"},
        ]
        path = tmp_path / "data" / "linked" / "fema_178_pw_linkage.csv"
        _write_linkage_csv(path, rows)

    def test_gap_report_contains_pws_not_in_portal(self, tmp_path):
        _setup_dirs(tmp_path)
        self._setup_v2(tmp_path)
        # Portal only has PW-001 and PW-002
        self._setup_portal(tmp_path, ["PW-001", "PW-002"])
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(5, 0.0)):
            result = run(root=tmp_path)
        gap_path = tmp_path / "data" / "validation" / "fema_pa_gap_report.csv"
        df_gap = pd.read_csv(gap_path)
        # PW-003, PW-004, and empty pw (5 total - 2 matched = 3) should be in gap
        assert len(df_gap) == 3
        assert result["gap_count"] == 3

    def test_gap_reason_for_empty_pw_number(self, tmp_path):
        _setup_dirs(tmp_path)
        self._setup_v2(tmp_path)
        self._setup_portal(tmp_path, ["PW-001", "PW-002", "PW-003", "PW-004"])
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(5, 0.0)):
            run(root=tmp_path)
        df_gap = pd.read_csv(tmp_path / "data" / "validation" / "fema_pa_gap_report.csv")
        no_pw_rows = df_gap[df_gap["gap_reason"] == "no_pw_number"]
        assert len(no_pw_rows) == 1

    def test_gap_reason_for_pw_not_in_portal(self, tmp_path):
        _setup_dirs(tmp_path)
        self._setup_v2(tmp_path)
        self._setup_portal(tmp_path, ["PW-001"])  # only 1 match
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(5, 0.0)):
            run(root=tmp_path)
        df_gap = pd.read_csv(tmp_path / "data" / "validation" / "fema_pa_gap_report.csv")
        portal_gap = df_gap[df_gap["gap_reason"] == "pw_not_in_portal"]
        # PW-002, PW-003, PW-004 not in portal
        assert len(portal_gap) == 3

    def test_pw_coverage_reflects_portal_rows(self, tmp_path):
        _setup_dirs(tmp_path)
        self._setup_v2(tmp_path)
        self._setup_portal(tmp_path, [f"PW-{i:03d}" for i in range(1, 10)])
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(5, 0.0)):
            result = run(root=tmp_path)
        assert result["pw_coverage"] == 9

    def test_high_value_unresolved_written(self, tmp_path):
        _setup_dirs(tmp_path)
        self._setup_v2(tmp_path)
        self._setup_portal(tmp_path, ["PW-001"])
        self._setup_linkage(tmp_path)
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(5, 0.0)):
            result = run(root=tmp_path)
        hv_path = tmp_path / "data" / "review" / "fema_pa_high_value_unresolved.csv"
        assert hv_path.exists()
        df_hv = pd.read_csv(hv_path)
        # PW-002 ($1.5M) and PW-004 ($2M) both have confidence=none and > threshold
        assert len(df_hv) == 2
        assert result["high_value_unresolved"] == 2

    def test_high_value_excludes_below_threshold(self, tmp_path):
        """Only confidence=none rows with amount >= HIGH_VALUE_THRESHOLD appear in report."""
        _setup_dirs(tmp_path)
        self._setup_v2(tmp_path)
        self._setup_portal(tmp_path, ["PW-001"])
        # Write linkage with a low-value none row
        rows = [
            {"pw_number": "PW-003", "disaster_number": "4339", "applicant_name": "Town C",
             "v2_project_amount": "250000", "link_confidence": "none"},  # below threshold
        ]
        _write_linkage_csv(tmp_path / "data" / "linked" / "fema_178_pw_linkage.csv", rows)
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(5, 0.0)):
            result = run(root=tmp_path)
        assert result["high_value_unresolved"] == 0

    def test_high_value_report_has_correct_columns(self, tmp_path):
        _setup_dirs(tmp_path)
        self._setup_v2(tmp_path)
        self._setup_portal(tmp_path, ["PW-001"])
        self._setup_linkage(tmp_path)
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(5, 0.0)):
            run(root=tmp_path)
        df_hv = pd.read_csv(tmp_path / "data" / "review" / "fema_pa_high_value_unresolved.csv")
        for col in HIGH_VALUE_COLUMNS:
            assert col in df_hv.columns, f"Missing column '{col}' in high-value report"

    def test_diff_report_has_correct_columns(self, tmp_path):
        _setup_dirs(tmp_path)
        self._setup_v2(tmp_path)
        self._setup_portal(tmp_path, ["PW-001"])
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(5, 9999.0)):
            run(root=tmp_path)
        df_diff = pd.read_csv(tmp_path / "data" / "validation" / "fema_pa_v1_v2_diff_report.csv")
        for col in DIFF_COLUMNS:
            assert col in df_diff.columns, f"Missing column '{col}' in diff report"

    def test_status_ok_when_all_inputs_present(self, tmp_path):
        _setup_dirs(tmp_path)
        self._setup_v2(tmp_path)
        self._setup_portal(tmp_path, ["PW-001"])
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(5, 0.0)):
            result = run(root=tmp_path)
        assert result["status"] == "OK"

    def test_second_run_returns_cached(self, tmp_path):
        """Second run() call with existing gap_path returns CACHED status."""
        _setup_dirs(tmp_path)
        self._setup_v2(tmp_path)
        self._setup_portal(tmp_path, ["PW-001"])
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(5, 0.0)):
            run(root=tmp_path)
            result2 = run(root=tmp_path)
        assert result2["status"] == "CACHED"

    def test_force_reruns_despite_existing_output(self, tmp_path):
        """force=True causes re-run even when gap CSV already exists."""
        _setup_dirs(tmp_path)
        self._setup_v2(tmp_path)
        self._setup_portal(tmp_path, ["PW-001"])
        with patch("scripts.validate_fema_pa_coverage._fetch_count_and_amount", return_value=(5, 0.0)):
            run(root=tmp_path)
            result2 = run(root=tmp_path, force=True)
        assert result2["status"] == "OK"

    def test_pw_target_constant(self):
        assert PW_TARGET == 178

    def test_high_value_threshold_constant(self):
        assert HIGH_VALUE_THRESHOLD == 1_000_000
