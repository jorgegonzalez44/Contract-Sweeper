"""
Tests for scripts/download_openfema_pa_projects.py

Covers:
  - Pure helper functions: _map_record, _normalize_row (via _map_record)
  - Pagination logic: _paginate (URL building with $top/$skip, stopping on empty page)
  - run() integration: caching (force=False), mocked paginated HTTP response
"""

import logging
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# Suppress noisy log output from the module under test and test logger
logging.getLogger("download_openfema_pa_projects").setLevel(logging.CRITICAL)
logging.getLogger("test").setLevel(logging.CRITICAL)

from scripts.download_openfema_pa_projects import (
    PAGE_SIZE,
    PA_V2_COLUMNS,
    PA_V2_ENDPOINT,
    FEMA_BASE_V2,
    _map_record,
    _paginate,
    run,
)


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

def _silent_logger() -> logging.Logger:
    """Return a logger that discards all output."""
    logger = logging.getLogger("test_openfema")
    logger.setLevel(logging.CRITICAL)
    return logger


def _make_http_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Build a fake requests.Response-like mock."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# _map_record
# ---------------------------------------------------------------------------

class TestMapRecord:
    def _raw(self, **overrides) -> dict:
        base = {
            "disasterNumber": "4339",
            "pwNumber": "1001",
            "applicantId": "APPL-01",
            "applicantName": "Municipio de San Juan",
            "county": "San Juan",
            "countyFips": "72127",
            "stateNumberCode": "72",
            "category": "B",
            "applicationTitle": "Debris Removal",
            "damageCategory": "Large Project",
            "projectAmount": 500000.0,
            "federalShareObligated": 400000.0,
            "totalObligated": 450000.0,
            "obligatedDate": "2018-05-01",
            "projectWorksheetDate": "2018-04-01",
            "closedProjectWorksheetDate": "2019-01-15",
            "latitude": 18.4655,
            "longitude": -66.1057,
        }
        base.update(overrides)
        return base

    def test_returns_all_canonical_columns(self):
        row = _map_record(self._raw(), "openfema_v2", "2024-01-01")
        assert set(row.keys()) == set(PA_V2_COLUMNS)

    def test_disaster_number_is_string(self):
        row = _map_record(self._raw(), "openfema_v2", "2024-01-01")
        assert row["disaster_number"] == "4339"
        assert isinstance(row["disaster_number"], str)

    def test_source_system_and_pull_date_preserved(self):
        row = _map_record(self._raw(), "openfema_v2", "2026-05-01")
        assert row["source_system"] == "openfema_v2"
        assert row["pull_date"] == "2026-05-01"

    def test_applicant_name_carried_through(self):
        row = _map_record(self._raw(), "openfema_v2", "2024-01-01")
        assert row["applicant_name"] == "Municipio de San Juan"

    def test_applicant_normalized_is_uppercase_stripped(self):
        row = _map_record(self._raw(), "openfema_v2", "2024-01-01")
        # _normalize_name uppercases and strips punctuation/suffixes
        assert row["applicant_normalized"] == "MUNICIPIO DE SAN JUAN"

    def test_numeric_fields_preserved(self):
        row = _map_record(self._raw(), "openfema_v2", "2024-01-01")
        assert row["project_amount"] == 500000.0
        assert row["federal_share_obligated"] == 400000.0
        assert row["total_obligated"] == 450000.0

    def test_null_applicant_name_gives_empty_string(self):
        row = _map_record(self._raw(applicantName=None), "openfema_v2", "2024-01-01")
        assert row["applicant_name"] == ""

    def test_county_fallback_to_countyName(self):
        raw = self._raw()
        del raw["county"]
        raw["countyName"] = "Bayamon"
        row = _map_record(raw, "openfema_v2", "2024-01-01")
        assert row["county"] == "Bayamon"

    def test_category_falls_back_to_damageCategory_when_absent(self):
        raw = self._raw()
        del raw["category"]
        row = _map_record(raw, "openfema_v2", "2024-01-01")
        assert row["category"] == "Large Project"

    def test_state_code_falls_back_to_state_key(self):
        raw = self._raw()
        del raw["stateNumberCode"]
        raw["state"] = "PR"
        row = _map_record(raw, "openfema_v2", "2024-01-01")
        assert row["state_code"] == "PR"


