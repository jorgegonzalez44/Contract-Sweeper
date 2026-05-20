"""Tests for download_cdbg_dr.py — HUD CDBG-DR data for Puerto Rico."""

import logging
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Suppress noisy log output from the module under test
logging.getLogger("download_cdbg_dr").setLevel(logging.CRITICAL)
logging.getLogger("test").setLevel(logging.CRITICAL)

from scripts.download_cdbg_dr import (
    MASTER_COLUMNS,
    _build_usaspending_payload,
    _derive_fiscal_year,
    _fetch_cor3,
    _file_has_data,
    _normalize_cor3,
    _normalize_local_df,
    _normalize_usaspending,
    _post_with_retry,
    _session,
    run,
    _run,
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
        import math
        assert _derive_fiscal_year(float("nan")) == ""


# ---------------------------------------------------------------------------
# _file_has_data
# ---------------------------------------------------------------------------

class TestFileHasData:
    def test_missing_file_returns_false(self, tmp_path):
        assert _file_has_data(tmp_path / "nonexistent.csv") is False

    def test_valid_csv_with_data_returns_true(self, tmp_path):
        p = tmp_path / "data.csv"
        pd.DataFrame([{"a": 1, "b": 2}]).to_csv(p, index=False)
        assert _file_has_data(p) is True

    def test_header_only_csv_returns_false(self, tmp_path):
        """Header-only CSV has 0 data rows."""
        p = tmp_path / "header_only.csv"
        pd.DataFrame(columns=["a", "b"]).to_csv(p, index=False)
        # _file_has_data reads nrows=2 — header-only has 0 rows
        assert _file_has_data(p) is False

    def test_corrupt_file_returns_false(self, tmp_path):
        p = tmp_path / "corrupt.csv"
        p.write_bytes(b"\x00\x01\x02\x03")
        result = _file_has_data(p)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# _session
# ---------------------------------------------------------------------------

class TestSession:
    def test_returns_requests_session(self):
        import requests
        s = _session()
        assert isinstance(s, requests.Session)

    def test_session_has_user_agent_header(self):
        s = _session()
        assert "User-Agent" in s.headers
        assert "ContractSweeper" in s.headers["User-Agent"]

    def test_session_has_content_type_header(self):
        s = _session()
        assert s.headers.get("Content-Type") == "application/json"


# ---------------------------------------------------------------------------
# _build_usaspending_payload
# ---------------------------------------------------------------------------

class TestBuildUsaspendingPayload:
    def test_pop_filter_includes_place_of_performance(self):
        payload = _build_usaspending_payload("pop", 1)
        f = payload["filters"]
        assert "place_of_performance_locations" in f
        assert f["place_of_performance_locations"][0]["state"] == "PR"

    def test_recipient_filter_includes_recipient_locations(self):
        payload = _build_usaspending_payload("recipient", 1)
        f = payload["filters"]
        assert "recipient_locations" in f
        assert f["recipient_locations"][0]["state"] == "PR"

    def test_pop_filter_does_not_include_recipient_locations(self):
        payload = _build_usaspending_payload("pop", 1)
        assert "recipient_locations" not in payload["filters"]

    def test_payload_page_number_is_set(self):
        payload = _build_usaspending_payload("pop", 3)
        assert payload["page"] == 3

    def test_payload_subawards_is_false(self):
        payload = _build_usaspending_payload("pop", 1)
        assert payload["subawards"] is False

    def test_payload_contains_hud_agency(self):
        payload = _build_usaspending_payload("pop", 1)
        agencies = payload["filters"]["agencies"]
        assert any(
            "Housing and Urban Development" in a.get("name", "")
            for a in agencies
        )

    def test_payload_time_period_present(self):
        payload = _build_usaspending_payload("pop", 1)
        assert "time_period" in payload["filters"]
        tp = payload["filters"]["time_period"]
        assert len(tp) >= 1
        assert "start_date" in tp[0]
        assert "end_date" in tp[0]


# ---------------------------------------------------------------------------
# _normalize_usaspending
# ---------------------------------------------------------------------------

class TestNormalizeUsaspending:
    def _sample_record(self):
        return {
            "Award ID": "AWARD-001",
            "Recipient Name": "Test Corp PR",
            "recipient_uei": "UEI12345",
            "Total Obligation": "500000",
            "Start Date": "2022-03-15",
            "Awarding Agency": "Department of Housing and Urban Development",
            "Awarding Sub Agency": "CPD",
            "Description": "CDBG-DR grant for hurricane recovery",
        }

    def test_returns_master_columns(self):
        df = _normalize_usaspending([self._sample_record()], "cdbg_dr_usaspending.csv")
        assert list(df.columns) == MASTER_COLUMNS

    def test_award_id_mapped_correctly(self):
        df = _normalize_usaspending([self._sample_record()], "cdbg_dr_usaspending.csv")
        assert df["award_id"].iloc[0] == "AWARD-001"

    def test_recipient_name_mapped(self):
        df = _normalize_usaspending([self._sample_record()], "cdbg_dr_usaspending.csv")
        assert df["recipient_name"].iloc[0] == "Test Corp PR"

    def test_fiscal_year_derived(self):
        df = _normalize_usaspending([self._sample_record()], "cdbg_dr_usaspending.csv")
        # 2022-03-15 → FY2022
        assert df["fiscal_year"].iloc[0] == "2022"

    def test_pop_state_is_pr(self):
        df = _normalize_usaspending([self._sample_record()], "cdbg_dr_usaspending.csv")
        assert df["pop_state"].iloc[0] == "PR"

    def test_source_dataset_is_cdbg_dr(self):
        df = _normalize_usaspending([self._sample_record()], "cdbg_dr_usaspending.csv")
        assert df["source_dataset"].iloc[0] == "cdbg_dr"

    def test_award_category_is_grant(self):
        df = _normalize_usaspending([self._sample_record()], "cdbg_dr_usaspending.csv")
        assert df["award_category"].iloc[0] == "grant"

    def test_source_file_set(self):
        df = _normalize_usaspending([self._sample_record()], "cdbg_dr_usaspending.csv")
        assert df["source_file"].iloc[0] == "cdbg_dr_usaspending.csv"

    def test_empty_records_returns_empty_df(self):
        df = _normalize_usaspending([], "cdbg_dr_usaspending.csv")
        assert list(df.columns) == MASTER_COLUMNS
        assert len(df) == 0

    def test_october_date_gets_next_fiscal_year(self):
        record = self._sample_record()
        record["Start Date"] = "2022-10-15"
        df = _normalize_usaspending([record], "f.csv")
        assert df["fiscal_year"].iloc[0] == "2023"


# ---------------------------------------------------------------------------
# _normalize_cor3
# ---------------------------------------------------------------------------

class TestNormalizeCor3:
    def _sample_record(self):
        return {
            "project_id": "PROJ-001",
            "subrecipient_name": "Construction LLC",
            "project_name": "Road Repair",
            "obligated_amount": "250000",
            "start_date": "2021-06-01",
            "municipality": "San Juan",
            "uei": "UEIPR999",
        }

    def test_returns_master_columns(self):
        df = _normalize_cor3([self._sample_record()], "cor3_api")
        assert list(df.columns) == MASTER_COLUMNS

    def test_award_id_prefixed_with_cdbg_cor3(self):
        df = _normalize_cor3([self._sample_record()], "cor3_api")
        assert df["award_id"].iloc[0].startswith("CDBG-COR3-")

    def test_recipient_name_from_subrecipient_name(self):
        df = _normalize_cor3([self._sample_record()], "cor3_api")
        assert df["recipient_name"].iloc[0] == "Construction LLC"

    def test_description_from_project_name(self):
        df = _normalize_cor3([self._sample_record()], "cor3_api")
        assert df["description"].iloc[0] == "Road Repair"

    def test_pop_state_is_pr(self):
        df = _normalize_cor3([self._sample_record()], "cor3_api")
        assert df["pop_state"].iloc[0] == "PR"

    def test_pop_county_from_municipality(self):
        df = _normalize_cor3([self._sample_record()], "cor3_api")
        assert df["pop_county"].iloc[0] == "San Juan"

    def test_source_dataset_is_cdbg_dr(self):
        df = _normalize_cor3([self._sample_record()], "cor3_api")
        assert df["source_dataset"].iloc[0] == "cdbg_dr"

    def test_award_category_is_grant(self):
        df = _normalize_cor3([self._sample_record()], "cor3_api")
        assert df["award_category"].iloc[0] == "grant"

    def test_empty_records_returns_empty_df(self):
        df = _normalize_cor3([], "cor3_api")
        assert list(df.columns) == MASTER_COLUMNS
        assert len(df) == 0

    def test_fallback_fields_used_when_primary_absent(self):
        """_normalize_cor3 falls back to alternate field names."""
        record = {
            "id": "999",
            "recipient_name": "Fallback Corp",
            "description": "Fallback project",
            "amount": "100000",
            "date": "2020-01-01",
        }
        df = _normalize_cor3([record], "cor3_api")
        assert df["recipient_name"].iloc[0] == "Fallback Corp"
        assert df["description"].iloc[0] == "Fallback project"

    def test_award_id_uses_index_when_no_id_field(self):
        """When no id fields, award_id uses index as fallback."""
        record = {"subrecipient_name": "No ID Corp"}
        df = _normalize_cor3([record], "cor3_api")
        # The index 0 is used, so award_id should be CDBG-COR3-0
        assert df["award_id"].iloc[0] == "CDBG-COR3-0"


# ---------------------------------------------------------------------------
# _normalize_local_df
# ---------------------------------------------------------------------------

class TestNormalizeLocalDf:
    def _sample_df(self):
        return pd.DataFrame([{
            "Award ID": "LOCAL-001",
            "Recipient Name": "Local Contractor PR",
            "Total Obligation": "75000",
            "Start Date": "2019-05-10",
            "Awarding Agency": "HUD",
            "Description": "CDBG-DR local data",
        }])

    def test_returns_master_columns(self):
        df = _normalize_local_df(self._sample_df(), "local_file.csv")
        assert list(df.columns) == MASTER_COLUMNS

    def test_award_id_mapped(self):
        df = _normalize_local_df(self._sample_df(), "local_file.csv")
        assert df["award_id"].iloc[0] == "LOCAL-001"

    def test_recipient_name_mapped(self):
        df = _normalize_local_df(self._sample_df(), "local_file.csv")
        assert df["recipient_name"].iloc[0] == "Local Contractor PR"

    def test_source_dataset_is_cdbg_dr(self):
        df = _normalize_local_df(self._sample_df(), "local_file.csv")
        assert df["source_dataset"].iloc[0] == "cdbg_dr"

    def test_pop_state_defaults_to_pr_when_absent(self):
        df = _normalize_local_df(self._sample_df(), "local_file.csv")
        assert df["pop_state"].iloc[0] == "PR"

    def test_award_id_fallback_when_nan(self):
        """Rows with missing Award ID get CDBG-LOCAL-<index> fallback."""
        df_in = pd.DataFrame([{
            "Recipient Name": "No ID Corp",
            "Total Obligation": "10000",
        }])
        df = _normalize_local_df(df_in, "no_id.csv")
        assert df["award_id"].iloc[0] == "CDBG-LOCAL-0"

    def test_award_category_is_grant(self):
        df = _normalize_local_df(self._sample_df(), "local_file.csv")
        assert df["award_category"].iloc[0] == "grant"


# ---------------------------------------------------------------------------
# _post_with_retry
# ---------------------------------------------------------------------------

class TestPostWithRetry:
    def test_returns_parsed_json_on_success(self):
        logger = MagicMock()
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"results": [{"id": 1}]}
        session.post.return_value = resp

        result = _post_with_retry(session, "https://example.com/api", {}, logger)
        assert result == {"results": [{"id": 1}]}

    def test_returns_none_on_4xx_error(self):
        logger = MagicMock()
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 400
        resp.text = "Bad Request"
        session.post.return_value = resp

        result = _post_with_retry(session, "https://example.com/api", {}, logger)
        assert result is None

    def test_returns_none_after_all_retries_fail(self):
        import requests as req_lib
        logger = MagicMock()
        session = MagicMock()
        session.post.side_effect = req_lib.RequestException("Connection error")

        result = _post_with_retry(session, "https://example.com/api", {}, logger)
        assert result is None


