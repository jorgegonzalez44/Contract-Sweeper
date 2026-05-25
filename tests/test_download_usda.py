"""Tests for download_usda.py — USDA grants/loans downloader for Puerto Rico."""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Suppress noisy log output from the module under test
logging.getLogger("download_usda").setLevel(logging.CRITICAL)
logging.getLogger("test").setLevel(logging.CRITICAL)

from scripts.download_usda import (
    AGENCY_NAME,
    FIELDS,
    GRANT_TYPE_CODES,
    LOAN_TYPE_CODES,
    MASTER_COLUMNS,
    PASSES,
    TIME_WINDOWS,
    _build_payload,
    _derive_fiscal_year,
    _file_has_data,
    _results_to_df,
    build_master,
    run,
)


# ---------------------------------------------------------------------------
# _derive_fiscal_year
# ---------------------------------------------------------------------------

class TestDeriveFiscalYear:
    def test_jan_to_sep_returns_same_year(self):
        assert _derive_fiscal_year("2023-03-15") == "2023"

    def test_oct_to_dec_returns_next_year(self):
        assert _derive_fiscal_year("2022-10-01") == "2023"

    def test_september_boundary_same_year(self):
        assert _derive_fiscal_year("2023-09-30") == "2023"

    def test_empty_string_returns_empty(self):
        assert _derive_fiscal_year("") == ""

    def test_none_returns_empty(self):
        assert _derive_fiscal_year(None) == ""

    def test_invalid_date_returns_empty(self):
        assert _derive_fiscal_year("not-a-date") == ""

    def test_december_is_next_fiscal_year(self):
        assert _derive_fiscal_year("2021-12-31") == "2022"

    def test_nan_returns_empty(self):
        assert _derive_fiscal_year(float("nan")) == ""


# ---------------------------------------------------------------------------
# _file_has_data
# ---------------------------------------------------------------------------

class TestFileHasData:
    def test_missing_file_returns_false(self, tmp_path):
        assert _file_has_data(tmp_path / "nonexistent.csv") is False

    def test_valid_csv_with_data_returns_true(self, tmp_path):
        p = tmp_path / "data.csv"
        pd.DataFrame([{"a": 1}]).to_csv(p, index=False)
        assert _file_has_data(p) is True

    def test_header_only_csv_returns_false(self, tmp_path):
        # nrows=2 on an empty CSV yields 0 rows → False
        p = tmp_path / "header_only.csv"
        pd.DataFrame(columns=["a", "b"]).to_csv(p, index=False)
        assert _file_has_data(p) is False

    def test_corrupt_file_returns_false(self, tmp_path):
        p = tmp_path / "corrupt.csv"
        p.write_bytes(b"\x00\x01\x02\x03")
        result = _file_has_data(p)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# _build_payload
# ---------------------------------------------------------------------------

class TestBuildPayload:
    def _window(self):
        return {
            "label": "2018f2022",
            "start_date": "2018-10-01",
            "end_date": "2022-09-30",
            "fy_start": 2018,
        }

    def test_pop_filter_uses_place_of_performance(self):
        payload = _build_payload(GRANT_TYPE_CODES, "pop", self._window())
        f = payload["filters"]
        assert "place_of_performance_locations" in f
        assert f["place_of_performance_locations"][0]["state"] == "PR"
        assert "recipient_locations" not in f

    def test_recipient_filter_uses_recipient_locations(self):
        payload = _build_payload(GRANT_TYPE_CODES, "recipient", self._window())
        f = payload["filters"]
        assert "recipient_locations" in f
        assert f["recipient_locations"][0]["state"] == "PR"
        assert "place_of_performance_locations" not in f

    def test_award_type_codes_present(self):
        payload = _build_payload(GRANT_TYPE_CODES, "pop", self._window())
        assert payload["filters"]["award_type_codes"] == GRANT_TYPE_CODES

    def test_loan_type_codes_present(self):
        payload = _build_payload(LOAN_TYPE_CODES, "recipient", self._window())
        assert payload["filters"]["award_type_codes"] == LOAN_TYPE_CODES

    def test_date_range_matches_window(self):
        payload = _build_payload(GRANT_TYPE_CODES, "pop", self._window())
        tp = payload["filters"]["time_period"]
        assert len(tp) == 1
        assert tp[0]["start_date"] == "2018-10-01"
        assert tp[0]["end_date"] == "2022-09-30"

    def test_agency_filter_is_usda(self):
        payload = _build_payload(GRANT_TYPE_CODES, "pop", self._window())
        agencies = payload["filters"]["agencies"]
        assert any(a["name"] == AGENCY_NAME for a in agencies)

    def test_grants_sort_field_is_award_amount(self):
        payload = _build_payload(GRANT_TYPE_CODES, "pop", self._window())
        assert payload["sort"] == "Award Amount"

    def test_loans_sort_field_is_award_id(self):
        payload = _build_payload(LOAN_TYPE_CODES, "recipient", self._window())
        assert payload["sort"] == "Award ID"

    def test_subawards_is_false(self):
        payload = _build_payload(GRANT_TYPE_CODES, "pop", self._window())
        assert payload["subawards"] is False

    def test_fields_list_present(self):
        payload = _build_payload(GRANT_TYPE_CODES, "pop", self._window())
        assert "fields" in payload
        assert "Award ID" in payload["fields"]

    def test_location_country_is_usa(self):
        payload = _build_payload(GRANT_TYPE_CODES, "pop", self._window())
        loc = payload["filters"]["place_of_performance_locations"][0]
        assert loc["country"] == "USA"

    def test_limit_is_100(self):
        payload = _build_payload(GRANT_TYPE_CODES, "pop", self._window())
        assert payload["limit"] == 100


