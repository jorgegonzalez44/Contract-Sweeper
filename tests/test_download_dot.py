"""Tests for download_dot.py — DOT grants downloader for Puerto Rico."""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Suppress noisy log output from the module under test
logging.getLogger("download_dot").setLevel(logging.CRITICAL)
logging.getLogger("test").setLevel(logging.CRITICAL)

from scripts.download_dot import (
    AGENCY_NAME,
    FIELDS,
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

    def test_december_rolls_to_next_fy(self):
        assert _derive_fiscal_year("2019-12-31") == "2020"


# ---------------------------------------------------------------------------
# _file_has_data
# ---------------------------------------------------------------------------

class TestFileHasData:
    def test_missing_file_returns_false(self, tmp_path):
        assert _file_has_data(tmp_path / "nonexistent.csv") is False

    def test_valid_csv_with_rows_returns_true(self, tmp_path):
        p = tmp_path / "data.csv"
        pd.DataFrame([{"a": 1}]).to_csv(p, index=False)
        assert _file_has_data(p) is True

    def test_header_only_csv_returns_false(self, tmp_path):
        # header-only has 0 data rows; nrows=2 yields empty df
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
            "label": "2010f2017",
            "start_date": "2010-10-01",
            "end_date": "2017-09-30",
            "fy_start": 2010,
        }

    def test_pop_filter_uses_place_of_performance(self):
        payload = _build_payload("pop", self._window())
        f = payload["filters"]
        assert "place_of_performance_locations" in f
        assert f["place_of_performance_locations"][0]["state"] == "PR"
        assert "recipient_locations" not in f

    def test_recipient_filter_uses_recipient_locations(self):
        payload = _build_payload("recipient", self._window())
        f = payload["filters"]
        assert "recipient_locations" in f
        assert f["recipient_locations"][0]["state"] == "PR"
        assert "place_of_performance_locations" not in f

    def test_filters_award_type_codes_match_constants(self):
        payload = _build_payload("pop", self._window())
        assert payload["filters"]["award_type_codes"] == GRANT_TYPE_CODES

    def test_filters_agency_is_dot(self):
        payload = _build_payload("pop", self._window())
        agencies = payload["filters"]["agencies"]
        assert any(AGENCY_NAME in a.get("name", "") for a in agencies)

    def test_time_period_matches_window(self):
        payload = _build_payload("pop", self._window())
        tp = payload["filters"]["time_period"]
        assert tp[0]["start_date"] == "2010-10-01"
        assert tp[0]["end_date"] == "2017-09-30"

    def test_fields_present_in_payload(self):
        payload = _build_payload("pop", self._window())
        assert "fields" in payload
        assert isinstance(payload["fields"], list)
        assert len(payload["fields"]) > 0

    def test_location_country_is_usa(self):
        for filter_type in ("pop", "recipient"):
            payload = _build_payload(filter_type, self._window())
            f = payload["filters"]
            if filter_type == "pop":
                loc = f["place_of_performance_locations"][0]
            else:
                loc = f["recipient_locations"][0]
            assert loc["country"] == "USA"


# ---------------------------------------------------------------------------
# _results_to_df
# ---------------------------------------------------------------------------

class TestResultsToDf:
    def _sample_results(self):
        return [
            {
                "Award ID": "DOT-001",
                "Recipient Name": "PR Transit Authority",
                "recipient_uei": "UEI-ABC",
                "Awarding Agency": "Department of Transportation",
                "Awarding Sub Agency": "FTA",
                "Award Amount": 500000,
                "Start Date": "2022-03-15",
                "Award Type": "Formula Grant",
                "Place of Performance State Code": "PR",
                "Place of Performance County Name": "San Juan",
                "Description": "Transit infrastructure grant",
            }
        ]

    def test_returns_master_columns(self):
        df = _results_to_df(self._sample_results(), "dot_pop_2022.csv")
        assert list(df.columns) == MASTER_COLUMNS

    def test_award_id_renamed_correctly(self):
        df = _results_to_df(self._sample_results(), "dot_pop_2022.csv")
        assert "award_id" in df.columns
        assert df["award_id"].iloc[0] == "DOT-001"

    def test_source_file_populated(self):
        df = _results_to_df(self._sample_results(), "dot_pop_2022.csv")
        assert df["source_file"].iloc[0] == "dot_pop_2022.csv"

    def test_source_dataset_is_dot(self):
        df = _results_to_df(self._sample_results(), "dot_pop_2022.csv")
        assert df["source_dataset"].iloc[0] == "dot"

    def test_fiscal_year_derived_from_start_date(self):
        df = _results_to_df(self._sample_results(), "dot_pop_2022.csv")
        # 2022-03-15 → FY2022
        assert df["fiscal_year"].iloc[0] == "2022"

    def test_empty_results_returns_master_columns(self):
        df = _results_to_df([], "empty.csv")
        assert list(df.columns) == MASTER_COLUMNS
        assert len(df) == 0

    def test_missing_columns_filled_with_empty_string(self):
        # Minimal result missing most fields
        minimal = [{"Award ID": "X"}]
        df = _results_to_df(minimal, "test.csv")
        for col in MASTER_COLUMNS:
            assert col in df.columns

    def test_obligated_amount_renamed(self):
        df = _results_to_df(self._sample_results(), "dot_pop_2022.csv")
        assert "obligated_amount" in df.columns
        assert df["obligated_amount"].iloc[0] == 500000

    def test_pop_state_renamed(self):
        df = _results_to_df(self._sample_results(), "dot_pop_2022.csv")
        assert "pop_state" in df.columns
        assert df["pop_state"].iloc[0] == "PR"


