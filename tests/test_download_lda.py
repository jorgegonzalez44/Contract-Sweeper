"""Tests for scripts/download_lda.py — LDA Senate lobbying disclosure downloader."""

import logging
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Suppress log noise during tests
logging.getLogger("download_lda").setLevel(logging.CRITICAL)

from scripts.download_lda import (
    _flatten,
    _get,
    _fetch_pass,
    run,
    OUTPUT_COLUMNS,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_logger():
    """Return a silent logger for use in tested functions."""
    log = logging.getLogger("test_lda")
    log.setLevel(logging.CRITICAL)
    return log


def _make_filing(**overrides) -> dict:
    """Return a minimal LDA filing dict."""
    base = {
        "filing_uuid": "uuid-001",
        "filing_year": 2023,
        "filing_type": "Q1",
        "period_of_report": "2023-03-31",
        "income": "50000.00",
        "expenses": "",
        "dt_posted": "2023-04-15T10:00:00Z",
        "registrant": {
            "id": 42,
            "name": "Lobby Firm Inc.",
            "state": "PR",
            "address": {},
        },
        "client": {
            "id": 7,
            "name": "PR Government",
            "state": "PR",
            "general_description": "Puerto Rico government entity",
            "address": {},
        },
        "lobbying_activities": [
            {
                "general_issue_code_display": "TAX",
                "description": "Federal tax reform matters",
                "lobbyists": [
                    {"lobbyist": {"name": "Jane Doe"}, "name": "Jane Doe"},
                ],
            }
        ],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests for _flatten
# ---------------------------------------------------------------------------

class TestFlatten:
    def test_basic_field_extraction(self):
        rec = _make_filing()
        result = _flatten(rec)
        assert result["filing_uuid"] == "uuid-001"
        assert result["filing_year"] == 2023
        assert result["filing_type"] == "Q1"
        assert result["period_of_report"] == "2023-03-31"
        assert result["income"] == "50000.00"
        assert result["dt_posted"] == "2023-04-15T10:00:00Z"

    def test_registrant_fields_extracted(self):
        rec = _make_filing()
        result = _flatten(rec)
        assert result["registrant_id"] == 42
        assert result["registrant_name"] == "Lobby Firm Inc."
        assert result["registrant_state"] == "PR"

    def test_client_fields_extracted(self):
        rec = _make_filing()
        result = _flatten(rec)
        assert result["client_id"] == 7
        assert result["client_name"] == "PR Government"
        assert result["client_state"] == "PR"
        assert result["client_description"] == "Puerto Rico government entity"

    def test_issue_codes_and_descriptions(self):
        rec = _make_filing()
        result = _flatten(rec)
        assert "TAX" in result["general_issue_codes"]
        assert "Federal tax reform" in result["issue_descriptions"]

    def test_lobbyist_names_joined(self):
        rec = _make_filing()
        result = _flatten(rec)
        assert "Jane Doe" in result["lobbyist_names"]

    def test_multiple_activities_joined_with_pipe(self):
        rec = _make_filing()
        rec["lobbying_activities"] = [
            {"general_issue_code_display": "TAX", "description": "Tax stuff", "lobbyists": []},
            {"general_issue_code_display": "HCR", "description": "Health stuff", "lobbyists": []},
        ]
        result = _flatten(rec)
        assert "TAX" in result["general_issue_codes"]
        assert "HCR" in result["general_issue_codes"]
        assert "|" in result["general_issue_codes"]

    def test_deduplication_of_issue_codes(self):
        rec = _make_filing()
        rec["lobbying_activities"] = [
            {"general_issue_code_display": "TAX", "description": "A", "lobbyists": []},
            {"general_issue_code_display": "TAX", "description": "B", "lobbyists": []},
        ]
        result = _flatten(rec)
        codes = result["general_issue_codes"].split("|")
        assert codes.count("TAX") == 1

    def test_missing_registrant_handled(self):
        rec = _make_filing()
        rec["registrant"] = None
        result = _flatten(rec)
        assert result["registrant_id"] == ""
        assert result["registrant_name"] == ""
        assert result["registrant_state"] == ""

    def test_missing_client_handled(self):
        rec = _make_filing()
        rec["client"] = None
        result = _flatten(rec)
        assert result["client_id"] == ""
        assert result["client_name"] == ""
        assert result["client_state"] == ""

    def test_state_falls_back_to_address(self):
        rec = _make_filing()
        rec["registrant"] = {"id": 1, "name": "Firm", "state": None, "address": {"state": "VA"}}
        rec["client"] = {"id": 2, "name": "Client", "state": None, "address": {"state": "DC"},
                         "general_description": ""}
        result = _flatten(rec)
        assert result["registrant_state"] == "VA"
        assert result["client_state"] == "DC"

    def test_empty_activities_gives_empty_strings(self):
        rec = _make_filing()
        rec["lobbying_activities"] = []
        result = _flatten(rec)
        assert result["general_issue_codes"] == ""
        assert result["issue_descriptions"] == ""
        assert result["lobbyist_names"] == ""

    def test_client_description_truncated_to_200(self):
        long_desc = "X" * 300
        rec = _make_filing()
        rec["client"]["general_description"] = long_desc
        result = _flatten(rec)
        assert len(result["client_description"]) == 200

    def test_output_has_all_required_columns(self):
        rec = _make_filing()
        result = _flatten(rec)
        for col in OUTPUT_COLUMNS:
            assert col in result, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# Tests for _get (the HTTP helper)
# ---------------------------------------------------------------------------

class TestGet:
    def _make_session(self):
        session = MagicMock()
        return session

    def test_successful_response_returns_json(self):
        session = self._make_session()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"count": 1, "results": [{"filing_uuid": "abc"}]}
        mock_resp.raise_for_status.return_value = None
        session.get.return_value = mock_resp

        with patch("scripts.download_lda.time.sleep"):
            result = _get(session, "http://example.com", {}, _make_logger())

        assert result == {"count": 1, "results": [{"filing_uuid": "abc"}]}

    def test_404_returns_none(self):
        session = self._make_session()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        session.get.return_value = mock_resp

        with patch("scripts.download_lda.time.sleep"):
            result = _get(session, "http://example.com", {}, _make_logger())

        assert result is None

    def test_timeout_returns_none_no_exception(self):
        import requests as req
        session = self._make_session()
        session.get.side_effect = req.exceptions.Timeout("timed out")

        with patch("scripts.download_lda.time.sleep"):
            result = _get(session, "http://example.com", {}, _make_logger())

        assert result is None

    def test_connection_error_returns_none(self):
        import requests as req
        session = self._make_session()
        session.get.side_effect = req.exceptions.ConnectionError("connection refused")

        with patch("scripts.download_lda.time.sleep"):
            result = _get(session, "http://example.com", {}, _make_logger())

        assert result is None


# ---------------------------------------------------------------------------
# Tests for _fetch_pass
# ---------------------------------------------------------------------------

class TestFetchPass:
    def test_successful_single_page(self):
        session = MagicMock()
        page_data = {
            "count": 1,
            "results": [_make_filing()],
            "next": None,
        }
        with patch("scripts.download_lda._get", return_value=page_data):
            records = _fetch_pass(session, "client_state", _make_logger())
        assert len(records) == 1
        assert records[0]["filing_uuid"] == "uuid-001"

    def test_failed_get_returns_empty(self):
        session = MagicMock()
        with patch("scripts.download_lda._get", return_value=None):
            records = _fetch_pass(session, "client_state", _make_logger())
        assert records == []

    def test_empty_results_returns_empty(self):
        session = MagicMock()
        page_data = {"count": 0, "results": [], "next": None}
        with patch("scripts.download_lda._get", return_value=page_data):
            records = _fetch_pass(session, "registrant_state", _make_logger())
        assert records == []

    def test_multiple_pages_collected(self):
        session = MagicMock()
        page1 = {
            "count": 2,
            "results": [_make_filing(filing_uuid="A"), _make_filing(filing_uuid="B")],
            "next": "http://example.com?page=2",
        }
        page2 = {
            "count": 2,
            "results": [_make_filing(filing_uuid="C")],
            "next": None,
        }
        with patch("scripts.download_lda._get", side_effect=[page1, page2]):
            records = _fetch_pass(session, "client_state", _make_logger())
        assert len(records) == 3
        uuids = [r["filing_uuid"] for r in records]
        assert "A" in uuids and "B" in uuids and "C" in uuids


# ---------------------------------------------------------------------------
# Tests for run() — integration with mocked HTTP
# ---------------------------------------------------------------------------

class TestRun:
    def _make_api_response(self, filings):
        return {
            "count": len(filings),
            "results": filings,
            "next": None,
        }

    def test_run_creates_output_files(self, tmp_path):
        """run() produces processed CSV when API returns data."""
        filing = _make_filing()
        api_resp = self._make_api_response([filing])

        with patch("scripts.download_lda._get", return_value=api_resp), \
             patch("scripts.download_lda.time.sleep"), \
             patch("scripts.download_lda.setup_logging", return_value=_make_logger()):
            result = run(root=tmp_path, force=True)

        assert result["status"] == "OK"
        out_path = tmp_path / "data" / "staging" / "processed" / "pr_lda_filings.csv"
        assert out_path.exists()

    def test_run_returns_correct_row_count(self, tmp_path):
        """run() row count matches deduplicated filings returned by API."""
        filings = [_make_filing(filing_uuid=f"uuid-{i}") for i in range(3)]
        api_resp = self._make_api_response(filings)

        with patch("scripts.download_lda._get", return_value=api_resp), \
             patch("scripts.download_lda.time.sleep"), \
             patch("scripts.download_lda.setup_logging", return_value=_make_logger()):
            result = run(root=tmp_path, force=True)

        # Both passes return the same 3 unique filings → deduped to 3
        assert result["rows"] >= 1

    def test_run_empty_api_returns_empty_status(self, tmp_path):
        """run() returns EMPTY when API has no results."""
        api_resp = {"count": 0, "results": [], "next": None}

        with patch("scripts.download_lda._get", return_value=api_resp), \
             patch("scripts.download_lda.time.sleep"), \
             patch("scripts.download_lda.setup_logging", return_value=_make_logger()):
            result = run(root=tmp_path, force=True)

        assert result["status"] == "EMPTY"
        assert result["rows"] == 0

    def test_run_uses_cached_file_if_exists(self, tmp_path):
        """run() loads from existing raw file instead of re-downloading."""
        import pandas as pd

        raw_dir = tmp_path / "data" / "staging" / "raw" / "lda"
        raw_dir.mkdir(parents=True)
        raw_path = raw_dir / "lda_pr_filings.csv"

        # Write a minimal pre-existing raw CSV
        df = pd.DataFrame([_flatten(_make_filing(filing_uuid="cached-uuid"))])
        df.to_csv(raw_path, index=False)

        with patch("scripts.download_lda._get") as mock_get, \
             patch("scripts.download_lda.setup_logging", return_value=_make_logger()):
            result = run(root=tmp_path, force=False)

        # Should NOT call the API at all
        mock_get.assert_not_called()
        assert result["status"] == "OK"
        assert result["rows"] >= 1

    def test_run_force_ignores_cache(self, tmp_path):
        """run(force=True) re-downloads even when raw file exists."""
        import pandas as pd

        raw_dir = tmp_path / "data" / "staging" / "raw" / "lda"
        raw_dir.mkdir(parents=True)
        raw_path = raw_dir / "lda_pr_filings.csv"
        df = pd.DataFrame([_flatten(_make_filing())])
        df.to_csv(raw_path, index=False)

        new_filing = _make_filing(filing_uuid="fresh-uuid", filing_year=2024)
        api_resp = self._make_api_response([new_filing])

        with patch("scripts.download_lda._get", return_value=api_resp), \
             patch("scripts.download_lda.time.sleep"), \
             patch("scripts.download_lda.setup_logging", return_value=_make_logger()):
            result = run(root=tmp_path, force=True)

        assert result["status"] == "OK"

    def test_run_deduplicates_overlapping_filings(self, tmp_path):
        """Filings with the same UUID from both passes are deduplicated."""
        shared_uuid = "shared-uuid"
        filing = _make_filing(filing_uuid=shared_uuid)
        api_resp = self._make_api_response([filing])

        with patch("scripts.download_lda._get", return_value=api_resp), \
             patch("scripts.download_lda.time.sleep"), \
             patch("scripts.download_lda.setup_logging", return_value=_make_logger()):
            result = run(root=tmp_path, force=True)

        # Both passes return same UUID → only 1 row after dedup
        assert result["rows"] == 1

    def test_run_output_has_correct_columns(self, tmp_path):
        """Output CSV contains all expected OUTPUT_COLUMNS."""
        import pandas as pd

        filing = _make_filing()
        api_resp = self._make_api_response([filing])

        with patch("scripts.download_lda._get", return_value=api_resp), \
             patch("scripts.download_lda.time.sleep"), \
             patch("scripts.download_lda.setup_logging", return_value=_make_logger()):
            run(root=tmp_path, force=True)

        out_path = tmp_path / "data" / "staging" / "processed" / "pr_lda_filings.csv"
        df = pd.read_csv(out_path, dtype=str)
        for col in OUTPUT_COLUMNS:
            assert col in df.columns, f"Missing column in output: {col}"
