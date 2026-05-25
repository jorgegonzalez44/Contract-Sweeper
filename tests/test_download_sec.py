"""Tests for scripts/download_sec.py — pure helpers and run() integration."""

import logging
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from scripts.download_sec import (
    EDGAR_BASE,
    EFTS_BASE,
    PR_DOMICILED,
    PR_SIGNIFICANT,
    COMPANY_COLUMNS,
    FINANCIAL_COLUMNS,
    XBRL_CONCEPTS,
    _session,
    _extract_annual_series,
    _company_financials,
    _discover_pr_filers,
    _fetch_submissions,
    _fetch_xbrl_facts,
    run,
)

# Suppress all log noise from the module under test
logging.getLogger("download_sec").setLevel(logging.CRITICAL)
logging.getLogger("test").setLevel(logging.CRITICAL)


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

def test_edgar_base_url():
    """EDGAR_BASE points to the correct SEC domain."""
    assert EDGAR_BASE == "https://data.sec.gov"


def test_efts_base_url():
    """EFTS_BASE points to the correct full-text search domain."""
    assert EFTS_BASE == "https://efts.sec.gov"


def test_pr_domiciled_non_empty():
    """PR_DOMICILED list contains at least one entry with required keys."""
    assert len(PR_DOMICILED) >= 1
    for entry in PR_DOMICILED:
        assert "cik" in entry
        assert "ticker" in entry
        assert "name" in entry
        assert "sector" in entry


def test_pr_significant_non_empty():
    """PR_SIGNIFICANT list contains at least one entry."""
    assert len(PR_SIGNIFICANT) >= 1


def test_company_columns_completeness():
    """COMPANY_COLUMNS includes key fields."""
    required = {"cik", "ticker", "name", "sector", "pr_domiciled"}
    assert required.issubset(set(COMPANY_COLUMNS))


def test_financial_columns_completeness():
    """FINANCIAL_COLUMNS includes key financial fields."""
    required = {"cik", "ticker", "fiscal_year", "total_revenues", "net_income"}
    assert required.issubset(set(FINANCIAL_COLUMNS))


# ---------------------------------------------------------------------------
# _session
# ---------------------------------------------------------------------------

def test_session_has_user_agent():
    """_session() returns a requests.Session with a User-Agent header."""
    s = _session()
    assert "User-Agent" in s.headers
    assert len(s.headers["User-Agent"]) > 0


def test_session_accept_json():
    """_session() sets Accept: application/json."""
    s = _session()
    assert s.headers.get("Accept") == "application/json"


# ---------------------------------------------------------------------------
# _extract_annual_series — pure function
# ---------------------------------------------------------------------------

def _make_facts(concept: str, entries: list, taxonomy: str = "us-gaap") -> dict:
    """Build a minimal XBRL facts dict for testing."""
    return {
        "facts": {
            taxonomy: {
                concept: {
                    "units": {
                        "USD": entries,
                    }
                }
            }
        }
    }


def test_extract_annual_series_empty_facts():
    """_extract_annual_series returns [] for empty facts."""
    result = _extract_annual_series({}, ["Revenues"])
    assert result == []


def test_extract_annual_series_no_matching_concept():
    """_extract_annual_series returns [] when no matching concept exists."""
    facts = _make_facts("SomethingElse", [
        {"form": "10-K", "end": "2022-12-31", "val": 1000, "fp": "FY", "filed": "2023-02-15"},
    ])
    result = _extract_annual_series(facts, ["Revenues"])
    assert result == []


def test_extract_annual_series_basic():
    """_extract_annual_series extracts (year, value) pairs from 10-K entries."""
    facts = _make_facts("Revenues", [
        {"form": "10-K", "end": "2021-12-31", "val": 500_000_000, "fp": "FY", "filed": "2022-02-01"},
        {"form": "10-K", "end": "2022-12-31", "val": 600_000_000, "fp": "FY", "filed": "2023-02-01"},
    ])
    result = _extract_annual_series(facts, ["Revenues"])
    assert (2021, 500_000_000.0) in result
    assert (2022, 600_000_000.0) in result


def test_extract_annual_series_skips_non_annual():
    """_extract_annual_series skips non-10-K forms (e.g. 10-Q)."""
    facts = _make_facts("Revenues", [
        {"form": "10-Q", "end": "2022-06-30", "val": 200_000_000, "fp": "Q2", "filed": "2022-08-01"},
        {"form": "10-K", "end": "2022-12-31", "val": 800_000_000, "fp": "FY", "filed": "2023-02-01"},
    ])
    result = _extract_annual_series(facts, ["Revenues"])
    assert len(result) == 1
    assert result[0][0] == 2022