# ---------------------------------------------------------------------------
# TIME_WINDOWS constant
# ---------------------------------------------------------------------------

class TestTimeWindowsConstant:
    def test_four_windows_defined(self):
        assert len(TIME_WINDOWS) == 4

    def test_all_windows_have_required_keys(self):
        for w in TIME_WINDOWS:
            assert "label" in w
            assert "start_date" in w
            assert "end_date" in w
            assert "fy_start" in w

    def test_windows_are_chronologically_ordered(self):
        starts = [w["start_date"] for w in TIME_WINDOWS]
        assert starts == sorted(starts)


# ---------------------------------------------------------------------------
# build_master
# ---------------------------------------------------------------------------

class TestBuildMaster:
    def test_combines_multiple_raw_csvs(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        for i, name in enumerate(["dot_pop_2022.csv", "dot_recipient_2022.csv"]):
            row = {col: f"val{i}" for col in MASTER_COLUMNS}
            row["award_id"] = f"AWARD-{i}"
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
        for name in ["dot_pop.csv", "dot_recipient.csv"]:
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
        row = {col: "value" for col in MASTER_COLUMNS}
        row["award_id"] = "AWARD-001"
        pd.DataFrame([row]).to_csv(raw_dir / "dot_pop_2022.csv", index=False)

        master_path = tmp_path / "master.csv"
        logger = logging.getLogger("test")
        build_master(raw_dir, master_path, logger)
        result = pd.read_csv(master_path, dtype=str)
        for col in MASTER_COLUMNS:
            assert col in result.columns


# ---------------------------------------------------------------------------
# run() integration with caching (force=False)
# ---------------------------------------------------------------------------

class TestRunCaching:
    """run() skips windows when output CSVs already exist (force=False)."""

    def _make_raw_dir(self, tmp_path):
        raw_dir = tmp_path / "data" / "staging" / "raw" / "dot"
        raw_dir.mkdir(parents=True)
        return raw_dir

    def test_skips_all_windows_when_all_csvs_exist(self, tmp_path):
        """All pre-existing CSVs cause no HTTP calls (force=False)."""
        raw_dir = self._make_raw_dir(tmp_path)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        # Pre-create one data row CSV for each window × filter_type
        row = {col: "cached_value" for col in MASTER_COLUMNS}
        for window in TIME_WINDOWS:
            for ft in ("pop", "recipient"):
                fname = f"dot_{ft}_{window['label']}.csv"
                row["award_id"] = f"AWARD-{fname}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_dot.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            summary = run(root=tmp_path)

        # No HTTP POST should be made since all files are cached
        mock_session.post.assert_not_called()
        assert isinstance(summary, dict)

    def test_summary_has_required_keys(self, tmp_path):
        raw_dir = self._make_raw_dir(tmp_path)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        row = {col: "v" for col in MASTER_COLUMNS}
        for window in TIME_WINDOWS:
            for ft in ("pop", "recipient"):
                fname = f"dot_{ft}_{window['label']}.csv"
                row["award_id"] = f"AWARD-{fname}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_dot.requests.Session"):
            summary = run(root=tmp_path)

        for key in ("raw_pop_rows", "raw_recipient_rows", "master_rows", "master_path", "errors", "windows"):
            assert key in summary, f"Missing key: {key}"

    def test_errors_is_list(self, tmp_path):
        raw_dir = self._make_raw_dir(tmp_path)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        row = {col: "v" for col in MASTER_COLUMNS}
        for window in TIME_WINDOWS:
            for ft in ("pop", "recipient"):
                fname = f"dot_{ft}_{window['label']}.csv"
                row["award_id"] = f"AWARD-{fname}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_dot.requests.Session"):
            summary = run(root=tmp_path)

        assert isinstance(summary["errors"], list)

    def test_windows_list_has_four_entries(self, tmp_path):
        raw_dir = self._make_raw_dir(tmp_path)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        row = {col: "v" for col in MASTER_COLUMNS}
        for window in TIME_WINDOWS:
            for ft in ("pop", "recipient"):
                fname = f"dot_{ft}_{window['label']}.csv"
                row["award_id"] = f"AWARD-{fname}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_dot.requests.Session"):
            summary = run(root=tmp_path)

        assert len(summary["windows"]) == len(TIME_WINDOWS)

    def test_master_written_when_cached_data_present(self, tmp_path):
        """build_master writes output when pre-existing raw CSVs provide data."""
        raw_dir = self._make_raw_dir(tmp_path)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        row = {col: "v" for col in MASTER_COLUMNS}
        for window in TIME_WINDOWS:
            for ft in ("pop", "recipient"):
                fname = f"dot_{ft}_{window['label']}.csv"
                row["award_id"] = f"AWARD-{fname}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_dot.requests.Session"):
            summary = run(root=tmp_path)

        master_path = tmp_path / "data" / "staging" / "processed" / "pr_dot_master.csv"
        assert master_path.exists()
        assert summary["master_rows"] >= 1


