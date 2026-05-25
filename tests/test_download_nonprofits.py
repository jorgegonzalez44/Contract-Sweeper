"""Tests for scripts/download_nonprofits.py — IRS 990 nonprofit downloader."""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Suppress log noise from the module under test and test logger
logging.getLogger("download_nonprofits").setLevel(logging.CRITICAL)
logging.getLogger("test").setLevel(logging.CRITICAL)

from scripts.download_nonprofits import (
    NTEE_LABELS,
    OUTPUT_COLUMNS,
    PROPUBLICA_BASE,
    _fetch_detail,
    _get,
    _list_orgs,
    _num,
    _session,
    run,
)


# ---------------------------------------------------------------------------
# _num — numeric coercion helper
# ---------------------------------------------------------------------------

class TestNum:
    def test_integer_returns_float(self):
        assert _num(1_000_000) == 1_000_000.0

    def test_string_integer_returns_float(self):
        assert _num("500000") == 500_000.0

    def test_float_string_returns_float(self):
        assert _num("1234.56") == 1234.56

    def test_none_returns_empty_string(self):
        assert _num(None) == ""

    def test_empty_string_returns_empty_string(self):
        assert _num("") == ""

    def test_non_numeric_string_returns_empty_string(self):
        assert _num("N/A") == ""

    def test_zero_is_valid(self):
        assert _num(0) == 0.0

    def test_negative_number_returns_float(self):
        assert _num(-99999) == -99999.0


# ---------------------------------------------------------------------------
# NTEE_LABELS constant
# ---------------------------------------------------------------------------

class TestNteeLabels:
    def test_contains_common_categories(self):
        assert "E" in NTEE_LABELS
        assert NTEE_LABELS["E"] == "Health"

    def test_education_category(self):
        assert NTEE_LABELS["B"] == "Education"

    def test_unknown_category(self):
        assert NTEE_LABELS["Z"] == "Unknown"

    def test_all_values_are_strings(self):
        for key, val in NTEE_LABELS.items():
            assert isinstance(val, str)
            assert len(val) > 0


# ---------------------------------------------------------------------------
# OUTPUT_COLUMNS constant
# ---------------------------------------------------------------------------

class TestOutputColumns:
    def test_ein_and_name_present(self):
        assert "ein" in OUTPUT_COLUMNS
        assert "name" in OUTPUT_COLUMNS

    def test_financial_columns_present(self):
        for col in ("total_revenue", "total_expenses", "total_assets"):
            assert col in OUTPUT_COLUMNS

    def test_ntee_category_present(self):
        assert "ntee_category" in OUTPUT_COLUMNS

    def test_is_list_of_strings(self):
        assert isinstance(OUTPUT_COLUMNS, list)
        for col in OUTPUT_COLUMNS:
            assert isinstance(col, str)


# ---------------------------------------------------------------------------
# _session — requests.Session factory
# ---------------------------------------------------------------------------

class TestSession:
    def test_returns_session_with_user_agent(self):
        sess = _session()
        assert "User-Agent" in sess.headers
        assert "ContractSweeper" in sess.headers["User-Agent"]

    def test_accept_header_is_json(self):
        sess = _session()
        assert sess.headers.get("Accept") == "application/json"


# ---------------------------------------------------------------------------
# _get — retry/error-handling wrapper around session.get
# ---------------------------------------------------------------------------

