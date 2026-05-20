"""Tests for scripts/download_fec.py — FEC Schedule A contributions from Puerto Rico."""

import logging
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Suppress noisy log output from the module under test
logging.getLogger("download_fec").setLevel(logging.CRITICAL)
logging.getLogger("test").setLevel(logging.CRITICAL)

from scripts.download_fec import (
    OUTPUT_COLUMNS,
    PAGE_SIZE,
    START_CYCLE,
    _current_fec_cycle,
    _fetch_cycle,
    _get,
    _session,
    run,
)


# ---------------------------------------------------------------------------
# _current_fec_cycle
# ---------------------------------------------------------------------------

class TestCurrentFecCycle:
    def test_returns_even_year(self):
        cycle = _current_fec_cycle()
        assert cycle % 2 == 0

    def test_returns_integer(self):
        cycle = _current_fec_cycle()
        assert isinstance(cycle, int)

    def test_returns_recent_year(self):
        cycle = _current_fec_cycle()
        assert cycle >= 2024


# ---------------------------------------------------------------------------
# OUTPUT_COLUMNS constant
# ---------------------------------------------------------------------------

class TestOutputColumns:
    def test_output_columns_is_list(self):
        assert isinstance(OUTPUT_COLUMNS, list)

    def test_output_columns_not_empty(self):
        assert len(OUTPUT_COLUMNS) > 0

    def test_required_columns_present(self):
        required = [
            "cycle",
            "contributor_name",
            "contribution_receipt_amount",
            "contribution_receipt_date",
            "committee_id",
            "is_individual",
        ]
        for col in required:
            assert col in OUTPUT_COLUMNS, f"Expected column '{col}' in OUTPUT_COLUMNS"

    def test_is_individual_column_present(self):
        assert "is_individual" in OUTPUT_COLUMNS

    def test_cycle_column_present(self):
        assert "cycle" in OUTPUT_COLUMNS


# ---------------------------------------------------------------------------
# _session
# ---------------------------------------------------------------------------

class TestSession:
    def test_session_returns_session_object(self):
        import requests
        sess = _session("DEMO_KEY")
        assert isinstance(sess, requests.Session)

    def test_session_sets_user_agent(self):
        sess = _session("DEMO_KEY")
        assert "User-Agent" in sess.headers
        assert "ContractSweeper" in sess.headers["User-Agent"]

    def test_session_sets_api_key_header(self):
        sess = _session("MY_TEST_KEY")
        assert sess.headers.get("X-Api-Key") == "MY_TEST_KEY"

    def test_session_sets_accept_json(self):
        sess = _session("DEMO_KEY")
        assert "application/json" in sess.headers.get("Accept", "")


# ---------------------------------------------------------------------------
# _get — network helper
# ---------------------------------------------------------------------------

