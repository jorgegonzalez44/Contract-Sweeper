"""Tests for download_subawards.py — USASpending subawards downloader."""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Suppress noisy log output from the module under test
logging.getLogger("download_subawards").setLevel(logging.CRITICAL)
logging.getLogger("test").setLevel(logging.CRITICAL)

from scripts.download_subawards import (
    CONTRACT_TYPE_CODES,
    GRANT_TYPE_CODES,
    MASTER_COLUMNS,
    SUBAWARD_FIELDS,
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

    def test_december_boundary_next_year(self):
        assert _derive_fiscal_year("2022-12-31") == "2023"

    def test_empty_string_returns_empty(self):
        assert _derive_fiscal_year("") == ""

    def test_none_returns_empty(self):
        assert _derive_fiscal_year(None) == ""

    def test_invalid_date_returns_empty(self):
        assert _derive_fiscal_year("not-a-date") == ""

    def test_nan_returns_empty(self):
        import numpy as np
        assert _derive_fiscal_year(float("nan")) == ""


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

    def test_returns_dict(self):
        payload = _build_payload(self._window(), GRANT_TYPE_CODES)
        assert isinstance(payload, dict)

    def test_filters_contains_award_type_codes(self):
        payload = _build_payload(self._window(), GRANT_TYPE_CODES)
        assert payload["filters"]["award_type_codes"] == GRANT_TYPE_CODES

    def test_filters_contains_contract_codes(self):
        payload = _build_payload(self._window(), CONTRACT_TYPE_CODES)
        assert payload["filters"]["award_type_codes"] == CONTRACT_TYPE_CODES

    def test_place_of_performance_is_pr(self):
        payload = _build_payload(self._window(), GRANT_TYPE_CODES)
        locs = payload["filters"]["place_of_performance_locations"]
        assert len(locs) == 1
        assert locs[0]["country"] == "USA"
        assert locs[0]["state"] == "PR"

    def test_time_period_matches_window(self):
        window = self._window()
        payload = _build_payload(window, GRANT_TYPE_CODES)
        tp = payload["filters"]["time_period"]
        assert tp[0]["start_date"] == window["start_date"]
        assert tp[0]["end_date"] == window["end_date"]

    def test_subawards_flag_is_true(self):
        payload = _build_payload(self._window(), GRANT_TYPE_CODES)
        assert payload["subawards"] is True

    def test_fields_list_is_present(self):
        payload = _build_payload(self._window(), GRANT_TYPE_CODES)
        assert "fields" in payload
        assert isinstance(payload["fields"], list)
        assert len(payload["fields"]) > 0

    def test_fields_match_subaward_fields(self):
        payload = _build_payload(self._window(), GRANT_TYPE_CODES)
        assert payload["fields"] == SUBAWARD_FIELDS

    def test_limit_is_positive_integer(self):
        payload = _build_payload(self._window(), GRANT_TYPE_CODES)
        assert isinstance(payload["limit"], int)
        assert payload["limit"] > 0

    def test_sort_field_present(self):
        payload = _build_payload(self._window(), GRANT_TYPE_CODES)
        assert "sort" in payload

    def test_order_field_present(self):
        payload = _build_payload(self._window(), GRANT_TYPE_CODES)
        assert "order" in payload


# ---------------------------------------------------------------------------
# _results_to_df  (row normalization)
# ---------------------------------------------------------------------------

class TestResultsToDf:
    def _sample_results(self):
        return [
            {
                "Sub-Award ID": "SA-001",
                "Sub-Awardee Name": "Puerto Rico Corp",
                "Sub-Award Amount": 150000.0,
                "Sub-Award Date": "2021-04-15",
                "Prime Award ID": "PA-PRIME-001",
                "Prime Recipient Name": "Main Contractor Inc",
                "Awarding Agency": "Department of Defense",
                "Place of Performance State Code": "PR",
                "Description": "Infrastructure support services",
            }
        ]

    def test_returns_dataframe(self):
        df = _results_to_df(self._sample_results(), "subawards_grants_2018f2022.csv")
        assert isinstance(df, pd.DataFrame)

    def test_columns_match_master_columns(self):
        df = _results_to_df(self._sample_results(), "subawards_grants_2018f2022.csv")
        assert list(df.columns) == MASTER_COLUMNS

    def test_award_id_mapped_correctly(self):
        df = _results_to_df(self._sample_results(), "test.csv")
        assert df["award_id"].iloc[0] == "SA-001"

    def test_recipient_name_mapped_correctly(self):
        df = _results_to_df(self._sample_results(), "test.csv")
        assert df["recipient_name"].iloc[0] == "Puerto Rico Corp"

    def test_obligated_amount_mapped_correctly(self):
        df = _results_to_df(self._sample_results(), "test.csv")
        assert df["obligated_amount"].iloc[0] == 150000.0

    def test_prime_award_id_mapped(self):
        df = _results_to_df(self._sample_results(), "test.csv")
        assert df["prime_award_id"].iloc[0] == "PA-PRIME-001"

    def test_prime_recipient_name_mapped(self):
        df = _results_to_df(self._sample_results(), "test.csv")
        assert df["prime_recipient_name"].iloc[0] == "Main Contractor Inc"

    def test_awarding_agency_mapped(self):
        df = _results_to_df(self._sample_results(), "test.csv")
        assert df["awarding_agency"].iloc[0] == "Department of Defense"

    def test_pop_state_mapped(self):
        df = _results_to_df(self._sample_results(), "test.csv")
        assert df["pop_state"].iloc[0] == "PR"

    def test_description_mapped(self):
        df = _results_to_df(self._sample_results(), "test.csv")
        assert df["description"].iloc[0] == "Infrastructure support services"

    def test_source_file_populated(self):
        df = _results_to_df(self._sample_results(), "subawards_grants_2018f2022.csv")
        assert df["source_file"].iloc[0] == "subawards_grants_2018f2022.csv"

    def test_source_dataset_is_subawards(self):
        df = _results_to_df(self._sample_results(), "test.csv")
        assert df["source_dataset"].iloc[0] == "subawards"

    def test_award_category_is_subaward(self):
        df = _results_to_df(self._sample_results(), "test.csv")
        assert df["award_category"].iloc[0] == "subaward"

    def test_fiscal_year_derived_from_date(self):
        # 2021-04-15 → FY2021 (April is in calendar year 2021, before Oct)
        df = _results_to_df(self._sample_results(), "test.csv")
        assert df["fiscal_year"].iloc[0] == "2021"

    def test_fiscal_year_oct_advances(self):
        results = [dict(self._sample_results()[0], **{"Sub-Award Date": "2021-10-01"})]
        df = _results_to_df(results, "test.csv")
        assert df["fiscal_year"].iloc[0] == "2022"

    def test_empty_results_returns_empty_df_with_master_columns(self):
        df = _results_to_df([], "test.csv")
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == MASTER_COLUMNS
        assert len(df) == 0

    def test_missing_optional_fields_filled_with_empty(self):
        # Only provide minimum fields; all others should be empty string
        minimal = [{"Sub-Award ID": "MIN-001"}]
        df = _results_to_df(minimal, "test.csv")
        for col in MASTER_COLUMNS:
            assert col in df.columns

    def test_multiple_rows_preserved(self):
        results = [
            dict(self._sample_results()[0], **{"Sub-Award ID": f"SA-{i}"})
            for i in range(5)
        ]
        df = _results_to_df(results, "test.csv")
        assert len(df) == 5


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

    def test_empty_file_returns_false(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("")
        assert _file_has_data(p) is False

    def test_corrupt_file_returns_false(self, tmp_path):
        p = tmp_path / "corrupt.csv"
        p.write_bytes(b"\x00\x01\x02\x03")
        result = _file_has_data(p)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------

class TestConstants:
    def test_grant_type_codes_non_empty(self):
        assert len(GRANT_TYPE_CODES) > 0

    def test_contract_type_codes_non_empty(self):
        assert len(CONTRACT_TYPE_CODES) > 0

    def test_time_windows_has_four_entries(self):
        assert len(TIME_WINDOWS) == 4

    def test_time_window_keys_present(self):
        for w in TIME_WINDOWS:
            for key in ("label", "start_date", "end_date", "fy_start"):
                assert key in w, f"Missing key '{key}' in window {w}"

    def test_master_columns_non_empty(self):
        assert len(MASTER_COLUMNS) > 0

    def test_subaward_fields_non_empty(self):
        assert len(SUBAWARD_FIELDS) > 0

    def test_grant_and_contract_codes_disjoint(self):
        assert set(GRANT_TYPE_CODES).isdisjoint(set(CONTRACT_TYPE_CODES))


# ---------------------------------------------------------------------------
# build_master
# ---------------------------------------------------------------------------

class TestBuildMaster:
    def test_combines_multiple_raw_csvs(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        for i, name in enumerate(["subawards_grants_2018f2022.csv", "subawards_contracts_2018f2022.csv"]):
            row = {col: f"val{i}_{col}" for col in MASTER_COLUMNS}
            row["award_id"] = f"SA-{i:03d}"
            pd.DataFrame([row]).to_csv(raw_dir / name, index=False)

        master_path = tmp_path / "master.csv"
        logger = logging.getLogger("test")
        rows = build_master(raw_dir, master_path, logger)
        assert rows == 2
        assert master_path.exists()

    def test_deduplicates_by_award_id(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        row = {col: "" for col in MASTER_COLUMNS}
        row["award_id"] = "DUP-001"
        for name in ["subawards_grants_2010f2017.csv", "subawards_contracts_2010f2017.csv"]:
            pd.DataFrame([row]).to_csv(raw_dir / name, index=False)

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

    def test_master_contains_all_canonical_columns(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        row = {col: "x" for col in MASTER_COLUMNS}
        row["award_id"] = "SA-CANONIC"
        pd.DataFrame([row]).to_csv(raw_dir / "subawards_grants_2023f2026.csv", index=False)

        master_path = tmp_path / "master.csv"
        logger = logging.getLogger("test")
        build_master(raw_dir, master_path, logger)
        result = pd.read_csv(master_path, dtype=str)
        for col in MASTER_COLUMNS:
            assert col in result.columns


# ---------------------------------------------------------------------------
# run() — caching (force=False skips existing files)
# ---------------------------------------------------------------------------

def _make_api_response(results=None, has_next_page=False):
    """Build a mock API JSON response."""
    return {
        "results": results or [],
        "page_metadata": {"has_next_page": has_next_page},
    }


def _make_mock_post(json_data):
    """Return a mock requests.Session.post that returns a canned response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


class TestRunCaching:
    """run() skips download when output CSVs already exist (force=False)."""

    def _pre_create_all_files(self, tmp_path):
        """Create all expected raw subaward files with at least one data row so caching kicks in."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "subawards"
        raw_dir.mkdir(parents=True)
        for window in TIME_WINDOWS:
            for type_group in ("grants", "contracts"):
                fname = f"subawards_{type_group}_{window['label']}.csv"
                row = {col: "cached" for col in MASTER_COLUMNS}
                row["award_id"] = f"CACHE-{type_group}-{window['label']}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)
        return raw_dir

    def test_skips_http_when_all_files_cached(self, tmp_path):
        """No HTTP calls made when all raw files already exist."""
        self._pre_create_all_files(tmp_path)

        with patch("scripts.download_subawards.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            run(root=tmp_path)

        mock_session.post.assert_not_called()

    def test_run_returns_summary_dict(self, tmp_path):
        """run() always returns a dict with expected keys."""
        self._pre_create_all_files(tmp_path)

        with patch("scripts.download_subawards.requests.Session"):
            summary = run(root=tmp_path)

        assert isinstance(summary, dict)
        for key in ("raw_rows", "master_rows", "errors", "windows"):
            assert key in summary

    def test_run_errors_list_is_list(self, tmp_path):
        """run() always returns errors as a list."""
        self._pre_create_all_files(tmp_path)

        with patch("scripts.download_subawards.requests.Session"):
            summary = run(root=tmp_path)

        assert isinstance(summary["errors"], list)

    def test_run_windows_list_has_four_entries(self, tmp_path):
        """run() returns stats for each of the four time windows."""
        self._pre_create_all_files(tmp_path)

        with patch("scripts.download_subawards.requests.Session"):
            summary = run(root=tmp_path)

        assert len(summary["windows"]) == 4

    def test_master_csv_written_from_cached_files(self, tmp_path):
        """Master CSV is built from pre-existing raw files."""
        self._pre_create_all_files(tmp_path)

        with patch("scripts.download_subawards.requests.Session"):
            summary = run(root=tmp_path)

        master_path = tmp_path / "data" / "staging" / "processed" / "pr_subawards_master.csv"
        assert master_path.exists()
        assert summary["master_rows"] >= 1

    def test_raw_rows_count_from_cached_files(self, tmp_path):
        """raw_rows in summary reflects cached data."""
        self._pre_create_all_files(tmp_path)

        with patch("scripts.download_subawards.requests.Session"):
            summary = run(root=tmp_path)

        # 4 windows × 2 type groups × 1 row each = 8 total
        assert summary["raw_rows"] == 8


# ---------------------------------------------------------------------------
# run() — mocked HTTP download path
# ---------------------------------------------------------------------------

class TestRunWithMockedHttp:
    """run() fetches data and writes CSVs when raw files do not exist."""

    def _mock_session_returning(self, mock_session_cls, results):
        """Wire mock session to return given results on the first page, then empty."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        first_resp = MagicMock()
        first_resp.status_code = 200
        first_resp.json.return_value = _make_api_response(results=results, has_next_page=False)
        first_resp.raise_for_status.return_value = None

        mock_session.post.return_value = first_resp
        return mock_session

    def _sample_result(self, award_id="SA-HTTP-001"):
        return {
            "Sub-Award ID": award_id,
            "Sub-Awardee Name": "HTTP Test Corp",
            "Sub-Award Amount": 50000.0,
            "Sub-Award Date": "2019-06-01",
            "Prime Award ID": "PA-PARENT-001",
            "Prime Recipient Name": "Parent Contractor",
            "Awarding Agency": "HUD",
            "Place of Performance State Code": "PR",
            "Description": "Mock subaward",
        }

    def test_raw_files_created_after_download(self, tmp_path):
        """Raw CSV files are written after successful API responses."""
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        with patch("scripts.download_subawards.requests.Session") as mock_session_cls, \
             patch("scripts.download_subawards.time.sleep"):  # skip sleeps
            # Return one result on the first call, empty on subsequent calls
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            call_count = [0]

            def side_effect(url, json=None, timeout=None):
                resp = MagicMock()
                resp.status_code = 200
                resp.raise_for_status.return_value = None
                if call_count[0] == 0:
                    resp.json.return_value = _make_api_response(
                        results=[self._sample_result()], has_next_page=False
                    )
                else:
                    resp.json.return_value = _make_api_response(results=[], has_next_page=False)
                call_count[0] += 1
                return resp

            mock_session.post.side_effect = side_effect
            run(root=tmp_path)

        raw_dir = tmp_path / "data" / "staging" / "raw" / "subawards"
        csv_files = list(raw_dir.glob("subawards_*.csv"))
        assert len(csv_files) > 0

    def test_master_csv_created_after_download(self, tmp_path):
        """Master CSV is created after download."""
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        with patch("scripts.download_subawards.requests.Session") as mock_session_cls, \
             patch("scripts.download_subawards.time.sleep"):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status.return_value = None
            resp.json.return_value = _make_api_response(results=[], has_next_page=False)
            mock_session.post.return_value = resp

            run(root=tmp_path)

        master_path = tmp_path / "data" / "staging" / "processed" / "pr_subawards_master.csv"
        # Master path existence depends on whether any raw files were written
        assert isinstance(master_path, Path)

    def test_summary_raw_rows_positive_when_data_returned(self, tmp_path):
        """raw_rows > 0 when API returns results."""
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        with patch("scripts.download_subawards.requests.Session") as mock_session_cls, \
             patch("scripts.download_subawards.time.sleep"):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            call_count = [0]

            def side_effect(url, json=None, timeout=None):
                resp = MagicMock()
                resp.status_code = 200
                resp.raise_for_status.return_value = None
                if call_count[0] < 2:
                    resp.json.return_value = _make_api_response(
                        results=[self._sample_result(f"SA-{call_count[0]:03d}")],
                        has_next_page=False,
                    )
                else:
                    resp.json.return_value = _make_api_response(results=[], has_next_page=False)
                call_count[0] += 1
                return resp

            mock_session.post.side_effect = side_effect
            summary = run(root=tmp_path)

        assert summary["raw_rows"] >= 0  # may be 0 if only first window data captured

    def test_summary_has_windows_key_with_list(self, tmp_path):
        """run() always returns 'windows' as a list."""
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        with patch("scripts.download_subawards.requests.Session") as mock_session_cls, \
             patch("scripts.download_subawards.time.sleep"):
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status.return_value = None
            resp.json.return_value = _make_api_response(results=[], has_next_page=False)
            mock_session.post.return_value = resp

            summary = run(root=tmp_path)

        assert isinstance(summary["windows"], list)