class TestGet:
    def _make_response(self, status_code: int, json_data=None, raise_exc=None):
        resp = MagicMock()
        resp.status_code = status_code
        if json_data is not None:
            resp.json.return_value = json_data
        if raise_exc:
            resp.raise_for_status.side_effect = raise_exc
        else:
            resp.raise_for_status.return_value = None
        resp.text = ""
        return resp

    def test_successful_response_returns_json(self):
        session = MagicMock()
        session.get.return_value = self._make_response(200, {"key": "value"})
        logger = logging.getLogger("test")
        result = _get(session, "http://example.com", {}, logger)
        assert result == {"key": "value"}

    def test_404_returns_none(self):
        session = MagicMock()
        session.get.return_value = self._make_response(404)
        logger = logging.getLogger("test")
        result = _get(session, "http://example.com", {}, logger)
        assert result is None

    def test_client_error_4xx_returns_none(self):
        session = MagicMock()
        session.get.return_value = self._make_response(400)
        logger = logging.getLogger("test")
        result = _get(session, "http://example.com", {}, logger)
        assert result is None

    def test_network_exception_exhausts_retries_and_returns_none(self):
        import requests as req_module
        session = MagicMock()
        session.get.side_effect = req_module.RequestException("connection error")
        logger = logging.getLogger("test")
        with patch("scripts.download_nonprofits.time.sleep"):
            result = _get(session, "http://example.com", {}, logger)
        assert result is None


# ---------------------------------------------------------------------------
# _list_orgs — pagination through ProPublica search endpoint
# ---------------------------------------------------------------------------

class TestListOrgs:
    def _make_page(self, orgs, total=None):
        data = {"organizations": orgs}
        if total is not None:
            data["total_results"] = total
        return data

    def test_returns_all_orgs_across_pages(self):
        page0 = self._make_page([{"ein": "11-1111111", "name": "Org A"}], total=2)
        page1 = self._make_page([{"ein": "22-2222222", "name": "Org B"}])
        page2 = self._make_page([])  # signals end of pagination

        session = MagicMock()
        logger = logging.getLogger("test")

        with patch("scripts.download_nonprofits._get", side_effect=[page0, page1, page2]):
            with patch("scripts.download_nonprofits.time.sleep"):
                orgs = _list_orgs(session, logger)

        assert len(orgs) == 2
        assert orgs[0]["ein"] == "11-1111111"

    def test_stops_on_none_response(self):
        session = MagicMock()
        logger = logging.getLogger("test")

        with patch("scripts.download_nonprofits._get", return_value=None):
            with patch("scripts.download_nonprofits.time.sleep"):
                orgs = _list_orgs(session, logger)

        assert orgs == []

    def test_stops_on_empty_organizations_key(self):
        session = MagicMock()
        logger = logging.getLogger("test")

        with patch("scripts.download_nonprofits._get", return_value={"organizations": []}):
            with patch("scripts.download_nonprofits.time.sleep"):
                orgs = _list_orgs(session, logger)

        assert orgs == []

    def test_url_uses_propublica_base(self):
        """_list_orgs calls _get with the correct search endpoint URL."""
        session = MagicMock()
        logger = logging.getLogger("test")

        captured = []

        def mock_get(sess, url, params, lgr):
            captured.append(url)
            return None  # stops after first call

        with patch("scripts.download_nonprofits._get", side_effect=mock_get):
            with patch("scripts.download_nonprofits.time.sleep"):
                _list_orgs(session, logger)

        assert len(captured) >= 1
        assert captured[0].startswith(PROPUBLICA_BASE)
        assert "search" in captured[0]


# ---------------------------------------------------------------------------
# _fetch_detail — 990 detail parser
# ---------------------------------------------------------------------------