def test_extract_annual_series_deduplicates_by_year():
    """_extract_annual_series keeps the latest-filed entry per fiscal year."""
    facts = _make_facts("Revenues", [
        {"form": "10-K", "end": "2022-12-31", "val": 100, "fp": "FY", "filed": "2023-01-01"},
        {"form": "10-K", "end": "2022-12-31", "val": 200, "fp": "FY", "filed": "2023-06-01"},  # amended
    ])
    result = _extract_annual_series(facts, ["Revenues"])
    assert len(result) == 1
    assert result[0] == (2022, 200.0)


def test_extract_annual_series_tries_concepts_in_order():
    """_extract_annual_series tries concept names in order and uses the first hit."""
    facts = _make_facts("NetIncomeLoss", [
        {"form": "10-K", "end": "2022-12-31", "val": 50_000, "fp": "FY", "filed": "2023-01-01"},
    ])
    # NetIncomeLoss should be found before ProfitLoss
    result = _extract_annual_series(facts, ["NetIncomeLoss", "ProfitLoss"])
    assert len(result) == 1
    assert result[0][1] == 50_000.0


def test_extract_annual_series_unit_filter():
    """_extract_annual_series respects the unit_filter parameter."""
    facts = {
        "facts": {
            "us-gaap": {
                "CommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"form": "10-K", "end": "2022-12-31", "val": 1_000_000, "fp": "FY", "filed": "2023-01-01"}
                        ]
                    }
                }
            }
        }
    }
    # unit_filter="USD" should find nothing (data is in shares)
    result_usd = _extract_annual_series(facts, ["CommonStockSharesOutstanding"], unit_filter="USD")
    assert result_usd == []

    # unit_filter="any" should find the entry
    result_any = _extract_annual_series(facts, ["CommonStockSharesOutstanding"], unit_filter="any")
    assert len(result_any) == 1


# ---------------------------------------------------------------------------
# _company_financials — pure function
# ---------------------------------------------------------------------------

def test_company_financials_empty_facts():
    """_company_financials returns [] for empty XBRL facts."""
    rows = _company_financials("0000123456", "TST", "Test Corp", {})
    assert rows == []


def test_company_financials_basic():
    """_company_financials produces correctly structured rows."""
    facts = _make_facts("Revenues", [
        {"form": "10-K", "end": "2022-12-31", "val": 1_000_000_000, "fp": "FY", "filed": "2023-02-01"},
    ])
    rows = _company_financials("0000123456", "TST", "Test Corp", facts)
    assert len(rows) == 1
    row = rows[0]
    assert row["cik"] == "0000123456"
    assert row["ticker"] == "TST"
    assert row["name"] == "Test Corp"
    assert row["fiscal_year"] == 2022
    assert row["total_revenues"] == pytest.approx(1_000_000_000.0)
    # All FINANCIAL_COLUMNS should be present
    for col in FINANCIAL_COLUMNS:
        assert col in row


def test_company_financials_multiple_years():
    """_company_financials returns one row per fiscal year."""
    facts = _make_facts("Revenues", [
        {"form": "10-K", "end": "2020-12-31", "val": 100, "fp": "FY", "filed": "2021-02-01"},
        {"form": "10-K", "end": "2021-12-31", "val": 200, "fp": "FY", "filed": "2022-02-01"},
        {"form": "10-K", "end": "2022-12-31", "val": 300, "fp": "FY", "filed": "2023-02-01"},
    ])
    rows = _company_financials("0000000001", "X", "Co X", facts)
    assert len(rows) == 3
    years = [r["fiscal_year"] for r in rows]
    assert years == sorted(years)


# ---------------------------------------------------------------------------
# _discover_pr_filers — mocked HTTP
# ---------------------------------------------------------------------------

def test_discover_pr_filers_returns_empty_on_none_response():
    """_discover_pr_filers returns [] when HTTP call returns None."""
    logger = MagicMock()
    session = MagicMock()
    with patch("scripts.download_sec._get", return_value=None):
        result = _discover_pr_filers(session, logger)
    assert result == []


def test_discover_pr_filers_parses_hits():
    """_discover_pr_filers parses hits from EFTS search response."""
    mock_response = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "entity_id": 9999999,
                        "display_names": ["New PR Corp"],
                    }
                }
            ]
        }
    }
    logger = MagicMock()
    session = MagicMock()
    with patch("scripts.download_sec._get", return_value=mock_response):
        result = _discover_pr_filers(session, logger)
    assert len(result) == 1
    assert result[0]["name"] == "New PR Corp"
    assert result[0]["sector"] == "Discovered"