class TestGet:
    def _make_logger(self):
        return logging.getLogger("test")

    def test_returns_json_on_200(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": [], "pagination": {"pages": 1, "count": 0}}
        mock_resp.raise_for_status.return_value = None
        mock_session.get.return_value = mock_resp

        with patch("scripts.download_fec.time.sleep"):
            result = _get(mock_session, "https://example.com", {}, self._make_logger(), 0)

        assert result is not None
        assert "results" in result

    def test_returns_none_on_404(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_session.get.return_value = mock_resp

        with patch("scripts.download_fec.time.sleep"):
            result = _get(mock_session, "https://example.com", {}, self._make_logger(), 0)

        assert result is None

    def test_returns_none_after_all_retries_fail(self):
        import requests as req_lib
        mock_session = MagicMock()
        mock_session.get.side_effect = req_lib.RequestException("Connection refused")

        with patch("scripts.download_fec.time.sleep"):
            result = _get(mock_session, "https://example.com", {}, self._make_logger(), 0)

        assert result is None

    def test_retries_on_request_exception(self):
        import requests as req_lib
        mock_session = MagicMock()
        # First two calls fail, third succeeds
        good_resp = MagicMock()
        good_resp.status_code = 200
        good_resp.json.return_value = {"results": [], "pagination": {"pages": 1, "count": 0}}
        good_resp.raise_for_status.return_value = None
        mock_session.get.side_effect = [
            req_lib.RequestException("timeout"),
            req_lib.RequestException("timeout"),
            good_resp,
        ]

        with patch("scripts.download_fec.time.sleep"):
            result = _get(mock_session, "https://example.com", {}, self._make_logger(), 0)

        assert result is not None
        assert mock_session.get.call_count == 3


# ---------------------------------------------------------------------------
# _fetch_cycle
# ---------------------------------------------------------------------------

class TestFetchCycle:
    def _make_logger(self):
        return logging.getLogger("test")

    def _make_api_response(self, results, total_pages=1, count=None):
        if count is None:
            count = len(results)
        return {
            "results": results,
            "pagination": {"pages": total_pages, "count": count},
        }

    def _make_fec_record(self, name="Test Contributor", amount="500.00", cycle=2022):
        return {
            "contributor_name": name,
            "contributor_city": "San Juan",
            "contributor_zip_code": "00901",
            "contributor_employer": "Test Corp",
            "contributor_occupation": "Engineer",
            "contribution_receipt_amount": amount,
            "contribution_receipt_date": "2022-03-15",
            "committee_id": "C00123456",
            "committee": {"name": "Test Committee"},
            "candidate_id": "P00000001",
            "candidate": {"name": "Test Candidate"},
            "report_year": "2022",
            "election_type": "G",
            "memo_text": "",
            "entity_type": "IND",
        }

    def test_returns_list(self):
        mock_session = MagicMock()
        with patch("scripts.download_fec._get", return_value=None):
            result = _fetch_cycle(mock_session, 2022, 0, self._make_logger())
        assert isinstance(result, list)

    def test_returns_empty_on_none_response(self):
        mock_session = MagicMock()
        with patch("scripts.download_fec._get", return_value=None):
            result = _fetch_cycle(mock_session, 2022, 0, self._make_logger())
        assert result == []

    def test_returns_empty_on_empty_results(self):
        mock_session = MagicMock()
        with patch("scripts.download_fec._get", return_value=self._make_api_response([])):
            result = _fetch_cycle(mock_session, 2022, 0, self._make_logger())
        assert result == []

    def test_maps_record_fields_correctly(self):
        mock_session = MagicMock()
        rec = self._make_fec_record("Jane Doe", "1000.00", 2022)
        api_resp = self._make_api_response([rec])
        with patch("scripts.download_fec._get", return_value=api_resp):
            result = _fetch_cycle(mock_session, 2022, 0, self._make_logger())
        assert len(result) == 1
        row = result[0]
        assert row["contributor_name"] == "Jane Doe"
        assert row["contribution_receipt_amount"] == "1000.00"
        assert row["cycle"] == 2022
        assert row["committee_name"] == "Test Committee"
        assert row["candidate_name"] == "Test Candidate"

    def test_is_individual_true_for_ind_entity_type(self):
        mock_session = MagicMock()
        rec = self._make_fec_record()
        rec["entity_type"] = "IND"
        api_resp = self._make_api_response([rec])
        with patch("scripts.download_fec._get", return_value=api_resp):
            result = _fetch_cycle(mock_session, 2022, 0, self._make_logger())
        assert result[0]["is_individual"] is True

    def test_is_individual_false_for_org_entity_type(self):
        mock_session = MagicMock()
        rec = self._make_fec_record()
        rec["entity_type"] = "ORG"
        api_resp = self._make_api_response([rec])
        with patch("scripts.download_fec._get", return_value=api_resp):
            result = _fetch_cycle(mock_session, 2022, 0, self._make_logger())
        assert result[0]["is_individual"] is False

    def test_handles_missing_committee_and_candidate(self):
        """Records with no committee/candidate nested dicts should not crash."""
        mock_session = MagicMock()
        rec = {
            "contributor_name": "Anonymous",
            "committee_id": "C00999",
            "committee": None,
            "candidate": None,
            "contribution_receipt_amount": "100",
            "contribution_receipt_date": "2022-01-01",
            "entity_type": "",
        }
        api_resp = self._make_api_response([rec])
        with patch("scripts.download_fec._get", return_value=api_resp):
            result = _fetch_cycle(mock_session, 2022, 0, self._make_logger())
        assert len(result) == 1
        assert result[0]["committee_name"] == ""
        assert result[0]["candidate_name"] == ""

    def test_paginates_across_multiple_pages(self):
        mock_session = MagicMock()
        page1_resp = {
            "results": [self._make_fec_record("Donor A")],
            "pagination": {"pages": 2, "count": 2},
        }
        page2_resp = {
            "results": [self._make_fec_record("Donor B")],
            "pagination": {"pages": 2, "count": 2},
        }
        with patch("scripts.download_fec._get", side_effect=[page1_resp, page2_resp]):
            result = _fetch_cycle(mock_session, 2022, 0, self._make_logger())
        assert len(result) == 2
        names = {r["contributor_name"] for r in result}
        assert "Donor A" in names
        assert "Donor B" in names


# ---------------------------------------------------------------------------
# run() — caching (force=False skips download when raw file exists)
# ---------------------------------------------------------------------------

class TestRunCaching:
    def _make_raw_dir(self, tmp_path):
        raw_dir = tmp_path / "data" / "staging" / "raw" / "fec"
        raw_dir.mkdir(parents=True)
        return raw_dir

    def _make_processed_dir(self, tmp_path):
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)
        return processed_dir

    def test_skips_http_when_raw_file_exists(self, tmp_path):
        """When raw CSV already exists and force=False, no HTTP calls are made."""
        raw_dir = self._make_raw_dir(tmp_path)
        self._make_processed_dir(tmp_path)

        # Pre-create the raw file with some data
        raw_path = raw_dir / "fec_pr_contributions.csv"
        sample = pd.DataFrame([{col: "x" for col in OUTPUT_COLUMNS}])
        sample["is_individual"] = "True"
        sample.to_csv(raw_path, index=False)

        with patch("scripts.download_fec._session") as mock_session_fn:
            summary = run(root=tmp_path, force=False)

        # _session should never have been called (no HTTP needed)
        mock_session_fn.assert_not_called()
        assert isinstance(summary, dict)

    def test_returns_summary_dict_on_cache_hit(self, tmp_path):
        """run() with cached raw file returns a proper summary dict."""
        raw_dir = self._make_raw_dir(tmp_path)
        self._make_processed_dir(tmp_path)

        raw_path = raw_dir / "fec_pr_contributions.csv"
        sample_row = {col: "" for col in OUTPUT_COLUMNS}
        sample_row["contributor_name"] = "Cache Hit Donor"
        sample_row["committee_id"] = "C00111111"
        sample_row["contribution_receipt_date"] = "2022-01-01"
        sample_row["contribution_receipt_amount"] = "250.00"
        pd.DataFrame([sample_row]).to_csv(raw_path, index=False)

        summary = run(root=tmp_path, force=False)

        assert "rows" in summary
        assert "raw_rows" in summary
        assert "status" in summary

    def test_status_ok_when_data_present(self, tmp_path):
        raw_dir = self._make_raw_dir(tmp_path)
        self._make_processed_dir(tmp_path)

        raw_path = raw_dir / "fec_pr_contributions.csv"
        sample_row = {col: "" for col in OUTPUT_COLUMNS}
        sample_row["contributor_name"] = "Donor X"
        sample_row["committee_id"] = "C00222222"
        sample_row["contribution_receipt_date"] = "2022-06-01"
        sample_row["contribution_receipt_amount"] = "100.00"
        pd.DataFrame([sample_row]).to_csv(raw_path, index=False)

        summary = run(root=tmp_path, force=False)
        assert summary["status"] == "OK"

    def test_master_csv_written_on_cache_hit(self, tmp_path):
        """Master CSV is written from cached raw file."""
        raw_dir = self._make_raw_dir(tmp_path)
        self._make_processed_dir(tmp_path)

        raw_path = raw_dir / "fec_pr_contributions.csv"
        sample_row = {col: "" for col in OUTPUT_COLUMNS}
        sample_row["contributor_name"] = "Donor Y"
        sample_row["committee_id"] = "C00333333"
        sample_row["contribution_receipt_date"] = "2022-03-10"
        sample_row["contribution_receipt_amount"] = "500.00"
        pd.DataFrame([sample_row]).to_csv(raw_path, index=False)

        run(root=tmp_path, force=False)

        master_path = tmp_path / "data" / "staging" / "processed" / "pr_fec_contributions.csv"
        assert master_path.exists()
        df = pd.read_csv(master_path, dtype=str)
        assert list(df.columns) == OUTPUT_COLUMNS


# ---------------------------------------------------------------------------
# run() — mocked HTTP download path (force=True)
# ---------------------------------------------------------------------------

class TestRunWithMockedHttp:
    def _api_response(self, records, total_pages=1, count=None):
        if count is None:
            count = len(records)
        return {
            "results": records,
            "pagination": {"pages": total_pages, "count": count},
        }

    def _make_fec_record(self, name="Test Donor"):
        return {
            "contributor_name": name,
            "contributor_city": "San Juan",
            "contributor_zip_code": "00901",
            "contributor_employer": "Employer Inc",
            "contributor_occupation": "Consultant",
            "contribution_receipt_amount": "1500.00",
            "contribution_receipt_date": "2022-05-01",
            "committee_id": "C00777777",
            "committee": {"name": "Committee ABC"},
            "candidate_id": "P00000099",
            "candidate": {"name": "Candidate Z"},
            "report_year": "2022",
            "election_type": "P",
            "memo_text": None,
            "entity_type": "IND",
        }

    def test_run_returns_dict_with_required_keys(self, tmp_path):
        """run(force=True) with mocked HTTP returns dict with required keys."""
        (tmp_path / "data" / "staging" / "raw" / "fec").mkdir(parents=True)
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)

        api_resp = self._api_response([self._make_fec_record()])
        empty_resp = self._api_response([])

        mock_session = MagicMock()
        # First call returns one record, subsequent calls return empty (end pagination)
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.raise_for_status.return_value = None
        mock_get_resp.json.side_effect = [api_resp] + [empty_resp] * 50

        mock_session.get.return_value = mock_get_resp

        with patch("scripts.download_fec._session", return_value=mock_session), \
             patch("scripts.download_fec.time.sleep"):
            summary = run(root=tmp_path, force=True)

        assert isinstance(summary, dict)
        assert "rows" in summary
        assert "raw_rows" in summary
        assert "status" in summary

    def test_run_writes_raw_csv_when_records_fetched(self, tmp_path):
        """run(force=True) writes raw CSV when records are returned by the API."""
        (tmp_path / "data" / "staging" / "raw" / "fec").mkdir(parents=True)
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)

        api_resp = self._api_response([self._make_fec_record("PR Donor")])
        empty_resp = self._api_response([])

        mock_session = MagicMock()
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.raise_for_status.return_value = None
        mock_get_resp.json.side_effect = [api_resp] + [empty_resp] * 50
        mock_session.get.return_value = mock_get_resp

        with patch("scripts.download_fec._session", return_value=mock_session), \
             patch("scripts.download_fec.time.sleep"):
            run(root=tmp_path, force=True)

        raw_path = tmp_path / "data" / "staging" / "raw" / "fec" / "fec_pr_contributions.csv"
        assert raw_path.exists()

    def test_run_empty_when_no_api_records(self, tmp_path):
        """run(force=True) returns EMPTY status when API returns no records."""
        (tmp_path / "data" / "staging" / "raw" / "fec").mkdir(parents=True)
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)

        empty_resp = self._api_response([])
        mock_session = MagicMock()
        mock_get_resp = MagicMock()
        mock_get_resp.status_code = 200
        mock_get_resp.raise_for_status.return_value = None
        mock_get_resp.json.return_value = empty_resp
        mock_session.get.return_value = mock_get_resp

        with patch("scripts.download_fec._session", return_value=mock_session), \
             patch("scripts.download_fec.time.sleep"):
            summary = run(root=tmp_path, force=True)

        assert summary["status"] == "EMPTY"
        assert summary["rows"] == 0

    def test_run_deduplicates_records(self, tmp_path):
        """run() deduplicates contributions with same name/committee/date/amount."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "fec"
        raw_dir.mkdir(parents=True)
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)

        # Pre-create raw file with duplicate rows
        dup_row = {col: "" for col in OUTPUT_COLUMNS}
        dup_row["contributor_name"] = "Dup Donor"
        dup_row["committee_id"] = "C00444444"
        dup_row["contribution_receipt_date"] = "2022-07-04"
        dup_row["contribution_receipt_amount"] = "200.00"

        raw_path = raw_dir / "fec_pr_contributions.csv"
        pd.DataFrame([dup_row, dup_row]).to_csv(raw_path, index=False)

        summary = run(root=tmp_path, force=False)

        # raw_rows is before dedup, rows is after
        assert summary["raw_rows"] == 2
        assert summary["rows"] == 1

    def test_master_csv_has_output_columns(self, tmp_path):
        """Master CSV produced by run() has exactly the OUTPUT_COLUMNS."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "fec"
        raw_dir.mkdir(parents=True)
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)

        sample_row = {col: "" for col in OUTPUT_COLUMNS}
        sample_row["contributor_name"] = "Output Col Donor"
        sample_row["committee_id"] = "C00555555"
        sample_row["contribution_receipt_date"] = "2022-08-08"
        sample_row["contribution_receipt_amount"] = "750.00"
        raw_path = raw_dir / "fec_pr_contributions.csv"
        pd.DataFrame([sample_row]).to_csv(raw_path, index=False)

        run(root=tmp_path, force=False)

        master_path = tmp_path / "data" / "staging" / "processed" / "pr_fec_contributions.csv"
        df = pd.read_csv(master_path, dtype=str)
        assert list(df.columns) == OUTPUT_COLUMNS


# ---------------------------------------------------------------------------
# START_CYCLE constant
# ---------------------------------------------------------------------------

class TestStartCycle:
    def test_start_cycle_is_2000(self):
        assert START_CYCLE == 2000

    def test_start_cycle_is_even(self):
        assert START_CYCLE % 2 == 0

    def test_end_cycle_gte_start_cycle(self):
        from scripts.download_fec import END_CYCLE
        assert END_CYCLE >= START_CYCLE

    def test_page_size_positive(self):
        assert PAGE_SIZE > 0
        assert PAGE_SIZE <= 100