class TestFetchDetail:
    def _org_data(self, filings=None):
        return {
            "organization": {"ein": "12-3456789"},
            "filings_with_data": filings or [],
        }

    def _filing(self, year=2022, revenue=1_000_000, expenses=800_000,
                assets=2_000_000, liabilities=500_000):
        return {
            "tax_prd_yr": str(year),
            "totrevenue": revenue,
            "totfuncexpns": expenses,
            "totassetsend": assets,
            "totliabend": liabilities,
            "totcntrbgfts": 50_000,
            "totgrnts": 30_000,
            "compnsatncurrofcr": 120_000,
            "noemployees": 15,
        }

    def test_returns_empty_dict_when_no_filings(self):
        session = MagicMock()
        logger = logging.getLogger("test")
        data = self._org_data(filings=[])
        with patch("scripts.download_nonprofits._get", return_value=data):
            with patch("scripts.download_nonprofits.time.sleep"):
                result = _fetch_detail(session, "12-3456789", logger)
        assert result == {}

    def test_returns_empty_dict_on_none_response(self):
        session = MagicMock()
        logger = logging.getLogger("test")
        with patch("scripts.download_nonprofits._get", return_value=None):
            with patch("scripts.download_nonprofits.time.sleep"):
                result = _fetch_detail(session, "12-3456789", logger)
        assert result == {}

    def test_extracts_latest_filing_year(self):
        session = MagicMock()
        logger = logging.getLogger("test")
        data = self._org_data(filings=[self._filing(year=2023)])
        with patch("scripts.download_nonprofits._get", return_value=data):
            with patch("scripts.download_nonprofits.time.sleep"):
                result = _fetch_detail(session, "12-3456789", logger)
        assert result["latest_filing_year"] == "2023"

    def test_extracts_total_revenue(self):
        session = MagicMock()
        logger = logging.getLogger("test")
        data = self._org_data(filings=[self._filing(revenue=999_000)])
        with patch("scripts.download_nonprofits._get", return_value=data):
            with patch("scripts.download_nonprofits.time.sleep"):
                result = _fetch_detail(session, "12-3456789", logger)
        assert result["total_revenue"] == 999_000.0

    def test_computes_revenue_trend_with_four_filings(self):
        session = MagicMock()
        logger = logging.getLogger("test")
        # filings[0]=latest, filings[3]=3 years ago
        filings = [
            self._filing(year=2023, revenue=2_000_000),
            self._filing(year=2022, revenue=1_500_000),
            self._filing(year=2021, revenue=1_200_000),
            self._filing(year=2020, revenue=1_000_000),
        ]
        data = self._org_data(filings=filings)
        with patch("scripts.download_nonprofits._get", return_value=data):
            with patch("scripts.download_nonprofits.time.sleep"):
                result = _fetch_detail(session, "12-3456789", logger)
        # trend = (2M - 1M) / 1M * 100 = +100%
        assert result["revenue_trend"] == "+100%"

    def test_no_trend_with_fewer_than_four_filings(self):
        session = MagicMock()
        logger = logging.getLogger("test")
        filings = [
            self._filing(year=2023, revenue=2_000_000),
            self._filing(year=2022, revenue=1_500_000),
        ]
        data = self._org_data(filings=filings)
        with patch("scripts.download_nonprofits._get", return_value=data):
            with patch("scripts.download_nonprofits.time.sleep"):
                result = _fetch_detail(session, "12-3456789", logger)
        assert result["revenue_trend"] == ""


# ---------------------------------------------------------------------------
# run() integration tests
# ---------------------------------------------------------------------------

def _make_org(ein="11-1111111", name="Test Nonprofit", city="San Juan",
              state="PR", revenue_amt=1_000_000, ntee_code="B01",
              ruling_year_month="201501", subsection_code="3"):
    return {
        "ein": ein,
        "name": name,
        "city": city,
        "state": state,
        "revenue_amt": revenue_amt,
        "ntee_code": ntee_code,
        "ruling_year_month": ruling_year_month,
        "subsection_code": subsection_code,
    }


def _make_detail_response(ein="11-1111111", revenue=1_000_000):
    return {
        "organization": {"ein": ein},
        "filings_with_data": [
            {
                "tax_prd_yr": "2022",
                "totrevenue": revenue,
                "totfuncexpns": 800_000,
                "totassetsend": 2_000_000,
                "totliabend": 500_000,
                "totcntrbgfts": 50_000,
                "totgrnts": 30_000,
                "compnsatncurrofcr": 120_000,
                "noemployees": 15,
            }
        ],
    }