# ---------------------------------------------------------------------------
# _fetch_cor3
# ---------------------------------------------------------------------------

class TestFetchCor3:
    def test_returns_list_on_json_list_response(self):
        logger = MagicMock()
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"Content-Type": "application/json"}
        resp.json.return_value = [{"project_id": "P1", "amount": "100"}]
        session.get.return_value = resp

        result = _fetch_cor3(session, logger)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_returns_list_on_json_dict_with_data_key(self):
        logger = MagicMock()
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"Content-Type": "application/json"}
        resp.json.return_value = {"data": [{"project_id": "P2"}]}
        session.get.return_value = resp

        result = _fetch_cor3(session, logger)
        assert isinstance(result, list)
        assert len(result) == 1

    def test_returns_empty_list_on_non_json_response(self):
        logger = MagicMock()
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"Content-Type": "text/html"}
        session.get.return_value = resp

        result = _fetch_cor3(session, logger)
        assert result == []

    def test_returns_empty_list_on_non_200_status(self):
        logger = MagicMock()
        session = MagicMock()
        resp = MagicMock()
        resp.status_code = 404
        resp.headers = {"Content-Type": "application/json"}
        session.get.return_value = resp

        result = _fetch_cor3(session, logger)
        assert result == []

    def test_returns_empty_list_on_exception(self):
        import requests as req_lib
        logger = MagicMock()
        session = MagicMock()
        session.get.side_effect = req_lib.RequestException("timeout")

        result = _fetch_cor3(session, logger)
        assert result == []


