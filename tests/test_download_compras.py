"""Tests for download_compras.py — Compras PR procurement data downloader."""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Suppress noisy log output from the module under test
logging.getLogger("download_compras").setLevel(logging.CRITICAL)
logging.getLogger("test").setLevel(logging.CRITICAL)

from scripts.download_compras import (
    AWARD_COLUMNS,
    COMPRAS_BASE,
    COMPRAS_ENDPOINTS,
    PAGE_SIZE,
    RFP_COLUMNS,
    _fetch_html_table,
    _fetch_json_endpoint,
    _normalize_award,
    _normalize_rfp,
    _session,
    _try_get,
    run,
)


# ---------------------------------------------------------------------------
# _session
# ---------------------------------------------------------------------------

class TestSession:
    def test_returns_requests_session(self):
        s = _session()
        assert s is not None

    def test_user_agent_set(self):
        s = _session()
        assert "User-Agent" in s.headers
        assert "ContractSweeper" in s.headers["User-Agent"]

    def test_accept_language_set(self):
        s = _session()
        assert "Accept-Language" in s.headers
        assert "es" in s.headers["Accept-Language"]

    def test_referer_set(self):
        s = _session()
        assert "Referer" in s.headers
        assert COMPRAS_BASE in s.headers["Referer"]


# ---------------------------------------------------------------------------
# _normalize_rfp
# ---------------------------------------------------------------------------

class TestNormalizeRfp:
    def _sample(self):
        return {
            "id": "RFP-001",
            "title": "Construction Services",
            "agency": "Dept of Transportation",
            "posted_date": "2023-01-15",
            "due_date": "2023-02-15",
            "estimated_value": "500000",
            "status": "open",
        }

    def test_returns_all_rfp_columns(self):
        result = _normalize_rfp(self._sample())
        for col in RFP_COLUMNS:
            assert col in result

    def test_rfp_id_extracted(self):
        result = _normalize_rfp(self._sample())
        assert result["rfp_id"] == "RFP-001"

    def test_title_extracted(self):
        result = _normalize_rfp(self._sample())
        assert result["title"] == "Construction Services"

    def test_agency_extracted(self):
        result = _normalize_rfp(self._sample())
        assert result["agency"] == "Dept of Transportation"

    def test_agency_normalized_populated(self):
        result = _normalize_rfp(self._sample())
        assert isinstance(result["agency_normalized"], str)
        assert len(result["agency_normalized"]) > 0

    def test_estimated_value_converted_to_float(self):
        result = _normalize_rfp(self._sample())
        assert isinstance(result["estimated_value"], float)
        assert result["estimated_value"] == 500000.0

    def test_estimated_value_with_dollar_sign_and_commas(self):
        r = self._sample()
        r["estimated_value"] = "$1,250,000"
        result = _normalize_rfp(r)
        assert result["estimated_value"] == 1250000.0

    def test_estimated_value_invalid_returns_zero(self):
        r = self._sample()
        r["estimated_value"] = "N/A"
        result = _normalize_rfp(r)
        assert result["estimated_value"] == 0.0

    def test_estimated_value_missing_returns_zero(self):
        r = {k: v for k, v in self._sample().items() if k != "estimated_value"}
        result = _normalize_rfp(r)
        assert result["estimated_value"] == 0.0

    def test_spanish_field_names_accepted(self):
        r = {
            "numero": "SOL-999",
            "titulo": "Servicios Profesionales",
            "agencia": "Autoridad de Carreteras",
            "fecha_publicacion": "2023-03-01",
            "fecha_cierre": "2023-04-01",
            "presupuesto": "750000",
            "estado": "activo",
        }
        result = _normalize_rfp(r)
        assert result["rfp_id"] == "SOL-999"
        assert result["title"] == "Servicios Profesionales"
        assert result["agency"] == "Autoridad de Carreteras"
        assert result["estimated_value"] == 750000.0

    def test_empty_dict_returns_default_values(self):
        result = _normalize_rfp({})
        for col in RFP_COLUMNS:
            assert col in result
        assert result["estimated_value"] == 0.0


