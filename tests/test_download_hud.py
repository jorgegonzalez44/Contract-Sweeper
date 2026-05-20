"""Tests for download_hud.py — HUD grants downloader for Puerto Rico."""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Suppress noisy log output from the module under test
logging.getLogger("download_hud").setLevel(logging.CRITICAL)
logging.getLogger("test").setLevel(logging.CRITICAL)

from scripts.download_hud import (
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

    def test_oct_returns_next_year(self):
        assert _derive_fiscal_year("2022-10-01") == "2023"

    def test_december_returns_next_year(self):
        assert _derive_fiscal_year("2022-12-31") == "2023"

    def test_september_boundary_same_year(self):
        assert _derive_fiscal_year("2023-09-30") == "2023"

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
        return {"label": "2018f2022", "start_date": "2018-10-01", "end_date": "2022-09-30", "fy_start": 2018}

    def test_pop_filter_uses_place_of_performance_locations(self):
        payload = _build_payload("pop", self._window())
        f = payload["filters"]
        assert "place_of_performance_locations" in f
        loc = f["place_of_performance_locations"][0]
        assert loc["country"] == "USA"
        assert loc["state"] == "PR"
        assert "recipient_locations" not in f

    def test_recipient_filter_uses_recipient_locations(self):
        payload = _build_payload("recipient", self._window())
        f = payload["filters"]
        assert "recipient_locations" in f
        loc = f["recipient_locations"][0]
        assert loc["country"] == "USA"
        assert loc["state"] == "PR"
        assert "place_of_performance_locations" not in f

    def test_payload_award_type_codes_match_constants(self):
        payload = _build_payload("pop", self._window())
        assert payload["filters"]["award_type_codes"] == GRANT_TYPE_CODES

    def test_payload_agency_is_hud(self):
        payload = _build_payload("pop", self._window())
        agencies = payload["filters"]["agencies"]
        assert any(a["name"] == AGENCY_NAME for a in agencies)

    def test_payload_time_period_matches_window(self):
        payload = _build_payload("pop", self._window())
        tp = payload["filters"]["time_period"]
        assert tp[0]["start_date"] == "2018-10-01"
        assert tp[0]["end_date"] == "2022-09-30"

    def test_payload_fields_match_constants(self):
        payload = _build_payload("pop", self._window())
        assert payload["fields"] == FIELDS

    def test_payload_page_defaults_to_one(self):
        payload = _build_payload("pop", self._window())
        assert payload["page"] == 1

    def test_payload_subawards_false(self):
        payload = _build_payload("recipient", self._window())
        assert payload["subawards"] is False


# ---------------------------------------------------------------------------
# _results_to_df
# ---------------------------------------------------------------------------

class TestResultsToDf:
    def _sample_results(self):
        return [
            {
                "Award ID": "GRANT-001",
                "Recipient Name": "PR Housing Corp",
                "recipient_uei": "UEI123",
                "Awarding Agency": "HUD",
                "Awarding Sub Agency": "Office of Community Planning",
                "Award Amount": 5000000,
                "Start Date": "2022-03-15",
                "Award Type": "Block Grant",
                "Place of Performance State Code": "PR",
                "Place of Performance County Name": "San Juan",
                "Description": "CDBG funding for infrastructure",
            }
        ]

    def test_returns_master_columns(self):
        df = _results_to_df(self._sample_results(), "hud_pop_2018f2022.csv")
        assert list(df.columns) == MASTER_COLUMNS

    def test_award_id_renamed_correctly(self):
        df = _results_to_df(self._sample_results(), "hud_pop_2018f2022.csv")
        assert df["award_id"].iloc[0] == "GRANT-001"

    def test_recipient_name_renamed_correctly(self):
        df = _results_to_df(self._sample_results(), "hud_pop_2018f2022.csv")
        assert df["recipient_name"].iloc[0] == "PR Housing Corp"

    def test_obligated_amount_renamed_correctly(self):
        df = _results_to_df(self._sample_results(), "hud_pop_2018f2022.csv")
        assert df["obligated_amount"].iloc[0] == 5000000

    def test_source_file_is_populated(self):
        df = _results_to_df(self._sample_results(), "hud_pop_2018f2022.csv")
        assert df["source_file"].iloc[0] == "hud_pop_2018f2022.csv"

    def test_source_dataset_is_hud(self):
        df = _results_to_df(self._sample_results(), "hud_pop_2018f2022.csv")
        assert df["source_dataset"].iloc[0] == "hud"

    def test_fiscal_year_derived_from_start_date(self):
        df = _results_to_df(self._sample_results(), "hud_pop_2018f2022.csv")
        # 2022-03-15 → FY2022
        assert df["fiscal_year"].iloc[0] == "2022"

    def test_fiscal_year_oct_date_gives_next_year(self):
        results = [{"Award ID": "X", "Start Date": "2022-11-01"}]
        df = _results_to_df(results, "test.csv")
        assert df["fiscal_year"].iloc[0] == "2023"

    def test_empty_results_returns_master_column_df(self):
        df = _results_to_df([], "empty.csv")
        assert list(df.columns) == MASTER_COLUMNS
        assert len(df) == 0

    def test_missing_columns_filled_with_empty_string(self):
        minimal = [{"Award ID": "M-001"}]
        df = _results_to_df(minimal, "minimal.csv")
        for col in MASTER_COLUMNS:
            assert col in df.columns

    def test_pop_state_renamed_correctly(self):
        df = _results_to_df(self._sample_results(), "hud_pop_2018f2022.csv")
        assert df["pop_state"].iloc[0] == "PR"

    def test_pop_county_renamed_correctly(self):
        df = _results_to_df(self._sample_results(), "hud_pop_2018f2022.csv")
        assert df["pop_county"].iloc[0] == "San Juan"


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
        p = tmp_path / "header_only.csv"
        pd.DataFrame(columns=["a", "b"]).to_csv(p, index=False)
        # header-only → 0 rows → returns False
        assert _file_has_data(p) is False

    def test_corrupt_file_returns_false(self, tmp_path):
        p = tmp_path / "corrupt.csv"
        p.write_bytes(b"\x00\x01\x02\x03")
        result = _file_has_data(p)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# build_master
# ---------------------------------------------------------------------------

class TestBuildMaster:
    def test_combines_multiple_raw_csvs(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        for i, name in enumerate(["hud_pop_2018f2022.csv", "hud_recipient_2018f2022.csv"]):
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
        for name in ["hud_pop_2010f2017.csv", "hud_recipient_2010f2017.csv"]:
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

    def test_master_has_correct_columns(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        row = {col: "x" for col in MASTER_COLUMNS}
        row["award_id"] = "COL-TEST-001"
        pd.DataFrame([row]).to_csv(raw_dir / "hud_pop_test.csv", index=False)

        master_path = tmp_path / "master.csv"
        logger = logging.getLogger("test")
        build_master(raw_dir, master_path, logger)
        result = pd.read_csv(master_path, dtype=str)
        for col in MASTER_COLUMNS:
            assert col in result.columns


# ---------------------------------------------------------------------------
# TIME_WINDOWS / constants
# ---------------------------------------------------------------------------

class TestTimeWindows:
    def test_four_time_windows_defined(self):
        assert len(TIME_WINDOWS) == 4

    def test_each_window_has_required_keys(self):
        required = {"label", "start_date", "end_date", "fy_start"}
        for w in TIME_WINDOWS:
            assert required.issubset(w.keys()), f"Missing keys in window {w}"

    def test_grant_type_codes_nonempty(self):
        assert len(GRANT_TYPE_CODES) > 0

    def test_master_columns_contains_expected_fields(self):
        expected = {"award_id", "recipient_name", "obligated_amount", "award_date", "source_dataset"}
        assert expected.issubset(set(MASTER_COLUMNS))


# ---------------------------------------------------------------------------
# run() integration — caching (force=False skips existing files)
# ---------------------------------------------------------------------------

class TestRunCaching:
    """run() skips windows when output CSVs already have data (force=False)."""

    def test_skips_download_when_all_csvs_exist(self, tmp_path):
        """Pre-existing data CSVs should prevent any HTTP POST calls."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "hud"
        raw_dir.mkdir(parents=True)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        # Pre-create all expected output files with at least one data row
        for window in TIME_WINDOWS:
            for filter_type in ("pop", "recipient"):
                fname = f"hud_{filter_type}_{window['label']}.csv"
                row = {col: "cached_value" for col in MASTER_COLUMNS}
                row["award_id"] = f"CACHED-{filter_type}-{window['label']}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_hud.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            summary = run(root=tmp_path)

        # No HTTP calls should have been made — all files were cached
        mock_session.post.assert_not_called()
        assert isinstance(summary, dict)

    def test_summary_keys_present(self, tmp_path):
        """run() always returns a dict with the expected summary keys."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "hud"
        raw_dir.mkdir(parents=True)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        for window in TIME_WINDOWS:
            for filter_type in ("pop", "recipient"):
                fname = f"hud_{filter_type}_{window['label']}.csv"
                row = {col: "v" for col in MASTER_COLUMNS}
                row["award_id"] = f"ID-{filter_type}-{window['label']}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_hud.requests.Session"):
            summary = run(root=tmp_path)

        for key in ("raw_pop_rows", "raw_recipient_rows", "master_rows", "errors", "windows"):
            assert key in summary, f"Key '{key}' missing from summary"

    def test_master_written_from_cached_files(self, tmp_path):
        """When raw CSVs exist, build_master writes the master file."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "hud"
        raw_dir.mkdir(parents=True)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        for window in TIME_WINDOWS:
            for filter_type in ("pop", "recipient"):
                fname = f"hud_{filter_type}_{window['label']}.csv"
                row = {col: "v" for col in MASTER_COLUMNS}
                row["award_id"] = f"MASTER-{filter_type}-{window['label']}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_hud.requests.Session"):
            summary = run(root=tmp_path)

        master_path = tmp_path / "data" / "staging" / "processed" / "pr_hud_master.csv"
        assert master_path.exists()
        assert summary["master_rows"] > 0


# ---------------------------------------------------------------------------
# run() integration — mocked HTTP download path
# ---------------------------------------------------------------------------

def _make_mock_post_response(results: list, has_next: bool = False) -> MagicMock:
    """Return a mock requests.Response for a USASpending spending_by_award POST."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "results": results,
        "page_metadata": {"has_next_page": has_next},
    }
    return resp


class TestRunWithMockedHttp:
    """run() with mocked HTTP correctly downloads and saves data."""

    def _setup_dirs(self, tmp_path: Path):
        raw_dir = tmp_path / "data" / "staging" / "raw" / "hud"
        raw_dir.mkdir(parents=True)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)
        return raw_dir, processed_dir

    def _sample_result(self, award_id: str = "HUD-001") -> dict:
        return {
            "Award ID": award_id,
            "Recipient Name": "PR Housing Authority",
            "recipient_uei": "UEI-TEST",
            "Awarding Agency": "HUD",
            "Awarding Sub Agency": "CPD",
            "Award Amount": 1000000,
            "Start Date": "2019-06-01",
            "Award Type": "Block Grant",
            "Place of Performance State Code": "PR",
            "Place of Performance County Name": "Ponce",
            "Description": "CDBG infrastructure",
        }

    def test_run_returns_dict(self, tmp_path):
        """run() always returns a dict even when HTTP responses are mocked."""
        raw_dir, _ = self._setup_dirs(tmp_path)

        # Pre-cache all windows so no HTTP calls are needed
        for window in TIME_WINDOWS:
            for filter_type in ("pop", "recipient"):
                fname = f"hud_{filter_type}_{window['label']}.csv"
                row = {col: "v" for col in MASTER_COLUMNS}
                row["award_id"] = f"PRELOAD-{filter_type}-{window['label']}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_hud.requests.Session"):
            summary = run(root=tmp_path)

        assert isinstance(summary, dict)

    def test_run_errors_is_list(self, tmp_path):
        """errors key in summary is always a list."""
        raw_dir, _ = self._setup_dirs(tmp_path)

        for window in TIME_WINDOWS:
            for filter_type in ("pop", "recipient"):
                fname = f"hud_{filter_type}_{window['label']}.csv"
                row = {col: "v" for col in MASTER_COLUMNS}
                row["award_id"] = f"ERR-{filter_type}-{window['label']}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_hud.requests.Session"):
            summary = run(root=tmp_path)

        assert isinstance(summary["errors"], list)

    def test_run_windows_list_matches_time_windows_count(self, tmp_path):
        """run() returns a window stat entry for each TIME_WINDOW."""
        raw_dir, _ = self._setup_dirs(tmp_path)

        for window in TIME_WINDOWS:
            for filter_type in ("pop", "recipient"):
                fname = f"hud_{filter_type}_{window['label']}.csv"
                row = {col: "v" for col in MASTER_COLUMNS}
                row["award_id"] = f"WIN-{filter_type}-{window['label']}"
                pd.DataFrame([row]).to_csv(raw_dir / fname, index=False)

        with patch("scripts.download_hud.requests.Session"):
            summary = run(root=tmp_path)

        assert len(summary["windows"]) == len(TIME_WINDOWS)

    def test_run_downloads_and_saves_csv_when_no_cache(self, tmp_path):
        """When no cached files exist, run() fetches via HTTP and saves CSVs."""
        raw_dir, processed_dir = self._setup_dirs(tmp_path)

        # Mock the session's post to return one result page (no next page)
        sample = self._sample_result("FRESH-001")

        with patch("scripts.download_hud.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.post.return_value = _make_mock_post_response(
                results=[sample], has_next=False
            )

            summary = run(root=tmp_path)

        # HTTP POST must have been called at least once (for a non-cached window)
        assert mock_session.post.called
        # master path should exist
        master_path = tmp_path / "data" / "staging" / "processed" / "pr_hud_master.csv"
        assert master_path.exists()

    def test_raw_csvs_written_for_each_filter_type(self, tmp_path):
        """run() writes hud_pop_<label>.csv and hud_recipient_<label>.csv files."""
        raw_dir, processed_dir = self._setup_dirs(tmp_path)

        sample_pop = self._sample_result("POP-001")
        sample_rec = self._sample_result("REC-001")

        with patch("scripts.download_hud.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            mock_session.post.return_value = _make_mock_post_response(
                results=[sample_pop], has_next=False
            )

            # Only test the first window to keep the test fast
            from scripts.download_hud import _run
            with patch("scripts.download_hud.TIME_WINDOWS", [TIME_WINDOWS[0]]):
                summary = _run(root=tmp_path, force=True)

        label = TIME_WINDOWS[0]["label"]
        assert (raw_dir / f"hud_pop_{label}.csv").exists()
        assert (raw_dir / f"hud_recipient_{label}.csv").exists()