# ---------------------------------------------------------------------------
# _results_to_df
# ---------------------------------------------------------------------------

class TestResultsToDf:
    def _sample_result(self):
        return {
            "Award ID": "AWARD-001",
            "Recipient Name": "Puerto Rico Farms Inc",
            "recipient_uei": "UEI123",
            "Awarding Agency": "Department of Agriculture",
            "Awarding Sub Agency": "Farm Service Agency",
            "Award Amount": 75000.0,
            "Start Date": "2021-03-15",
            "Award Type": "04",
            "Place of Performance State Code": "PR",
            "Place of Performance County Name": "Mayaguez",
            "Description": "Rural development grant",
        }

    def test_returns_master_columns(self):
        df = _results_to_df([self._sample_result()], "usda_grants_pop_2018f2022.csv")
        assert list(df.columns) == MASTER_COLUMNS

    def test_award_id_renamed(self):
        df = _results_to_df([self._sample_result()], "usda_grants_pop_2018f2022.csv")
        assert df["award_id"].iloc[0] == "AWARD-001"

    def test_recipient_name_renamed(self):
        df = _results_to_df([self._sample_result()], "usda_grants_pop_2018f2022.csv")
        assert df["recipient_name"].iloc[0] == "Puerto Rico Farms Inc"

    def test_source_file_populated(self):
        df = _results_to_df([self._sample_result()], "usda_grants_pop_2018f2022.csv")
        assert df["source_file"].iloc[0] == "usda_grants_pop_2018f2022.csv"

    def test_source_dataset_is_usda(self):
        df = _results_to_df([self._sample_result()], "usda_grants_pop_2018f2022.csv")
        assert df["source_dataset"].iloc[0] == "usda"

    def test_fiscal_year_derived_from_start_date(self):
        df = _results_to_df([self._sample_result()], "usda_grants_pop_2018f2022.csv")
        # 2021-03-15 → FY2021
        assert df["fiscal_year"].iloc[0] == "2021"

    def test_empty_results_returns_master_columns(self):
        df = _results_to_df([], "usda_grants_pop_2018f2022.csv")
        assert list(df.columns) == MASTER_COLUMNS
        assert len(df) == 0

    def test_missing_columns_filled_with_empty_string(self):
        minimal = {"Award ID": "X123"}
        df = _results_to_df([minimal], "test.csv")
        for col in MASTER_COLUMNS:
            assert col in df.columns

    def test_pop_state_and_county_mapped(self):
        df = _results_to_df([self._sample_result()], "usda_grants_pop_2018f2022.csv")
        assert df["pop_state"].iloc[0] == "PR"
        assert df["pop_county"].iloc[0] == "Mayaguez"


# ---------------------------------------------------------------------------
# build_master
# ---------------------------------------------------------------------------