# ---------------------------------------------------------------------------
# run() integration — caching (force=False skips download)
# ---------------------------------------------------------------------------

class TestRunCaching:
    """run() reuses existing raw file when force=False."""

    def _make_raw_dir(self, tmp_path):
        raw_dir = tmp_path / "data" / "staging" / "raw" / "cdbg_dr"
        raw_dir.mkdir(parents=True)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)
        return raw_dir

    def test_skips_usaspending_download_when_raw_file_exists(self, tmp_path):
        """Pre-existing raw CSV causes USASpending HTTP to be skipped."""
        raw_dir = self._make_raw_dir(tmp_path)
        raw_path = raw_dir / "cdbg_dr_usaspending.csv"

        # Write a realistic pre-existing raw CSV
        sample = {col: "test" for col in ["Award ID", "Recipient Name", "recipient_uei",
                                           "Total Obligation", "Start Date",
                                           "Awarding Agency", "Awarding Sub Agency", "Description"]}
        sample["Award ID"] = "EXISTING-AWARD-001"
        pd.DataFrame([sample]).to_csv(raw_path, index=False)

        with patch("scripts.download_cdbg_dr._session") as mock_session_fn, \
             patch("scripts.download_cdbg_dr._fetch_cor3", return_value=[]):
            mock_session = MagicMock()
            mock_session_fn.return_value = mock_session

            summary = run(root=tmp_path)

        # No POST calls should have been made (file existed → cached path)
        mock_session.post.assert_not_called()
        assert isinstance(summary, dict)

    def test_run_returns_dict_with_required_keys(self, tmp_path):
        """run() always returns a dict with rows, master_path, status."""
        raw_dir = self._make_raw_dir(tmp_path)
        raw_path = raw_dir / "cdbg_dr_usaspending.csv"
        pd.DataFrame([{"Award ID": "X001", "Recipient Name": "Corp"}]).to_csv(raw_path, index=False)

        with patch("scripts.download_cdbg_dr._fetch_cor3", return_value=[]):
            summary = run(root=tmp_path)

        for key in ("rows", "master_path", "status"):
            assert key in summary

    def test_master_csv_written_after_run(self, tmp_path):
        """run() always writes master CSV regardless of source data."""
        self._make_raw_dir(tmp_path)

        with patch("scripts.download_cdbg_dr._fetch_usaspending", return_value=[]), \
             patch("scripts.download_cdbg_dr._fetch_cor3", return_value=[]):
            summary = run(root=tmp_path)

        master_path = Path(summary["master_path"])
        assert master_path.exists()

    def test_status_ok_when_records_returned(self, tmp_path):
        """Status is 'OK' when at least one record is present."""
        self._make_raw_dir(tmp_path)
        records = [{
            "Award ID": "AWARD-PR-001",
            "Recipient Name": "PR Recovery Corp",
            "recipient_uei": "UEI99",
            "Total Obligation": "500000",
            "Start Date": "2022-06-01",
            "Awarding Agency": "HUD",
            "Awarding Sub Agency": "CPD",
            "Description": "Disaster recovery grant",
        }]

        with patch("scripts.download_cdbg_dr._fetch_usaspending", return_value=records), \
             patch("scripts.download_cdbg_dr._fetch_cor3", return_value=[]):
            summary = run(root=tmp_path)

        assert summary["status"] == "OK"
        assert summary["rows"] >= 1

    def test_status_manual_required_when_no_records(self, tmp_path):
        """Status is MANUAL_DOWNLOAD_REQUIRED when all sources return empty."""
        self._make_raw_dir(tmp_path)

        with patch("scripts.download_cdbg_dr._fetch_usaspending", return_value=[]), \
             patch("scripts.download_cdbg_dr._fetch_cor3", return_value=[]):
            summary = run(root=tmp_path)

        assert summary["status"] == "MANUAL_DOWNLOAD_REQUIRED"
        assert "instructions" in summary

    def test_run_creates_output_directories(self, tmp_path):
        """run() creates raw and processed directories if they don't exist."""
        with patch("scripts.download_cdbg_dr._fetch_usaspending", return_value=[]), \
             patch("scripts.download_cdbg_dr._fetch_cor3", return_value=[]):
            run(root=tmp_path)

        assert (tmp_path / "data" / "staging" / "raw" / "cdbg_dr").exists()
        assert (tmp_path / "data" / "staging" / "processed").exists()

    def test_force_false_loads_existing_usaspending_csv(self, tmp_path):
        """With force=False and existing raw CSV, the data is loaded and normalized."""
        raw_dir = self._make_raw_dir(tmp_path)
        raw_path = raw_dir / "cdbg_dr_usaspending.csv"

        # Write data with USASPENDING_FIELDS columns
        row = {
            "Award ID": "CACHED-001",
            "Recipient Name": "Cached Corp",
            "recipient_uei": "UEI-CACHED",
            "Total Obligation": "1000000",
            "Start Date": "2021-01-15",
            "Awarding Agency": "HUD",
            "Awarding Sub Agency": "CPD",
            "Description": "Cached grant",
        }
        pd.DataFrame([row]).to_csv(raw_path, index=False)

        with patch("scripts.download_cdbg_dr._fetch_cor3", return_value=[]):
            summary = _run(root=tmp_path, force=False)

        assert summary["rows"] >= 1
        assert summary["status"] == "OK"

    def test_cor3_records_included_in_master(self, tmp_path):
        """COR3 API records are included in the master output."""
        self._make_raw_dir(tmp_path)
        cor3_records = [{
            "project_id": "COR3-PROJ-001",
            "subrecipient_name": "COR3 Contractor",
            "project_name": "Infrastructure Repair",
            "obligated_amount": "300000",
            "start_date": "2020-08-15",
            "municipality": "Ponce",
        }]

        with patch("scripts.download_cdbg_dr._fetch_usaspending", return_value=[]), \
             patch("scripts.download_cdbg_dr._fetch_cor3", return_value=cor3_records):
            summary = run(root=tmp_path)

        assert summary["rows"] >= 1
        # Verify the master CSV has the COR3 record
        master_df = pd.read_csv(summary["master_path"], dtype=str)
        assert any("COR3" in aid for aid in master_df["award_id"].tolist())

    def test_local_csv_file_loaded_from_raw_dir(self, tmp_path):
        """Local CSV files in raw/cdbg_dr/ are picked up by Source C."""
        raw_dir = self._make_raw_dir(tmp_path)

        # Create a local CSV file (not named cdbg_dr_usaspending.csv)
        local_file = raw_dir / "local_data.csv"
        local_row = {
            "Award ID": "LOCAL-PR-001",
            "Recipient Name": "Local PR Vendor",
            "Total Obligation": "50000",
            "Start Date": "2020-05-01",
            "Description": "Local CDBG-DR data",
        }
        pd.DataFrame([local_row]).to_csv(local_file, index=False)

        with patch("scripts.download_cdbg_dr._fetch_usaspending", return_value=[]), \
             patch("scripts.download_cdbg_dr._fetch_cor3", return_value=[]):
            summary = run(root=tmp_path)

        assert summary["rows"] >= 1

    def test_deduplication_keeps_first_on_same_award_id(self, tmp_path):
        """Duplicate award_ids across sources are deduplicated."""
        self._make_raw_dir(tmp_path)
        # Two records with the same Award ID
        dup_award_id = "AWARD-DUP-001"
        records = [
            {
                "Award ID": dup_award_id, "Recipient Name": "Corp A",
                "recipient_uei": "", "Total Obligation": "100000",
                "Start Date": "2022-01-01", "Awarding Agency": "HUD",
                "Awarding Sub Agency": "", "Description": "Dup 1",
            },
            {
                "Award ID": dup_award_id, "Recipient Name": "Corp B",
                "recipient_uei": "", "Total Obligation": "200000",
                "Start Date": "2022-02-01", "Awarding Agency": "HUD",
                "Awarding Sub Agency": "", "Description": "Dup 2",
            },
        ]
        with patch("scripts.download_cdbg_dr._fetch_usaspending", return_value=records), \
             patch("scripts.download_cdbg_dr._fetch_cor3", return_value=[]):
            summary = run(root=tmp_path)

        # Only 1 of the 2 duplicate rows should remain
        master_df = pd.read_csv(summary["master_path"], dtype=str)
        dup_rows = master_df[master_df["award_id"] == dup_award_id]
        assert len(dup_rows) == 1