class TestRunCaching:
    """run(force=False) uses cached raw CSV when it already exists."""

    def test_skips_http_when_raw_csv_exists(self, tmp_path):
        """Pre-existing raw CSV causes org-list phase to load from disk (no HTTP)."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "nonprofits"
        raw_dir.mkdir(parents=True)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        # Pre-create a raw CSV with one org that has low revenue so no detail call
        org = _make_org(revenue_amt=0)
        pd.DataFrame([org]).to_csv(raw_dir / "pr_nonprofits_raw.csv", index=False)

        with patch("scripts.download_nonprofits._session") as mock_session_cls:
            mock_sess = MagicMock()
            mock_session_cls.return_value = mock_sess
            # No detail calls expected for revenue=0
            with patch("scripts.download_nonprofits._fetch_detail", return_value={}):
                result = run(root=tmp_path, force=False)

        # _list_orgs should NOT have made HTTP requests
        mock_sess.get.assert_not_called()
        assert isinstance(result, dict)
        assert result["status"] in ("OK", "EMPTY")

    def test_output_csv_written_to_processed_dir(self, tmp_path):
        """run() writes pr_nonprofits.csv in processed directory."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "nonprofits"
        raw_dir.mkdir(parents=True)
        processed_dir = tmp_path / "data" / "staging" / "processed"
        processed_dir.mkdir(parents=True)

        org = _make_org(revenue_amt=0)
        pd.DataFrame([org]).to_csv(raw_dir / "pr_nonprofits_raw.csv", index=False)

        with patch("scripts.download_nonprofits._fetch_detail", return_value={}):
            result = run(root=tmp_path, force=False)

        out_path = tmp_path / "data" / "staging" / "processed" / "pr_nonprofits.csv"
        assert out_path.exists()
        assert result["path"] == str(out_path)