# ---------------------------------------------------------------------------
# _normalize_award
# ---------------------------------------------------------------------------

class TestNormalizeAward:
    def _sample(self):
        return {
            "id": "AWD-001",
            "rfp_id": "RFP-100",
            "title": "Road Repair Contract",
            "agency": "Dept of Transportation",
            "award_date": "2023-03-01",
            "vendor": "Build Corp",
            "awarded_amount": "2500000",
        }

    def test_returns_all_award_columns(self):
        result = _normalize_award(self._sample())
        for col in AWARD_COLUMNS:
            assert col in result

    def test_contract_id_extracted(self):
        result = _normalize_award(self._sample())
        assert result["contract_id"] == "AWD-001"

    def test_rfp_id_extracted(self):
        result = _normalize_award(self._sample())
        assert result["rfp_id"] == "RFP-100"

    def test_title_extracted(self):
        result = _normalize_award(self._sample())
        assert result["title"] == "Road Repair Contract"

    def test_agency_normalized_populated(self):
        result = _normalize_award(self._sample())
        assert isinstance(result["agency_normalized"], str)
        assert len(result["agency_normalized"]) > 0

    def test_vendor_extracted(self):
        result = _normalize_award(self._sample())
        assert result["awarded_vendor"] == "Build Corp"

    def test_vendor_normalized_populated(self):
        result = _normalize_award(self._sample())
        assert isinstance(result["awarded_vendor_normalized"], str)
        assert len(result["awarded_vendor_normalized"]) > 0

    def test_awarded_amount_converted_to_float(self):
        result = _normalize_award(self._sample())
        assert isinstance(result["awarded_amount"], float)
        assert result["awarded_amount"] == 2500000.0

    def test_awarded_amount_with_commas(self):
        r = self._sample()
        r["awarded_amount"] = "3,750,000"
        result = _normalize_award(r)
        assert result["awarded_amount"] == 3750000.0

    def test_awarded_amount_invalid_returns_zero(self):
        r = self._sample()
        r["awarded_amount"] = "TBD"
        result = _normalize_award(r)
        assert result["awarded_amount"] == 0.0

    def test_spanish_field_names_accepted(self):
        r = {
            "contrato_id": "CON-555",
            "solicitation_id": "SOL-100",
            "titulo": "Contrato de Construccion",
            "entidad": "Municipio de San Juan",
            "fecha_adjudicacion": "2023-06-15",
            "contratista": "Constructora PR LLC",
            "monto": "4,000,000",
        }
        result = _normalize_award(r)
        assert result["awarded_vendor"] == "Constructora PR LLC"
        assert result["awarded_amount"] == 4000000.0

    def test_empty_dict_returns_default_values(self):
        result = _normalize_award({})
        for col in AWARD_COLUMNS:
            assert col in result
        assert result["awarded_amount"] == 0.0


# ---------------------------------------------------------------------------
# _try_get
# ---------------------------------------------------------------------------

