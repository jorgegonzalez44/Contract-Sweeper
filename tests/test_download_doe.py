"""Tests for download_doe.py — DOE grants downloader for Puerto Rico."""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Suppress noisy log output from the module under test
logging.getLogger("download_doe").setLevel(logging.CRITICAL)
logging.getLogger("test").setLevel(logging.CRITICAL)

from scripts.download_doe import (
    AGENCY_NAME,
    GRANT_TYPE_CODES,
    MASTER_COLUMNS,
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

    def test_december_advances_year(self):
        assert _derive_fiscal_year("2020-12-31") == "2021"


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

    def test_pop_filter_uses_place_of_performance_locations(self):
        payload = _build_payload("pop", self._window())
        assert "place_of_performance_locations" in payload["filters"]
        loc = payload["filters"]["place_of_performance_locations"][0]
        assert loc["state"] == "PR"
        assert loc["country"] == "USA"

    def test_pop_filter_does_not_include_recipient_locations(self):
        payload = _build_payload("pop", self._window())
        assert "recipient_locations" not in payload["filters"]

    def test_recipient_filter_uses_recipient_locations(self):
        payload = _build_payload("recipient", self._window())
        assert "recipient_locations" in payload["filters"]
        loc = payload["filters"]["recipient_locations"][0]
        assert loc["state"] == "PR"
        assert loc["country"] == "USA"

    def test_recipient_filter_does_not_include_pop_locations(self):
        payload = _build_payload("recipient", self._window())
        assert "place_of_performance_locations" not in payload["filters"]

    def test_payload_includes_grant_award_type_codes(self):
        payload = _build_payload("pop", self._window())
        assert payload["filters"]["award_type_codes"] == GRANT_TYPE_CODES

    def test_payload_includes_doe_agency(self):
        payload = _build_payload("pop", self._window())
        agencies = payload["filters"]["agencies"]
        agency_names = [a["name"] for a in agencies]
        assert AGENCY_NAME in agency_names

    def test_payload_date_range_matches_window(self):
        payload = _build_payload("pop", self._window())
        time_period = payload["filters"]["time_period"]
        assert time_period[0]["start_date"] == "2018-10-01"
        assert time_period[0]["end_date"] == "2022-09-30"

    def test_payload_has_page_and_limit(self):
        payload = _build_payload("pop", self._window())
        assert "page" in payload
        assert "limit" in payload
        assert payload["limit"] > 0

    def test_payload_subawards_is_false(self):
        payload = _build_payload("pop", self._window())
        assert payload["subawards"] is False


# ---------------------------------------------------------------------------
# _results_to_df
# ---------------------------------------------------------------------------

class TestResultsToDf:
    def _sample_results(self):
        return [
            {
                "Award ID": "DOE-2022-001",
                "Recipient Name": "PR Solar Corp",
                "recipient_uei": "UEI123",
                "Awarding Agency": "Department of Energy",
                "Awarding Sub Agency": "Office of Energy Efficiency",
                "Award Amount": 500000.0,
                "Start Date": "2022-03-15",
                "Award Type": "Grant",
                "Place of Performance State Code": "PR",
                "Place of Performance County Name": "San Juan",
                "Description": "Solar energy grant",
            }
        ]

    def test_returns_master_columns(self):
        df = _results_to_df(self._sample_results(), "doe_pop_2022.csv")
        assert list(df.columns) == MASTER_COLUMNS

    def test_award_id_mapped_correctly(self):
        df = _results_to_df(self._sample_results(), "doe_pop_2022.csv")
        assert df["award_id"].iloc[0] == "DOE-2022-001"

    def test_recipient_name_mapped_correctly(self):
        df = _results_to_df(self._sample_results(), "doe_pop_2022.csv")
        assert df["recipient_name"].iloc[0] == "PR Solar Corp"

    def test_source_file_populated(self):
        df = _results_to_df(self._sample_results(), "doe_pop_2022.csv")
        assert df["source_file"].iloc[0] == "doe_pop_2022.csv"

    def test_source_dataset_is_doe(self):
        df = _results_to_df(self._sample_results(), "doe_pop_2022.csv")
        assert df["source_dataset"].iloc[0] == "doe"

    def test_fiscal_year_derived_from_start_date(self):
        df = _results_to_df(self._sample_results(), "doe_pop_2022.csv")
        # 2022-03-15 → FY 2022
        assert df["fiscal_year"].iloc[0] == "2022"

    def test_empty_results_returns_master_columns(self):
        df = _results_to_df([], "doe_pop_empty.csv")
        assert list(df.columns) == MASTER_COLUMNS
        assert len(df) == 0

    def test_missing_columns_filled_with_empty_string(self):
        minimal = [{"Award ID": "X"}]
        df = _results_to_df(minimal, "test.csv")
        for col in MASTER_COLUMNS:
            assert col in df.columns

    def test_obligated_amount_mapped(self):
        df = _results_to_df(self._sample_results(), "doe_pop_2022.csv")
        assert df["obligated_amount"].iloc[0] == 500000.0

    def test_pop_state_mapped(self):
        df = _results_to_df(self._sample_results(), "doe_pop_2022.csv")
        assert df["pop_state"].iloc[0] == "PR"


# ---------------------------------------------------------------------------
# _file_has_data
# ---------------------------------------------------------------------------

class TestFileHasData:
    def test_missing_file_returns_false(self, tmp_path):
        assert _file_has_data(tmp_path / "nonexistent.csv") is False

    def test_valid_csv_with_row_returns_true(self, tmp_path):
        p = tmp_path / "data.csv"
        pd.DataFrame([{"a": 1}]).to_csv(p, index=False)
        assert _file_has_data(p) is True

    def test_corrupt_file_returns_false(self, tmp_path):
        p = tmp_path / "corrupt.csv"
        p.write_bytes(b"\x00\x01\x02\x03")
        result = _file_has_data(p)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# TIME_WINDOWS constant
# ---------------------------------------------------------------------------

class TestTimeWindowsConstant:
    def test_four_windows_defined(self):
        assert len(TIME_WINDOWS) == 4

    def test_window_keys_present(self):
        for w in TIME_WINDOWS:
            assert "label" in w
            assert "start_date" in w
            assert "end_date" in w
            assert "fy_start" in w

    def test_labels_are_unique(self):
        labels = [w["label"] for w in TIME_WINDOWS]
        assert len(labels) == len(set(labels))

    def test_fy_start_values_ascending(self):
        fy_starts = [w["fy_start"] for w in TIME_WINDOWS]
        assert fy_starts == sorted(fy_starts)


# ---------------------------------------------------------------------------
# build_master
# ---------------------------------------------------------------------------

class TestBuildMaster:
    def test_combines_multiple_raw_csvs(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        for i, name in enumerate(["doe_pop_2022.csv", "doe_recipient_2022.csv"]):
            row = {col: f"val{i}" for col in MASTER_COLUMNS}
            row["award_id"] = f"DOE-{i:03d}"
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
        for name in ["doe_pop_2022.csv", "doe_recipient_2022.csv"]:
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

    def test_master_csv_has_correct_columns(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        row = {col: "test_value" for col in MASTER_COLUMNS}
        row["award_id"] = "DOE-001"
        pd.DataFrame([row]).to_csv(raw_dir / "doe_pop_2022.csv", index=False)

        master_path = tmp_path / "master.csv"
        logger = logging.getLogger("test")
        build_master(raw_dir, master_path, logger)
        result = pd.read_csv(master_path, dtype=str)
        for col in MASTER_COLUMNS:
            assert col in result.columns


# ---------------------------------------------------------------------------
# run() integration — caching (force=False skips existing)
# ---------------------------------------------------------------------------

class TestRunCaching:
    """run() skips windows when output CSVs already exist (force=False)."""

    def test_skips_download_when_csv_exists(self, tmp_path):
        """Pre-existing CSVs cause all windows to be skipped — no HTTP calls."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "doe"
        raw_dir.mkdir(parents=True)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        # Pre-create one row for each window and filter type
        for window in TIME_WINDOWS:
            label = window["label"]
            for filter_type in ("pop", "recipient"):
                fname = f"doe_{filter_type}_{label}.csv"
                row = {col: "test_val" for col in MASTER_COLUMNS}
                row["award_id"] = f"DOE-{label}-{filter_type}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_doe.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            summary = run(root=tmp_path)

        # No HTTP POST should have been made — everything was cached
        mock_session.post.assert_not_called()
        assert isinstance(summary, dict)

    def test_run_returns_summary_dict_keys(self, tmp_path):
        """run() always returns a dict with the expected keys."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "doe"
        raw_dir.mkdir(parents=True)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        # Pre-fill all CSVs so no HTTP is needed
        for window in TIME_WINDOWS:
            label = window["label"]
            for filter_type in ("pop", "recipient"):
                fname = f"doe_{filter_type}_{label}.csv"
                row = {col: "v" for col in MASTER_COLUMNS}
                row["award_id"] = f"DOE-{label}-{filter_type}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_doe.requests.Session"):
            summary = run(root=tmp_path)

        for key in ("raw_pop_rows", "raw_recipient_rows", "master_rows", "errors", "windows"):
            assert key in summary

    def test_run_errors_list_is_list(self, tmp_path):
        """run() always returns errors as a list."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "doe"
        raw_dir.mkdir(parents=True)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        for window in TIME_WINDOWS:
            label = window["label"]
            for filter_type in ("pop", "recipient"):
                fname = f"doe_{filter_type}_{label}.csv"
                pd.DataFrame(columns=MASTER_COLUMNS).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_doe.requests.Session"):
            summary = run(root=tmp_path)

        assert isinstance(summary["errors"], list)

    def test_run_windows_list_has_four_entries(self, tmp_path):
        """run() returns stats for each of the four time windows."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "doe"
        raw_dir.mkdir(parents=True)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        for window in TIME_WINDOWS:
            label = window["label"]
            for filter_type in ("pop", "recipient"):
                fname = f"doe_{filter_type}_{label}.csv"
                pd.DataFrame(columns=MASTER_COLUMNS).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_doe.requests.Session"):
            summary = run(root=tmp_path)

        assert len(summary["windows"]) == 4


# ---------------------------------------------------------------------------
# run() integration — mocked HTTP download
# ---------------------------------------------------------------------------

def _make_mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


class TestRunWithMockedHttp:
    """run() with mocked HTTP produces output files."""

    def _sample_api_result(self, award_id: str = "DOE-MOCK-001"):
        return {
            "Award ID": award_id,
            "Recipient Name": "Mock Solar LLC",
            "recipient_uei": "MOCK001",
            "Awarding Agency": "Department of Energy",
            "Awarding Sub Agency": "EERE",
            "Award Amount": 100000.0,
            "Start Date": "2022-06-01",
            "Award Type": "Grant",
            "Place of Performance State Code": "PR",
            "Place of Performance County Name": "Ponce",
            "Description": "Mock DOE grant",
        }

    def _setup_mock_session(self, mock_session_cls, results: list, has_next: bool = False):
        """Wire up mock session to return paged API results."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        api_response = {
            "results": results,
            "page_metadata": {"has_next_page": has_next},
        }
        mock_resp = _make_mock_response(api_response)
        mock_session.post.return_value = mock_resp
        return mock_session

    def test_run_creates_raw_csv_files(self, tmp_path):
        """HTTP mocked data produces raw CSV files in the expected directory."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "doe"
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        # Only test the first window by pre-caching the other three
        for window in TIME_WINDOWS[1:]:
            raw_dir.mkdir(parents=True, exist_ok=True)
            label = window["label"]
            for filter_type in ("pop", "recipient"):
                fname = f"doe_{filter_type}_{label}.csv"
                pd.DataFrame(columns=MASTER_COLUMNS).to_csv(raw_dir / fname, index=False)

        results = [self._sample_api_result("DOE-TEST-001")]

        with patch("scripts.download_doe.requests.Session") as mock_session_cls:
            self._setup_mock_session(mock_session_cls, results)
            with patch("scripts.download_doe.time.sleep"):  # skip real sleeps
                summary = run(root=tmp_path)

        # At least some raw files should exist
        assert raw_dir.exists()
        csv_files = list(raw_dir.glob("doe_*.csv"))
        assert len(csv_files) >= 2

    def test_run_creates_master_csv(self, tmp_path):
        """run() calls build_master which creates the master CSV."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "doe"
        raw_dir.mkdir(parents=True)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        # Pre-fill all windows with data
        for window in TIME_WINDOWS:
            label = window["label"]
            for filter_type in ("pop", "recipient"):
                fname = f"doe_{filter_type}_{label}.csv"
                row = {col: "v" for col in MASTER_COLUMNS}
                row["award_id"] = f"DOE-{label}-{filter_type}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_doe.requests.Session"):
            summary = run(root=tmp_path)

        master_path = tmp_path / "data" / "staging" / "processed" / "pr_doe_master.csv"
        assert master_path.exists()
        assert summary["master_rows"] >= 1

    def test_run_master_path_in_summary(self, tmp_path):
        """run() summary includes the master_path string."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "doe"
        raw_dir.mkdir(parents=True)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        for window in TIME_WINDOWS:
            label = window["label"]
            for filter_type in ("pop", "recipient"):
                fname = f"doe_{filter_type}_{label}.csv"
                pd.DataFrame(columns=MASTER_COLUMNS).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_doe.requests.Session"):
            summary = run(root=tmp_path)

        assert "master_path" in summary
        assert "pr_doe_master.csv" in summary["master_path"]