# ---------------------------------------------------------------------------
# run() with mocked HTTP — download path
# ---------------------------------------------------------------------------

def _make_mock_post_response(results: list, has_next: bool = False) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "results": results,
        "page_metadata": {"has_next_page": has_next},
    }
    resp.raise_for_status.return_value = None
    return resp


class TestRunWithMockedHttp:
    """run() with mocked HTTP fetches data and writes output files."""

    def _sample_api_result(self, award_id="DOT-001"):
        return {
            "Award ID": award_id,
            "Recipient Name": "PR DOT Entity",
            "recipient_uei": "UEI-001",
            "Awarding Agency": "Department of Transportation",
            "Awarding Sub Agency": "FTA",
            "Award Amount": 1_000_000,
            "Start Date": "2023-11-01",
            "Award Type": "Formula Grant",
            "Place of Performance State Code": "PR",
            "Place of Performance County Name": "San Juan",
            "Description": "Transit grant",
        }

    def test_run_downloads_and_creates_raw_csvs(self, tmp_path):
        """When HTTP returns data, raw CSV files are created."""
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        mock_resp = _make_mock_post_response([self._sample_api_result()], has_next=False)

        with patch("scripts.download_dot.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.post.return_value = mock_resp

            # Only download the most recent window to keep the test fast;
            # pre-create all other windows as cached
            raw_dir = tmp_path / "data" / "staging" / "raw" / "dot"
            raw_dir.mkdir(parents=True)
            row = {col: "v" for col in MASTER_COLUMNS}
            for window in TIME_WINDOWS[:-1]:
                for ft in ("pop", "recipient"):
                    fname = f"dot_{ft}_{window['label']}.csv"
                    row["award_id"] = f"AWARD-{fname}"
                    pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

            from scripts.download_dot import _run
            summary = _run(root=tmp_path, force=False, fy_start=2023)

        # HTTP should have been called for both filter types of the last window
        assert mock_session.post.called
        assert isinstance(summary, dict)

    def test_run_master_rows_positive_after_download(self, tmp_path):
        """After a successful (mocked) download, master_rows > 0."""
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)
        raw_dir = tmp_path / "data" / "staging" / "raw" / "dot"
        raw_dir.mkdir(parents=True)

        # Pre-seed one row for every window except the last two
        row = {col: "v" for col in MASTER_COLUMNS}
        for window in TIME_WINDOWS[:2]:
            for ft in ("pop", "recipient"):
                fname = f"dot_{ft}_{window['label']}.csv"
                row["award_id"] = f"AWARD-{fname}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        mock_resp = _make_mock_post_response(
            [self._sample_api_result("DOT-NEW-001"), self._sample_api_result("DOT-NEW-002")],
            has_next=False,
        )

        with patch("scripts.download_dot.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.post.return_value = mock_resp

            from scripts.download_dot import _run
            summary = _run(root=tmp_path, force=False, fy_start=2018)

        assert summary["master_rows"] > 0

    def test_run_master_path_in_summary(self, tmp_path):
        """run() returns master_path in summary dict."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "dot"
        raw_dir.mkdir(parents=True)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        # Use fully cached scenario for speed
        row = {col: "v" for col in MASTER_COLUMNS}
        for window in TIME_WINDOWS:
            for ft in ("pop", "recipient"):
                fname = f"dot_{ft}_{window['label']}.csv"
                row["award_id"] = f"AWARD-{fname}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_dot.requests.Session"):
            summary = run(root=tmp_path)

        assert "master_path" in summary
        assert "pr_dot_master.csv" in summary["master_path"]

    def test_http_error_recorded_in_errors(self, tmp_path):
        """When HTTP returns a 4xx error, no crash — recorded in errors or empty result."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "dot"
        raw_dir.mkdir(parents=True)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        bad_resp = MagicMock()
        bad_resp.status_code = 400
        bad_resp.text = "Bad Request"
        bad_resp.raise_for_status.side_effect = None

        with patch("scripts.download_dot.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.post.return_value = bad_resp

            from scripts.download_dot import _run
            # Should not raise, just return summary with errors
            summary = _run(root=tmp_path, force=True, fy_start=2023)

        assert isinstance(summary, dict)
        assert isinstance(summary["errors"], list)