# ---------------------------------------------------------------------------
# _paginate  —  URL building + stopping logic
# ---------------------------------------------------------------------------

class TestPaginate:
    """Validate _paginate URL construction and pagination stop conditions."""

    def _endpoint(self):
        return PA_V2_ENDPOINT

    def _data_key(self):
        return "PublicAssistanceFundedProjectsDetails"

    def _page(self, records, total=None):
        """Build a fake OpenFEMA page response."""
        payload = {self._data_key(): records}
        if total is not None:
            payload["metadata"] = {"count": total}
        return payload

    @patch("scripts.download_openfema_pa_projects._get_with_retry")
    def test_first_page_url_has_top_and_skip_zero(self, mock_get):
        """First request URL must include $top and $skip=0."""
        mock_get.side_effect = [
            self._page([{"id": 1}], total=1),
            self._page([]),           # second call returns empty → stop
        ]
        logger = _silent_logger()
        _paginate(self._endpoint(), self._data_key(), {}, logger)
        first_url = mock_get.call_args_list[0][0][0]
        assert "$top=" in first_url
        assert "$skip=0" in first_url

    @patch("scripts.download_openfema_pa_projects._get_with_retry")
    def test_second_page_url_has_skip_equal_to_page_size(self, mock_get):
        """Second request URL must advance $skip by PAGE_SIZE."""
        records = [{"id": i} for i in range(PAGE_SIZE)]
        mock_get.side_effect = [
            self._page(records, total=PAGE_SIZE * 2),
            self._page([]),   # empty second page → stop
        ]
        logger = _silent_logger()
        _paginate(self._endpoint(), self._data_key(), {}, logger)
        second_url = mock_get.call_args_list[1][0][0]
        assert f"$skip={PAGE_SIZE}" in second_url

    @patch("scripts.download_openfema_pa_projects._get_with_retry")
    def test_filter_clause_appended_to_url(self, mock_get):
        """$filter param is appended raw (not percent-encoded) into the URL."""
        mock_get.side_effect = [self._page([])]
        logger = _silent_logger()
        _paginate(self._endpoint(), self._data_key(), {"$filter": "state eq 'PR'"}, logger)
        url = mock_get.call_args_list[0][0][0]
        assert "$filter=state eq 'PR'" in url

    @patch("scripts.download_openfema_pa_projects._get_with_retry")
    def test_stops_on_empty_page(self, mock_get):
        """Pagination stops when a page returns an empty list (no total known)."""
        mock_get.side_effect = [
            self._page([{"id": 1}]),   # no total → can't stop early on count
            self._page([]),             # empty → stop
        ]
        logger = _silent_logger()
        results = _paginate(self._endpoint(), self._data_key(), {}, logger)
        assert len(results) == 1
        assert mock_get.call_count == 2

    @patch("scripts.download_openfema_pa_projects._get_with_retry")
    def test_stops_when_none_returned(self, mock_get):
        """Pagination stops immediately when _get_with_retry returns None."""
        mock_get.return_value = None
        logger = _silent_logger()
        results = _paginate(self._endpoint(), self._data_key(), {}, logger)
        assert results == []
        assert mock_get.call_count == 1

    @patch("scripts.download_openfema_pa_projects._get_with_retry")
    def test_collects_records_across_pages(self, mock_get):
        """All records from multiple pages are combined."""
        page1 = [{"id": i} for i in range(PAGE_SIZE)]
        page2 = [{"id": i + PAGE_SIZE} for i in range(5)]
        mock_get.side_effect = [
            self._page(page1, total=PAGE_SIZE + 5),
            self._page(page2, total=PAGE_SIZE + 5),
            self._page([]),
        ]
        logger = _silent_logger()
        results = _paginate(self._endpoint(), self._data_key(), {}, logger)
        assert len(results) == PAGE_SIZE + 5

    @patch("scripts.download_openfema_pa_projects._get_with_retry")
    def test_simple_params_are_url_encoded_and_appended(self, mock_get):
        """simple_params are URL-encoded and appended after OData params."""
        mock_get.side_effect = [self._page([])]
        logger = _silent_logger()
        _paginate(
            self._endpoint(),
            self._data_key(),
            {},
            logger,
            simple_params={"format": "json"},
        )
        url = mock_get.call_args_list[0][0][0]
        assert "format=json" in url