def test_discover_pr_filers_skips_known_ciks():
    """_discover_pr_filers does not return CIKs already in PR_DOMICILED/PR_SIGNIFICANT."""
    # Use a known CIK from PR_DOMICILED
    known_cik = int(PR_DOMICILED[0]["cik"])
    mock_response = {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "entity_id": known_cik,
                        "display_names": ["Popular Inc"],
                    }
                }
            ]
        }
    }
    logger = MagicMock()
    session = MagicMock()
    with patch("scripts.download_sec._get", return_value=mock_response):
        result = _discover_pr_filers(session, logger)
    assert result == []


# ---------------------------------------------------------------------------
# _fetch_submissions / _fetch_xbrl_facts — URL construction
# ---------------------------------------------------------------------------

def test_fetch_submissions_uses_correct_url():
    """_fetch_submissions calls _get with the expected CIK-formatted URL."""
    logger = MagicMock()
    session = MagicMock()
    with patch("scripts.download_sec._get", return_value=None) as mock_get:
        _fetch_submissions(session, "0000763901", logger)
    call_args = mock_get.call_args
    url = call_args[0][1]
    assert "CIK0000763901.json" in url
    assert url.startswith(EDGAR_BASE)


def test_fetch_xbrl_facts_uses_correct_url():
    """_fetch_xbrl_facts calls _get with the expected XBRL company facts URL."""
    logger = MagicMock()
    session = MagicMock()
    with patch("scripts.download_sec._get", return_value=None) as mock_get:
        _fetch_xbrl_facts(session, "0000049826", logger)
    call_args = mock_get.call_args
    url = call_args[0][1]
    assert "companyfacts/CIK0000049826.json" in url
    assert url.startswith(EDGAR_BASE)


# ---------------------------------------------------------------------------
# run() integration — cache hit (force=False)
# ---------------------------------------------------------------------------

def test_run_uses_cache_when_files_exist(tmp_path):
    """run() with force=False returns cached data without making HTTP calls."""
    raw_dir = tmp_path / "data" / "staging" / "raw" / "sec"
    raw_dir.mkdir(parents=True)
    out_dir = tmp_path / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True)

    # Pre-create the cached CSV files
    df_co = pd.DataFrame([{
        "cik": "0000763901", "ticker": "BPOP", "name": "Popular Inc",
        "sector": "Banking", "pr_domiciled": True,
        "sic": "6022", "sic_description": "State bank", "state_of_inc": "PR",
        "fiscal_year_end": "1231", "latest_10k_date": "2023-02-15",
        "total_employees": "12000",
    }])
    df_fin = pd.DataFrame([{
        "cik": "0000763901", "ticker": "BPOP", "name": "Popular Inc",
        "fiscal_year": 2022, "total_revenues": 2_500_000_000,
        "net_income": 600_000_000, "total_assets": None,
        "total_liabilities": None, "stockholders_equity": None,
        "operating_income": None, "r_and_d_expense": None,
        "shares_outstanding": None,
    }])
    df_co.to_csv(raw_dir / "pr_sec_companies.csv", index=False)
    df_fin.to_csv(raw_dir / "pr_sec_financials.csv", index=False)

    # Patch setup_logging to avoid creating log files in unexpected places
    with patch("scripts.download_sec.setup_logging") as mock_log:
        mock_log.return_value = MagicMock()
        result = run(root=tmp_path, force=False)

    assert result["status"] == "OK"
    assert result["company_rows"] == 1
    assert result["financial_rows"] == 1

    # Processed outputs must be written
    assert (out_dir / "pr_sec_companies.csv").exists()
    assert (out_dir / "pr_sec_financials.csv").exists()


def test_run_cache_skips_http(tmp_path):
    """run() with cached files does not call any HTTP endpoints."""
    raw_dir = tmp_path / "data" / "staging" / "raw" / "sec"
    raw_dir.mkdir(parents=True)
    out_dir = tmp_path / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True)

    pd.DataFrame(columns=["cik", "ticker", "name", "sector", "pr_domiciled",
                           "sic", "sic_description", "state_of_inc",
                           "fiscal_year_end", "latest_10k_date", "total_employees"]
                 ).to_csv(raw_dir / "pr_sec_companies.csv", index=False)
    pd.DataFrame(columns=["cik", "ticker", "name", "fiscal_year",
                           "total_revenues", "net_income", "total_assets",
                           "total_liabilities", "stockholders_equity",
                           "operating_income", "r_and_d_expense", "shares_outstanding"]
                 ).to_csv(raw_dir / "pr_sec_financials.csv", index=False)

    with patch("scripts.download_sec.setup_logging") as mock_log, \
         patch("scripts.download_sec._get") as mock_http:
        mock_log.return_value = MagicMock()
        run(root=tmp_path, force=False)

    mock_http.assert_not_called()