class TestRunWithMockedHttp:
    """run() with mocked HTTP session fetches orgs and writes output."""

    def test_returns_dict_with_expected_keys(self, tmp_path):
        """run() always returns a dict with rows, status, path."""
        search_page0 = {
            "organizations": [_make_org(revenue_amt=0)],
            "total_results": 1,
        }
        search_page1 = {"organizations": []}

        def mock_get_side_effect(session, url, params, logger):
            if "search" in url:
                page = params.get("page", 0)
                return search_page0 if page == 0 else search_page1
            # detail endpoint
            return _make_detail_response()

        with patch("scripts.download_nonprofits._get", side_effect=mock_get_side_effect):
            with patch("scripts.download_nonprofits.time.sleep"):
                result = run(root=tmp_path, force=True)

        assert isinstance(result, dict)
        assert "rows" in result
        assert "status" in result
        assert "path" in result

    def test_rows_count_matches_orgs_fetched(self, tmp_path):
        """run() rows count equals number of unique orgs."""
        orgs = [_make_org(ein=f"11-{i:07d}", revenue_amt=0) for i in range(3)]
        search_page0 = {"organizations": orgs, "total_results": 3}
        search_page1 = {"organizations": []}

        def mock_get_side_effect(session, url, params, logger):
            if "search" in url:
                page = params.get("page", 0)
                return search_page0 if page == 0 else search_page1
            return _make_detail_response()

        with patch("scripts.download_nonprofits._get", side_effect=mock_get_side_effect):
            with patch("scripts.download_nonprofits.time.sleep"):
                result = run(root=tmp_path, force=True)

        assert result["rows"] == 3

    def test_output_csv_has_output_columns(self, tmp_path):
        """Written CSV has exactly the OUTPUT_COLUMNS headers."""
        orgs = [_make_org(revenue_amt=0)]
        search_page0 = {"organizations": orgs, "total_results": 1}
        search_page1 = {"organizations": []}

        def mock_get_side_effect(session, url, params, logger):
            if "search" in url:
                page = params.get("page", 0)
                return search_page0 if page == 0 else search_page1
            return _make_detail_response()

        with patch("scripts.download_nonprofits._get", side_effect=mock_get_side_effect):
            with patch("scripts.download_nonprofits.time.sleep"):
                result = run(root=tmp_path, force=True)

        df = pd.read_csv(result["path"])
        for col in OUTPUT_COLUMNS:
            assert col in df.columns

    def test_empty_response_writes_empty_master(self, tmp_path):
        """If ProPublica returns no orgs, run() writes empty CSV with EMPTY status."""
        with patch("scripts.download_nonprofits._get", return_value=None):
            with patch("scripts.download_nonprofits.time.sleep"):
                result = run(root=tmp_path, force=True)

        assert result["rows"] == 0
        assert result["status"] == "EMPTY"

    def test_ntee_category_resolved_in_output(self, tmp_path):
        """NTEE code is translated to human-readable category in output CSV."""
        org = _make_org(ein="11-9999999", revenue_amt=0, ntee_code="E10")
        search_page0 = {"organizations": [org], "total_results": 1}
        search_page1 = {"organizations": []}

        def mock_get_side_effect(session, url, params, logger):
            if "search" in url:
                page = params.get("page", 0)
                return search_page0 if page == 0 else search_page1
            return _make_detail_response()

        with patch("scripts.download_nonprofits._get", side_effect=mock_get_side_effect):
            with patch("scripts.download_nonprofits.time.sleep"):
                result = run(root=tmp_path, force=True)

        df = pd.read_csv(result["path"])
        assert df["ntee_category"].iloc[0] == "Health"

    def test_detail_fetched_for_high_revenue_org(self, tmp_path):
        """_fetch_detail is called for orgs meeting the revenue threshold."""
        org = _make_org(ein="99-9999999", revenue_amt=1_000_000)
        search_page0 = {"organizations": [org], "total_results": 1}
        search_page1 = {"organizations": []}

        search_calls = []
        detail_calls = []

        def mock_get_side_effect(session, url, params, logger):
            if "search" in url:
                search_calls.append(params.get("page", 0))
                page = params.get("page", 0)
                return search_page0 if page == 0 else search_page1
            else:
                detail_calls.append(url)
                return _make_detail_response(ein="99-9999999", revenue=1_000_000)

        with patch("scripts.download_nonprofits._get", side_effect=mock_get_side_effect):
            with patch("scripts.download_nonprofits.time.sleep"):
                run(root=tmp_path, force=True, min_revenue=500_000)

        # At least one detail URL was requested
        assert len(detail_calls) >= 1

    def test_raw_csv_written_during_force_download(self, tmp_path):
        """When force=True, raw org list CSV is written."""
        org = _make_org(revenue_amt=0)
        search_page0 = {"organizations": [org], "total_results": 1}
        search_page1 = {"organizations": []}

        def mock_get_side_effect(session, url, params, logger):
            if "search" in url:
                page = params.get("page", 0)
                return search_page0 if page == 0 else search_page1
            return _make_detail_response()

        with patch("scripts.download_nonprofits._get", side_effect=mock_get_side_effect):
            with patch("scripts.download_nonprofits.time.sleep"):
                run(root=tmp_path, force=True)

        raw_path = tmp_path / "data" / "staging" / "raw" / "nonprofits" / "pr_nonprofits_raw.csv"
        assert raw_path.exists()

    def test_status_ok_when_orgs_present(self, tmp_path):
        """run() returns status='OK' when at least one org is processed."""
        org = _make_org(revenue_amt=0)
        search_page0 = {"organizations": [org], "total_results": 1}
        search_page1 = {"organizations": []}

        def mock_get_side_effect(session, url, params, logger):
            if "search" in url:
                page = params.get("page", 0)
                return search_page0 if page == 0 else search_page1
            return _make_detail_response()

        with patch("scripts.download_nonprofits._get", side_effect=mock_get_side_effect):
            with patch("scripts.download_nonprofits.time.sleep"):
                result = run(root=tmp_path, force=True)

        assert result["status"] == "OK"