# ---------------------------------------------------------------------------
# run() — caching behaviour
# ---------------------------------------------------------------------------

class TestRunCaching:
    """run() returns CACHED when output exists and force=False."""

    def test_cached_status_when_output_exists(self, tmp_path):
        out_dir = tmp_path / "data" / "normalized"
        out_dir.mkdir(parents=True)
        out_path = out_dir / "fema_pa_projects_v2.parquet"

        # Write a minimal parquet (or CSV fallback) so pq_read returns something
        df = pd.DataFrame([{col: "x" for col in PA_V2_COLUMNS}])
        from scripts.parquet_utils import pq_write
        pq_write(df, out_path)

        with patch("scripts.download_openfema_pa_projects.requests.get") as mock_get:
            result = run(root=tmp_path, force=False)

        mock_get.assert_not_called()
        assert result["status"] == "CACHED"
        assert result["rows"] >= 1

    def test_cached_result_has_correct_path(self, tmp_path):
        out_dir = tmp_path / "data" / "normalized"
        out_dir.mkdir(parents=True)
        out_path = out_dir / "fema_pa_projects_v2.parquet"

        df = pd.DataFrame([{col: "x" for col in PA_V2_COLUMNS}])
        from scripts.parquet_utils import pq_write
        pq_write(df, out_path)

        with patch("scripts.download_openfema_pa_projects.requests.get"):
            result = run(root=tmp_path, force=False)

        assert "fema_pa_projects_v2" in result["path"]


# ---------------------------------------------------------------------------
# run() — paginated HTTP integration (mocked)
# ---------------------------------------------------------------------------