# ---------------------------------------------------------------------------
# run() integration — download path (force=True), mocked HTTP
# ---------------------------------------------------------------------------

def _make_submission_response(cik: str, name: str) -> dict:
    """Minimal EDGAR submissions JSON for one company."""
    return {
        "cik": cik,
        "name": name,
        "entityType": "operating",
        "sic": "6022",
        "sicDescription": "State commercial banks",
        "stateOfIncorporation": "PR",
        "fiscalYearEnd": "1231",
        "filings": {
            "recent": {
                "form":        ["10-K", "10-Q"],
                "filingDate":  ["2023-02-15", "2023-05-10"],
            }
        }
    }


def _make_xbrl_response(cik: str, revenue: float) -> dict:
    """Minimal XBRL company facts JSON."""
    return {
        "cik": cik,
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "form": "10-K",
                                "end": "2022-12-31",
                                "val": revenue,
                                "fp": "FY",
                                "filed": "2023-02-15",
                            }
                        ]
                    }
                }
            },
            "dei": {}
        }
    }


def test_run_force_downloads_and_writes_csvs(tmp_path):
    """run(force=True) fetches data and writes both raw and processed CSVs."""
    # We intercept _discover_pr_filers to return empty and
    # _get to return minimal submission + xbrl data per call.
    call_count = {"n": 0}

    def fake_get(session, url, params, logger):
        call_count["n"] += 1
        if "submissions" in url:
            cik = url.split("CIK")[1].replace(".json", "")
            return _make_submission_response(cik, f"Company {cik}")
        if "companyfacts" in url:
            cik = url.split("CIK")[1].replace(".json", "")
            return _make_xbrl_response(cik, 1_000_000.0)
        return None

    with patch("scripts.download_sec.setup_logging") as mock_log, \
         patch("scripts.download_sec._discover_pr_filers", return_value=[]), \
         patch("scripts.download_sec._get", side_effect=fake_get):
        mock_log.return_value = MagicMock()
        result = run(root=tmp_path, force=True)

    assert result["status"] in ("OK", "EMPTY")
    raw_co  = tmp_path / "data" / "staging" / "raw" / "sec" / "pr_sec_companies.csv"
    raw_fin = tmp_path / "data" / "staging" / "raw" / "sec" / "pr_sec_financials.csv"
    assert raw_co.exists()
    assert raw_fin.exists()

    df_co = pd.read_csv(raw_co, dtype=str)
    assert set(COMPANY_COLUMNS).issubset(df_co.columns)


def test_run_force_financial_columns_present(tmp_path):
    """run(force=True) produces financial CSV with all required columns."""
    def fake_get(session, url, params, logger):
        if "submissions" in url:
            cik = url.split("CIK")[1].replace(".json", "")
            return _make_submission_response(cik, f"Company {cik}")
        if "companyfacts" in url:
            cik = url.split("CIK")[1].replace(".json", "")
            return _make_xbrl_response(cik, 999_999.0)
        return None

    with patch("scripts.download_sec.setup_logging") as mock_log, \
         patch("scripts.download_sec._discover_pr_filers", return_value=[]), \
         patch("scripts.download_sec._get", side_effect=fake_get):
        mock_log.return_value = MagicMock()
        run(root=tmp_path, force=True)

    raw_fin = tmp_path / "data" / "staging" / "raw" / "sec" / "pr_sec_financials.csv"
    if raw_fin.stat().st_size > 5:  # non-trivial file
        df_fin = pd.read_csv(raw_fin, dtype=str)
        assert set(FINANCIAL_COLUMNS).issubset(df_fin.columns)


def test_run_returns_dict_with_expected_keys(tmp_path):
    """run() always returns a dict with company_rows, financial_rows, and status."""
    raw_dir = tmp_path / "data" / "staging" / "raw" / "sec"
    raw_dir.mkdir(parents=True)
    out_dir = tmp_path / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True)

    pd.DataFrame(columns=COMPANY_COLUMNS).to_csv(
        raw_dir / "pr_sec_companies.csv", index=False)
    pd.DataFrame(columns=FINANCIAL_COLUMNS).to_csv(
        raw_dir / "pr_sec_financials.csv", index=False)

    with patch("scripts.download_sec.setup_logging") as mock_log:
        mock_log.return_value = MagicMock()
        result = run(root=tmp_path, force=False)

    assert "company_rows" in result
    assert "financial_rows" in result
    assert "status" in result
    assert result["status"] in ("OK", "EMPTY")