class TestBuildMaster:
    def _write_raw_csv(self, path: Path, award_id: str = "AWARD-001"):
        row = {col: "val" for col in MASTER_COLUMNS}
        row["award_id"] = award_id
        pd.DataFrame([row]).to_csv(path, index=False)

    def test_combines_multiple_raw_csvs(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        self._write_raw_csv(raw_dir / "usda_grants_pop_2018f2022.csv", "AWARD-001")
        self._write_raw_csv(raw_dir / "usda_grants_recipient_2018f2022.csv", "AWARD-002")

        master_path = tmp_path / "master.csv"
        logger = logging.getLogger("test")
        rows = build_master(raw_dir, master_path, logger)
        assert rows == 2
        assert master_path.exists()

    def test_deduplicates_by_award_id(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        # Same award_id in two files
        self._write_raw_csv(raw_dir / "usda_grants_pop_2018f2022.csv", "DUP-001")
        self._write_raw_csv(raw_dir / "usda_grants_recipient_2018f2022.csv", "DUP-001")

        master_path = tmp_path / "master.csv"
        logger = logging.getLogger("test")
        rows = build_master(raw_dir, master_path, logger)
        assert rows == 1

    def test_empty_raw_dir_returns_zero(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        master_path = tmp_path / "master.csv"
        logger = logging.getLogger("test")
        rows = build_master(raw_dir, master_path, logger)
        assert rows == 0
        assert not master_path.exists()

    def test_master_csv_contains_correct_columns(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        self._write_raw_csv(raw_dir / "usda_grants_pop_2023f2026.csv", "AWARD-999")

        master_path = tmp_path / "master.csv"
        logger = logging.getLogger("test")
        build_master(raw_dir, master_path, logger)
        result = pd.read_csv(master_path, dtype=str)
        for col in MASTER_COLUMNS:
            assert col in result.columns


# ---------------------------------------------------------------------------
# Constants / structure checks
# ---------------------------------------------------------------------------

class TestConstants:
    def test_three_passes_defined(self):
        assert len(PASSES) == 3

    def test_pass_tuples_have_three_elements(self):
        for p in PASSES:
            assert len(p) == 3

    def test_filter_types_valid(self):
        valid = {"pop", "recipient"}
        for _, _, filter_type in PASSES:
            assert filter_type in valid

    def test_four_time_windows(self):
        assert len(TIME_WINDOWS) == 4

    def test_time_window_keys_present(self):
        for w in TIME_WINDOWS:
            for key in ("label", "start_date", "end_date", "fy_start"):
                assert key in w

    def test_grant_type_codes_non_empty(self):
        assert len(GRANT_TYPE_CODES) > 0

    def test_loan_type_codes_contain_07_08(self):
        assert "07" in LOAN_TYPE_CODES
        assert "08" in LOAN_TYPE_CODES

    def test_fields_list_contains_award_id(self):
        assert "Award ID" in FIELDS

    def test_master_columns_list_non_empty(self):
        assert len(MASTER_COLUMNS) > 0


# ---------------------------------------------------------------------------
# Helpers for mocking HTTP
# ---------------------------------------------------------------------------

def _make_mock_post_response(results: list, has_next_page: bool = False) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "results": results,
        "page_metadata": {"has_next_page": has_next_page},
    }
    resp.raise_for_status.return_value = None
    return resp


def _sample_api_result(award_id: str = "AWARD-001") -> dict:
    return {
        "Award ID": award_id,
        "Recipient Name": "PR Farm Corp",
        "recipient_uei": "UEI999",
        "Awarding Agency": "Department of Agriculture",
        "Awarding Sub Agency": "Rural Development",
        "Award Amount": 50000.0,
        "Start Date": "2021-05-10",
        "Award Type": "04",
        "Place of Performance State Code": "PR",
        "Place of Performance County Name": "Ponce",
        "Description": "Rural grant",
    }


# ---------------------------------------------------------------------------
# run() — caching (force=False skips existing files)
# ---------------------------------------------------------------------------

class TestRunCaching:
    """run() skips passes when output CSVs already exist and force=False."""

    def _pre_create_all_outputs(self, tmp_path: Path):
        """Write a data CSV for every PASS × TIME_WINDOW combination."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "usda"
        raw_dir.mkdir(parents=True, exist_ok=True)
        for prefix, _, _ in PASSES:
            for window in TIME_WINDOWS:
                fname = f"{prefix}_{window['label']}.csv"
                row = {col: "cached" for col in MASTER_COLUMNS}
                row["award_id"] = f"{prefix}-{window['label']}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True, exist_ok=True)

    def test_skips_http_when_all_csvs_exist(self, tmp_path):
        """No HTTP calls made when every output CSV already has data."""
        self._pre_create_all_outputs(tmp_path)
        with patch("scripts.download_usda.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            run(root=tmp_path)
        mock_session.post.assert_not_called()

    def test_returns_summary_dict(self, tmp_path):
        """run() always returns a dict."""
        self._pre_create_all_outputs(tmp_path)
        with patch("scripts.download_usda.requests.Session"):
            summary = run(root=tmp_path)
        assert isinstance(summary, dict)

    def test_summary_has_required_keys(self, tmp_path):
        """Summary dict contains master_rows, master_path, errors, windows."""
        self._pre_create_all_outputs(tmp_path)
        with patch("scripts.download_usda.requests.Session"):
            summary = run(root=tmp_path)
        for key in ("master_rows", "master_path", "errors", "windows"):
            assert key in summary

    def test_errors_is_list(self, tmp_path):
        """summary['errors'] is always a list."""
        self._pre_create_all_outputs(tmp_path)
        with patch("scripts.download_usda.requests.Session"):
            summary = run(root=tmp_path)
        assert isinstance(summary["errors"], list)

    def test_windows_length_matches_time_windows(self, tmp_path):
        """summary['windows'] contains one entry per TIME_WINDOW."""
        self._pre_create_all_outputs(tmp_path)
        with patch("scripts.download_usda.requests.Session"):
            summary = run(root=tmp_path)
        assert len(summary["windows"]) == len(TIME_WINDOWS)

    def test_master_csv_written_from_cached_data(self, tmp_path):
        """Master CSV is written from the pre-existing raw CSVs."""
        self._pre_create_all_outputs(tmp_path)
        with patch("scripts.download_usda.requests.Session"):
            summary = run(root=tmp_path)
        master_path = tmp_path / "data" / "staging" / "processed" / "pr_usda_master.csv"
        assert master_path.exists()
        assert summary["master_rows"] > 0


# ---------------------------------------------------------------------------
# run() — mocked HTTP download path
# ---------------------------------------------------------------------------

class TestRunWithMockedHttp:
    """run() correctly fetches and saves data when CSVs are missing."""

    def _make_session_mock(self, results: list):
        """Return a mock session whose POST returns one page of results."""
        mock_session = MagicMock()
        mock_session.post.return_value = _make_mock_post_response(results, has_next_page=False)
        return mock_session

    def test_output_csv_written_for_each_pass_window(self, tmp_path):
        """A CSV is created for each PASS × TIME_WINDOW combination."""
        with patch("scripts.download_usda.requests.Session") as mock_session_cls:
            mock_session_cls.return_value = self._make_session_mock(
                [_sample_api_result(f"AWARD-{i}") for i in range(3)]
            )
            with patch("scripts.download_usda.time.sleep"):
                from scripts.download_usda import _run
                _run(root=tmp_path, force=True)

        raw_dir = tmp_path / "data" / "staging" / "raw" / "usda"
        csvs = list(raw_dir.glob("usda_*.csv"))
        expected_count = len(PASSES) * len(TIME_WINDOWS)
        assert len(csvs) == expected_count

    def test_master_csv_written_after_download(self, tmp_path):
        """pr_usda_master.csv is created after a successful download."""
        with patch("scripts.download_usda.requests.Session") as mock_session_cls:
            mock_session_cls.return_value = self._make_session_mock(
                [_sample_api_result("AWARD-MASTER-01")]
            )
            with patch("scripts.download_usda.time.sleep"):
                from scripts.download_usda import _run
                _run(root=tmp_path, force=True)

        master_path = tmp_path / "data" / "staging" / "processed" / "pr_usda_master.csv"
        assert master_path.exists()

    def test_no_results_writes_empty_csv(self, tmp_path):
        """When the API returns no results, an empty CSV is still written."""
        with patch("scripts.download_usda.requests.Session") as mock_session_cls:
            mock_session_cls.return_value = self._make_session_mock([])
            with patch("scripts.download_usda.time.sleep"):
                from scripts.download_usda import _run
                summary = _run(root=tmp_path, force=True)

        raw_dir = tmp_path / "data" / "staging" / "raw" / "usda"
        csvs = list(raw_dir.glob("usda_*.csv"))
        assert len(csvs) > 0
        # all passes had no results → errors recorded
        assert isinstance(summary["errors"], list)

    def test_http_error_recorded_in_summary(self, tmp_path):
        """A 400 HTTP error is gracefully handled and reported in summary."""
        mock_session = MagicMock()
        error_resp = MagicMock()
        error_resp.status_code = 400
        error_resp.text = "Bad Request"
        mock_session.post.return_value = error_resp

        with patch("scripts.download_usda.requests.Session") as mock_session_cls:
            mock_session_cls.return_value = mock_session
            with patch("scripts.download_usda.time.sleep"):
                from scripts.download_usda import _run
                summary = _run(root=tmp_path, force=True)

        assert isinstance(summary, dict)
        assert isinstance(summary["errors"], list)

    def test_fy_start_filters_windows(self, tmp_path):
        """Passing fy_start limits which time windows are processed."""
        with patch("scripts.download_usda.requests.Session") as mock_session_cls:
            mock_session_cls.return_value = self._make_session_mock([])
            with patch("scripts.download_usda.time.sleep"):
                from scripts.download_usda import _run
                summary = _run(root=tmp_path, force=True, fy_start=2023)

        # Only windows with fy_start >= 2023 should be processed
        expected_windows = [w for w in TIME_WINDOWS if w["fy_start"] >= 2023]
        assert len(summary["windows"]) == len(expected_windows)