class TestRunWithMockedHttp:
    """run() with mocked paginated API produces an output file."""

    def _mock_disaster_page(self):
        return {
            "DisasterDeclarationsSummaries": [
                {"disasterNumber": 4339, "state": "PR"},
            ],
            "metadata": {"count": 1},
        }

    def _mock_disaster_empty(self):
        return {"DisasterDeclarationsSummaries": [], "metadata": {"count": 1}}

    def _mock_pa_page(self, records):
        return {
            "PublicAssistanceFundedProjectsDetails": records,
            "metadata": {"count": len(records)},
        }

    def _mock_applicants_empty(self):
        return {"PublicAssistanceApplicants": [], "metadata": {"count": 0}}

    def _sample_pa_record(self, idx: int = 0) -> dict:
        return {
            "disasterNumber": 4339,
            "pwNumber": str(1000 + idx),
            "applicantId": f"A{idx:03d}",
            "applicantName": "Test Municipality",
            "county": "San Juan",
            "countyFips": "72127",
            "stateNumberCode": "72",
            "category": "B",
            "applicationTitle": "Road Repair",
            "damageCategory": "Large Project",
            "projectAmount": 100000.0 * (idx + 1),
            "federalShareObligated": 75000.0,
            "totalObligated": 80000.0,
            "obligatedDate": "2018-06-01",
            "projectWorksheetDate": "2018-05-01",
            "closedProjectWorksheetDate": "",
            "latitude": 18.4655,
            "longitude": -66.1057,
        }

    def _build_response_sequence(self):
        """Return a side_effect list that simulates:
            1. Disaster page 1 (1 disaster) → empty page 2 (stop)
            2. PA v2 page 1 (2 records) → empty page 2 (stop)
            3. Applicants page 1 empty (stop)
        """
        disaster_p1 = self._mock_disaster_page()
        disaster_p2 = {"DisasterDeclarationsSummaries": [], "metadata": {"count": 1}}
        pa_p1 = self._mock_pa_page([self._sample_pa_record(0), self._sample_pa_record(1)])
        pa_p2 = {"PublicAssistanceFundedProjectsDetails": [], "metadata": {"count": 2}}
        applicants_p1 = self._mock_applicants_empty()

        def side_effect(url, timeout=60):
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status.return_value = None
            if "DisasterDeclarationsSummaries" in url:
                if "$skip=0" in url:
                    resp.json.return_value = disaster_p1
                else:
                    resp.json.return_value = disaster_p2
            elif "PublicAssistanceFundedProjectsDetails" in url:
                if "$skip=0" in url:
                    resp.json.return_value = pa_p1
                else:
                    resp.json.return_value = pa_p2
            elif "PublicAssistanceApplicants" in url:
                resp.json.return_value = applicants_p1
            else:
                resp.json.return_value = {}
            return resp

        return side_effect

    @patch("scripts.download_openfema_pa_projects.time.sleep")
    @patch("scripts.download_openfema_pa_projects.requests.get")
    def test_run_returns_ok_status(self, mock_get, mock_sleep, tmp_path):
        mock_get.side_effect = self._build_response_sequence()
        result = run(root=tmp_path, force=True)
        assert result["status"] == "OK"

    @patch("scripts.download_openfema_pa_projects.time.sleep")
    @patch("scripts.download_openfema_pa_projects.requests.get")
    def test_run_returns_two_rows(self, mock_get, mock_sleep, tmp_path):
        mock_get.side_effect = self._build_response_sequence()
        result = run(root=tmp_path, force=True)
        assert result["rows"] == 2

    @patch("scripts.download_openfema_pa_projects.time.sleep")
    @patch("scripts.download_openfema_pa_projects.requests.get")
    def test_run_creates_output_file(self, mock_get, mock_sleep, tmp_path):
        mock_get.side_effect = self._build_response_sequence()
        result = run(root=tmp_path, force=True)
        out = Path(result["path"])
        # parquet or CSV fallback
        assert out.exists() or out.with_suffix(".csv").exists()

    @patch("scripts.download_openfema_pa_projects.time.sleep")
    @patch("scripts.download_openfema_pa_projects.requests.get")
    def test_run_output_has_canonical_columns(self, mock_get, mock_sleep, tmp_path):
        mock_get.side_effect = self._build_response_sequence()
        result = run(root=tmp_path, force=True)
        from scripts.parquet_utils import pq_read
        df = pq_read(Path(result["path"]))
        for col in PA_V2_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"

    @patch("scripts.download_openfema_pa_projects.time.sleep")
    @patch("scripts.download_openfema_pa_projects.requests.get")
    def test_run_empty_on_no_disasters(self, mock_get, mock_sleep, tmp_path):
        """When no disaster numbers are found, run() writes an empty parquet."""
        def no_disasters(url, timeout=60):
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status.return_value = None
            if "DisasterDeclarationsSummaries" in url:
                resp.json.return_value = {"DisasterDeclarationsSummaries": [], "metadata": {"count": 0}}
            elif "PublicAssistanceApplicants" in url:
                resp.json.return_value = {"PublicAssistanceApplicants": [], "metadata": {"count": 0}}
            else:
                resp.json.return_value = {}
            return resp

        mock_get.side_effect = no_disasters
        result = run(root=tmp_path, force=True)
        assert result["status"] == "EMPTY"
        assert result["rows"] == 0

    @patch("scripts.download_openfema_pa_projects.time.sleep")
    @patch("scripts.download_openfema_pa_projects.requests.get")
    def test_run_path_contains_normalized_subdir(self, mock_get, mock_sleep, tmp_path):
        mock_get.side_effect = self._build_response_sequence()
        result = run(root=tmp_path, force=True)
        assert "normalized" in result["path"]

    @patch("scripts.download_openfema_pa_projects.time.sleep")
    @patch("scripts.download_openfema_pa_projects.requests.get")
    def test_force_true_re_downloads_despite_existing_output(self, mock_get, mock_sleep, tmp_path):
        """With force=True, run() ignores any cached file and re-downloads."""
        out_dir = tmp_path / "data" / "normalized"
        out_dir.mkdir(parents=True)
        stale_df = pd.DataFrame([{col: "stale" for col in PA_V2_COLUMNS}])
        from scripts.parquet_utils import pq_write
        pq_write(stale_df, out_dir / "fema_pa_projects_v2.parquet")

        mock_get.side_effect = self._build_response_sequence()
        result = run(root=tmp_path, force=True)

        assert result["status"] == "OK"
        assert result["rows"] == 2