class TestTryGet:
    def test_returns_response_on_success(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_session.get.return_value = mock_resp
        logger = logging.getLogger("test")

        with patch("scripts.download_compras.time.sleep"):
            result = _try_get(mock_session, "http://example.com", {}, logger)

        assert result is mock_resp

    def test_returns_none_after_all_retries_fail(self):
        import requests as req_lib
        mock_session = MagicMock()
        mock_session.get.side_effect = req_lib.RequestException("network error")
        logger = logging.getLogger("test")

        with patch("scripts.download_compras.time.sleep"):
            result = _try_get(mock_session, "http://example.com", {}, logger)

        assert result is None


# ---------------------------------------------------------------------------
# _fetch_json_endpoint
# ---------------------------------------------------------------------------

class TestFetchJsonEndpoint:
    def _make_session(self, json_response, status_code=200):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = json_response
        mock_session.get.return_value = mock_resp
        return mock_session

    def test_returns_list_response_directly(self):
        records = [{"id": "1", "title": "Test RFP"}]
        session = self._make_session(records)
        logger = logging.getLogger("test")

        with patch("scripts.download_compras.time.sleep"):
            result = _fetch_json_endpoint(session, "/api/rfp", "rfps", 1, logger)

        assert result == records

    def test_returns_dict_data_key(self):
        records = [{"id": "2", "title": "Another RFP"}]
        session = self._make_session({"data": records, "next": None})
        logger = logging.getLogger("test")

        with patch("scripts.download_compras.time.sleep"):
            result = _fetch_json_endpoint(session, "/api/rfp", "rfps", 1, logger)

        assert result == records

    def test_returns_empty_list_on_http_error(self):
        session = self._make_session({}, status_code=404)
        logger = logging.getLogger("test")

        with patch("scripts.download_compras.time.sleep"):
            result = _fetch_json_endpoint(session, "/api/rfp", "rfps", 1, logger)

        assert result == []

    def test_returns_empty_list_on_json_decode_error(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("bad json")
        mock_session.get.return_value = mock_resp
        logger = logging.getLogger("test")

        with patch("scripts.download_compras.time.sleep"):
            result = _fetch_json_endpoint(mock_session, "/api/rfp", "rfps", 1, logger)

        assert result == []

    def test_stops_when_list_shorter_than_page_size(self):
        # If response has fewer items than PAGE_SIZE, pagination should stop
        records = [{"id": str(i)} for i in range(5)]  # 5 < PAGE_SIZE (100)
        session = self._make_session(records)
        logger = logging.getLogger("test")

        with patch("scripts.download_compras.time.sleep"):
            result = _fetch_json_endpoint(session, "/api/rfp", "rfps", 10, logger)

        # Should only have made one page request
        assert session.get.call_count == 1
        assert len(result) == 5


# ---------------------------------------------------------------------------
# _fetch_html_table
# ---------------------------------------------------------------------------

class TestFetchHtmlTable:
    def test_returns_empty_list_on_http_error(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_session.get.return_value = mock_resp
        logger = logging.getLogger("test")

        with patch("scripts.download_compras.time.sleep"):
            result = _fetch_html_table(mock_session, "/busqueda/solicitudes", logger)

        assert result == []

    def test_returns_data_from_embedded_json(self):
        records = [{"id": "H1", "title": "HTML Table RFP"}]
        html = f'<script>window.__DATA__ = {{"data": {json.dumps(records)}}};</script>'
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_session.get.return_value = mock_resp
        logger = logging.getLogger("test")

        with patch("scripts.download_compras.time.sleep"):
            result = _fetch_html_table(mock_session, "/busqueda/solicitudes", logger)

        assert result == records

    def test_returns_empty_list_when_no_embedded_json(self):
        mock_session = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body>No data here</body></html>"
        mock_session.get.return_value = mock_resp
        logger = logging.getLogger("test")

        with patch("scripts.download_compras.time.sleep"):
            result = _fetch_html_table(mock_session, "/busqueda/solicitudes", logger)

        assert result == []


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_compras_base_is_string(self):
        assert isinstance(COMPRAS_BASE, str)
        assert COMPRAS_BASE.startswith("https://")

    def test_compras_endpoints_has_rfps_and_awards(self):
        assert "rfps" in COMPRAS_ENDPOINTS
        assert "awards" in COMPRAS_ENDPOINTS

    def test_rfps_endpoints_is_nonempty_list(self):
        assert isinstance(COMPRAS_ENDPOINTS["rfps"], list)
        assert len(COMPRAS_ENDPOINTS["rfps"]) > 0

    def test_awards_endpoints_is_nonempty_list(self):
        assert isinstance(COMPRAS_ENDPOINTS["awards"], list)
        assert len(COMPRAS_ENDPOINTS["awards"]) > 0

    def test_rfp_columns_complete(self):
        expected = {"rfp_id", "title", "agency", "agency_normalized",
                    "posted_date", "due_date", "estimated_value", "status"}
        assert set(RFP_COLUMNS) == expected

    def test_award_columns_complete(self):
        expected = {"rfp_id", "contract_id", "title", "agency", "agency_normalized",
                    "award_date", "awarded_vendor", "awarded_vendor_normalized", "awarded_amount"}
        assert set(AWARD_COLUMNS) == expected


# ---------------------------------------------------------------------------
# run() — caching (force=False skips when outputs exist)
# ---------------------------------------------------------------------------

class TestRunCaching:
    def test_returns_cached_status_when_outputs_exist(self, tmp_path):
        """run() returns CACHED when both output files already exist."""
        out_dir = tmp_path / "data" / "staging" / "processed"
        out_dir.mkdir(parents=True)

        # Pre-create output files
        rfp_out = out_dir / "pr_compras_rfps.csv"
        award_out = out_dir / "pr_compras_awards.csv"
        pd.DataFrame([{"rfp_id": "1", "title": "T"}]).to_csv(rfp_out, index=False)
        pd.DataFrame([{"contract_id": "C1"}]).to_csv(award_out, index=False)

        # Also create raw dir
        (tmp_path / "data" / "staging" / "raw" / "compras").mkdir(parents=True)
        (tmp_path / "data" / "logs").mkdir(parents=True)

        with patch("scripts.download_compras._session") as mock_session_fn:
            result = run(root=tmp_path, force=False)

        # Session should not be used — cached path taken
        mock_session_fn.assert_not_called()
        assert result["status"] == "CACHED"

    def test_cached_result_includes_row_counts(self, tmp_path):
        """Cached result contains rfp_rows and award_rows keys."""
        out_dir = tmp_path / "data" / "staging" / "processed"
        out_dir.mkdir(parents=True)

        rfp_out = out_dir / "pr_compras_rfps.csv"
        award_out = out_dir / "pr_compras_awards.csv"
        pd.DataFrame([{"rfp_id": "1"}, {"rfp_id": "2"}]).to_csv(rfp_out, index=False)
        pd.DataFrame([{"contract_id": "C1"}]).to_csv(award_out, index=False)

        (tmp_path / "data" / "staging" / "raw" / "compras").mkdir(parents=True)
        (tmp_path / "data" / "logs").mkdir(parents=True)

        with patch("scripts.download_compras._session"):
            result = run(root=tmp_path, force=False)

        assert "rfp_rows" in result
        assert "award_rows" in result
        assert result["rfp_rows"] == 2
        assert result["award_rows"] == 1


# ---------------------------------------------------------------------------
# run() — download path with mocked HTTP
# ---------------------------------------------------------------------------

def _make_mock_session(rfp_records=None, award_records=None):
    """Return a mock session whose .get() returns JSON data for the first endpoint."""
    mock_session = MagicMock()

    rfp_records = rfp_records or []
    award_records = award_records or []

    def get_side_effect(url, params=None, timeout=None):
        resp = MagicMock()
        resp.status_code = 200
        if "rfp" in url or "solicitud" in url or "solicitation" in url:
            resp.json.return_value = rfp_records
        elif "award" in url or "contrato" in url or "contract" in url:
            resp.json.return_value = award_records
        else:
            resp.json.return_value = []
        return resp

    mock_session.get.side_effect = get_side_effect
    return mock_session


class TestRunWithMockedHttp:
    def test_run_returns_dict(self, tmp_path):
        """run() always returns a dict."""
        (tmp_path / "data" / "logs").mkdir(parents=True)

        with patch("scripts.download_compras._session") as mock_session_fn, \
             patch("scripts.download_compras.time.sleep"):
            mock_session_fn.return_value = _make_mock_session()
            result = run(root=tmp_path, force=True, max_pages=1)

        assert isinstance(result, dict)

    def test_run_returns_status_key(self, tmp_path):
        """run() result contains a 'status' key."""
        (tmp_path / "data" / "logs").mkdir(parents=True)

        with patch("scripts.download_compras._session") as mock_session_fn, \
             patch("scripts.download_compras.time.sleep"):
            mock_session_fn.return_value = _make_mock_session()
            result = run(root=tmp_path, force=True, max_pages=1)

        assert "status" in result

    def test_run_empty_response_returns_empty_status(self, tmp_path):
        """run() with no data from any endpoint returns EMPTY status."""
        (tmp_path / "data" / "logs").mkdir(parents=True)

        with patch("scripts.download_compras._session") as mock_session_fn, \
             patch("scripts.download_compras.time.sleep"):
            mock_session_fn.return_value = _make_mock_session(rfp_records=[], award_records=[])
            result = run(root=tmp_path, force=True, max_pages=1)

        assert result["status"] == "EMPTY"

    def test_run_with_rfp_data_creates_csv(self, tmp_path):
        """run() with RFP data writes pr_compras_rfps.csv."""
        (tmp_path / "data" / "logs").mkdir(parents=True)

        rfp_records = [
            {"id": "RFP-1", "title": "Test RFP", "agency": "DTOP",
             "posted_date": "2023-01-01", "due_date": "2023-02-01",
             "estimated_value": "100000", "status": "open"}
        ]

        with patch("scripts.download_compras._session") as mock_session_fn, \
             patch("scripts.download_compras.time.sleep"):
            mock_session_fn.return_value = _make_mock_session(rfp_records=rfp_records)
            result = run(root=tmp_path, force=True, max_pages=1)

        rfp_csv = tmp_path / "data" / "staging" / "processed" / "pr_compras_rfps.csv"
        assert rfp_csv.exists()

    def test_run_with_award_data_creates_csv(self, tmp_path):
        """run() with award data writes pr_compras_awards.csv."""
        (tmp_path / "data" / "logs").mkdir(parents=True)

        award_records = [
            {"id": "AWD-1", "rfp_id": "RFP-1", "title": "Award",
             "agency": "DTOP", "award_date": "2023-03-01",
             "vendor": "Build Corp", "awarded_amount": "500000"}
        ]

        with patch("scripts.download_compras._session") as mock_session_fn, \
             patch("scripts.download_compras.time.sleep"):
            mock_session_fn.return_value = _make_mock_session(award_records=award_records)
            result = run(root=tmp_path, force=True, max_pages=1)

        award_csv = tmp_path / "data" / "staging" / "processed" / "pr_compras_awards.csv"
        assert award_csv.exists()

    def test_run_with_rfp_data_returns_ok_status(self, tmp_path):
        """run() with RFP data returns OK status."""
        (tmp_path / "data" / "logs").mkdir(parents=True)

        rfp_records = [
            {"id": "RFP-1", "title": "Test RFP", "agency": "DTOP",
             "posted_date": "2023-01-01", "due_date": "2023-02-01",
             "estimated_value": "100000", "status": "open"}
        ]

        with patch("scripts.download_compras._session") as mock_session_fn, \
             patch("scripts.download_compras.time.sleep"):
            mock_session_fn.return_value = _make_mock_session(rfp_records=rfp_records)
            result = run(root=tmp_path, force=True, max_pages=1)

        assert result["status"] == "OK"

    def test_run_rfp_csv_has_correct_columns(self, tmp_path):
        """The RFP CSV written by run() contains the expected columns."""
        (tmp_path / "data" / "logs").mkdir(parents=True)

        rfp_records = [
            {"id": "RFP-2", "title": "Another RFP", "agency": "PRASA",
             "posted_date": "2023-04-01", "due_date": "2023-05-01",
             "estimated_value": "200000", "status": "closed"}
        ]

        with patch("scripts.download_compras._session") as mock_session_fn, \
             patch("scripts.download_compras.time.sleep"):
            mock_session_fn.return_value = _make_mock_session(rfp_records=rfp_records)
            run(root=tmp_path, force=True, max_pages=1)

        rfp_csv = tmp_path / "data" / "staging" / "processed" / "pr_compras_rfps.csv"
        df = pd.read_csv(rfp_csv)
        for col in RFP_COLUMNS:
            assert col in df.columns

    def test_run_award_csv_has_correct_columns(self, tmp_path):
        """The award CSV written by run() contains the expected columns."""
        (tmp_path / "data" / "logs").mkdir(parents=True)

        award_records = [
            {"id": "AWD-2", "rfp_id": "RFP-2", "title": "Contract",
             "agency": "PRASA", "award_date": "2023-06-01",
             "vendor": "Water Corp", "awarded_amount": "800000"}
        ]

        with patch("scripts.download_compras._session") as mock_session_fn, \
             patch("scripts.download_compras.time.sleep"):
            mock_session_fn.return_value = _make_mock_session(award_records=award_records)
            run(root=tmp_path, force=True, max_pages=1)

        award_csv = tmp_path / "data" / "staging" / "processed" / "pr_compras_awards.csv"
        df = pd.read_csv(award_csv)
        for col in AWARD_COLUMNS:
            assert col in df.columns

    def test_run_force_true_overwrites_existing(self, tmp_path):
        """run(force=True) overwrites existing output files."""
        out_dir = tmp_path / "data" / "staging" / "processed"
        out_dir.mkdir(parents=True)
        (tmp_path / "data" / "logs").mkdir(parents=True)

        # Pre-create old output files
        rfp_out = out_dir / "pr_compras_rfps.csv"
        award_out = out_dir / "pr_compras_awards.csv"
        pd.DataFrame([{"rfp_id": "OLD"}]).to_csv(rfp_out, index=False)
        pd.DataFrame([{"contract_id": "OLD"}]).to_csv(award_out, index=False)

        with patch("scripts.download_compras._session") as mock_session_fn, \
             patch("scripts.download_compras.time.sleep"):
            mock_session_fn.return_value = _make_mock_session()
            result = run(root=tmp_path, force=True, max_pages=1)

        # Should not return CACHED — download was attempted
        assert result["status"] != "CACHED"

    def test_run_creates_raw_json_when_data_found(self, tmp_path):
        """run() writes raw JSON file when data is successfully fetched."""
        (tmp_path / "data" / "logs").mkdir(parents=True)

        rfp_records = [
            {"id": "RFP-3", "title": "Raw JSON Test", "agency": "AEE",
             "posted_date": "2023-07-01", "due_date": "2023-08-01",
             "estimated_value": "300000", "status": "open"}
        ]

        with patch("scripts.download_compras._session") as mock_session_fn, \
             patch("scripts.download_compras.time.sleep"):
            mock_session_fn.return_value = _make_mock_session(rfp_records=rfp_records)
            run(root=tmp_path, force=True, max_pages=1)

        raw_json = tmp_path / "data" / "staging" / "raw" / "compras" / "compras_rfps_raw.json"
        assert raw_json.exists()
        data = json.loads(raw_json.read_text())
        assert isinstance(data, list)
        assert len(data) == 1

    def test_run_rfp_row_count_returned(self, tmp_path):
        """run() returns rfp_rows count in result dict."""
        (tmp_path / "data" / "logs").mkdir(parents=True)

        rfp_records = [
            {"id": f"RFP-{i}", "title": f"RFP {i}", "agency": "Test",
             "estimated_value": "1000"}
            for i in range(5)
        ]

        with patch("scripts.download_compras._session") as mock_session_fn, \
             patch("scripts.download_compras.time.sleep"):
            mock_session_fn.return_value = _make_mock_session(rfp_records=rfp_records)
            result = run(root=tmp_path, force=True, max_pages=1)

        assert "rfp_rows" in result
        assert result["rfp_rows"] == 5

    def test_run_award_row_count_returned(self, tmp_path):
        """run() returns award_rows count in result dict."""
        (tmp_path / "data" / "logs").mkdir(parents=True)

        award_records = [
            {"id": f"AWD-{i}", "vendor": f"Corp {i}", "awarded_amount": "1000"}
            for i in range(3)
        ]

        with patch("scripts.download_compras._session") as mock_session_fn, \
             patch("scripts.download_compras.time.sleep"):
            mock_session_fn.return_value = _make_mock_session(award_records=award_records)
            result = run(root=tmp_path, force=True, max_pages=1)

        assert "award_rows" in result
        assert result["award_rows"] == 3
