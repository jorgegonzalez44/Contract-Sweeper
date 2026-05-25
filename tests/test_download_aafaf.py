"""Tests for download_aafaf — URL helpers, row normalization, and run() integration."""

import logging
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.download_aafaf import (
    _session,
    _find_excel_links,
    _normalize_records,
    _parse_excel_to_records,
    AAFAF_COLUMNS,
    AAFAF_REPORTS_URL,
    PR_DATA_PORTAL_URL,
    run,
)

# Suppress noisy log output from the module under test
logging.getLogger("test").setLevel(logging.CRITICAL)
logging.getLogger("download_aafaf").setLevel(logging.CRITICAL)


# ---------------------------------------------------------------------------
# _session
# ---------------------------------------------------------------------------

def test_session_returns_configured_session():
    """_session() returns a requests.Session with custom User-Agent."""
    session = _session()
    assert session is not None
    assert "User-Agent" in session.headers
    assert "ContractSweeper" in session.headers["User-Agent"]


def test_session_accept_header_set():
    """_session() sets Accept header to include text/html."""
    session = _session()
    assert "Accept" in session.headers
    assert "text/html" in session.headers["Accept"]


# ---------------------------------------------------------------------------
# _find_excel_links
# ---------------------------------------------------------------------------

def test_find_excel_links_absolute_urls():
    """_find_excel_links extracts absolute https Excel links unchanged."""
    html = '<a href="https://example.com/report.xlsx">Download</a>'
    links = _find_excel_links(html, "https://example.com/")
    assert links == ["https://example.com/report.xlsx"]


def test_find_excel_links_root_relative():
    """_find_excel_links converts root-relative paths to absolute URLs."""
    html = '<a href="/files/budget.xlsx">Download</a>'
    links = _find_excel_links(html, "https://www.aafaf.pr.gov/informes/")
    assert len(links) == 1
    assert links[0].startswith("https://www.aafaf.pr.gov")
    assert links[0].endswith("/files/budget.xlsx")


def test_find_excel_links_relative_path():
    """_find_excel_links resolves relative paths against the base URL."""
    html = '<a href="docs/report.xls">Download</a>'
    links = _find_excel_links(html, "https://www.aafaf.pr.gov/informes/")
    assert len(links) == 1
    assert "docs/report.xls" in links[0]


def test_find_excel_links_csv_extension():
    """_find_excel_links picks up .csv links as well as .xlsx/.xls."""
    html = '<a href="https://example.com/data.csv">CSV</a>'
    links = _find_excel_links(html, "https://example.com/")
    assert links == ["https://example.com/data.csv"]


def test_find_excel_links_case_insensitive():
    """_find_excel_links is case-insensitive for extensions."""
    html = '<a href="https://example.com/REPORT.XLSX">Download</a>'
    links = _find_excel_links(html, "https://example.com/")
    assert len(links) == 1


def test_find_excel_links_no_excel_links():
    """_find_excel_links returns empty list when no Excel links present."""
    html = '<a href="https://example.com/page.html">Page</a>'
    links = _find_excel_links(html, "https://example.com/")
    assert links == []


def test_find_excel_links_multiple_links():
    """_find_excel_links extracts multiple links from a page."""
    html = """
    <a href="https://example.com/q1.xlsx">Q1</a>
    <a href="https://example.com/q2.xlsx">Q2</a>
    <a href="https://example.com/q3.csv">Q3</a>
    """
    links = _find_excel_links(html, "https://example.com/")
    assert len(links) == 3


# ---------------------------------------------------------------------------
# _normalize_records
# ---------------------------------------------------------------------------

def _null_logger():
    logger = logging.getLogger("test_null")
    logger.setLevel(logging.CRITICAL)
    return logger


def test_normalize_records_empty_returns_empty_df():
    """_normalize_records([]) returns an empty DataFrame with AAFAF_COLUMNS."""
    df = _normalize_records([], _null_logger())
    assert df.empty
    assert list(df.columns) == AAFAF_COLUMNS


def test_normalize_records_adds_missing_columns():
    """_normalize_records fills in missing AAFAF columns with empty string."""
    records = [{"source_doc": "http://example.com/x.xlsx", "report_type": "monthly_treasury"}]
    df = _normalize_records(records, _null_logger())
    assert set(AAFAF_COLUMNS).issubset(df.columns)
    for col in AAFAF_COLUMNS:
        assert col in df.columns


def test_normalize_records_fiscal_year_column_mapped():
    """_normalize_records maps a 'fiscal_year' key correctly."""
    records = [{"fiscal_year": "2024", "source_doc": "x.csv", "report_type": "monthly_treasury"}]
    df = _normalize_records(records, _null_logger())
    assert "fiscal_year" in df.columns
    assert df.iloc[0]["fiscal_year"] == "2024"


def test_normalize_records_revenue_amount_column_mapped():
    """_normalize_records maps revenue_amount-related column."""
    records = [{"revenue_amount": 1000.0, "source_doc": "x.csv", "report_type": "monthly_treasury"}]
    df = _normalize_records(records, _null_logger())
    assert "revenue_amount" in df.columns


def test_normalize_records_returns_only_aafaf_columns():
    """_normalize_records output contains exactly AAFAF_COLUMNS in order."""
    records = [
        {
            "fiscal_year": "2023",
            "month": "July",
            "report_type": "monthly_treasury",
            "revenue_amount": 500,
            "source_doc": "http://x.xlsx",
            "extra_col": "should_be_dropped",
        }
    ]
    df = _normalize_records(records, _null_logger())
    assert list(df.columns) == AAFAF_COLUMNS
    assert "extra_col" not in df.columns


def test_normalize_records_multiple_rows():
    """_normalize_records handles multiple records correctly."""
    records = [
        {"fiscal_year": "2023", "source_doc": "a.csv", "report_type": "monthly_treasury"},
        {"fiscal_year": "2024", "source_doc": "b.csv", "report_type": "monthly_treasury"},
    ]
    df = _normalize_records(records, _null_logger())
    assert len(df) == 2


# ---------------------------------------------------------------------------
# run() — caching path (force=False, file already exists)
# ---------------------------------------------------------------------------

def test_run_returns_cached_when_output_exists(tmp_path):
    """run() with force=False returns CACHED status if output CSV already exists."""
    out_dir = tmp_path / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True)
    csv_path = out_dir / "pr_aafaf_budget.csv"
    # Pre-create a non-empty CSV
    existing_df = pd.DataFrame([{col: "x" for col in AAFAF_COLUMNS}])
    existing_df.to_csv(csv_path, index=False, encoding="utf-8")

    result = run(root=tmp_path, force=False)
    assert result["status"] == "CACHED"
    assert result["rows"] == 1
    assert result["path"] == str(csv_path)


def test_run_cached_does_not_make_http_calls(tmp_path):
    """run() returns CACHED without any HTTP calls when output already exists."""
    out_dir = tmp_path / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True)
    csv_path = out_dir / "pr_aafaf_budget.csv"
    existing_df = pd.DataFrame([{col: "v" for col in AAFAF_COLUMNS}])
    existing_df.to_csv(csv_path, index=False, encoding="utf-8")

    with patch("scripts.download_aafaf.requests.Session") as mock_session_cls:
        result = run(root=tmp_path, force=False)
    # Session should never have been instantiated
    mock_session_cls.assert_not_called()
    assert result["status"] == "CACHED"


# ---------------------------------------------------------------------------
# run() — download path (mock HTTP, no real network calls)
# ---------------------------------------------------------------------------

def test_run_creates_empty_csv_when_no_data(tmp_path):
    """run() writes an empty CSV (EMPTY status) when HTTP returns nothing useful."""
    mock_session = MagicMock()
    # Both the AAFAF reports page and PR data portal return 404
    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 404
    mock_session.get.return_value = mock_resp_fail

    with patch("scripts.download_aafaf._session", return_value=mock_session), \
         patch("scripts.download_aafaf._get", return_value=None):
        result = run(root=tmp_path, force=True)

    assert result["status"] == "EMPTY"
    assert result["rows"] == 0
    out_path = Path(result["path"])
    assert out_path.exists()
    df = pd.read_csv(out_path)
    assert list(df.columns) == AAFAF_COLUMNS
    assert len(df) == 0


def test_run_creates_output_directory(tmp_path):
    """run() creates the output directory even if it does not exist."""
    with patch("scripts.download_aafaf._session") as mock_session_fn, \
         patch("scripts.download_aafaf._get", return_value=None):
        mock_session_fn.return_value = MagicMock()
        result = run(root=tmp_path, force=True)

    out_dir = tmp_path / "data" / "staging" / "processed"
    assert out_dir.exists()
    assert result["path"].endswith("pr_aafaf_budget.csv")


def test_run_force_ignores_cached_file(tmp_path):
    """run(force=True) re-runs even when a cached CSV exists."""
    out_dir = tmp_path / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True)
    csv_path = out_dir / "pr_aafaf_budget.csv"
    existing_df = pd.DataFrame([{col: "old" for col in AAFAF_COLUMNS}])
    existing_df.to_csv(csv_path, index=False, encoding="utf-8")

    with patch("scripts.download_aafaf._session") as mock_session_fn, \
         patch("scripts.download_aafaf._get", return_value=None):
        mock_session_fn.return_value = MagicMock()
        result = run(root=tmp_path, force=True)

    # Must not be CACHED — force bypassed the cache
    assert result["status"] != "CACHED"


def test_run_result_contains_required_keys(tmp_path):
    """run() always returns a dict with 'rows', 'path', and 'status' keys."""
    with patch("scripts.download_aafaf._session") as mock_session_fn, \
         patch("scripts.download_aafaf._get", return_value=None):
        mock_session_fn.return_value = MagicMock()
        result = run(root=tmp_path, force=True)

    assert "rows" in result
    assert "path" in result
    assert "status" in result


def test_run_with_mocked_records_writes_csv(tmp_path):
    """run() writes normalized records to CSV when data is available."""
    sample_records = [
        {
            "fiscal_year": "2024",
            "month": "January",
            "report_type": "monthly_treasury",
            "revenue_category": "Tax Revenue",
            "revenue_amount": 1500000,
            "expenditure_category": "Operations",
            "expenditure_amount": 1200000,
            "cash_balance": 300000,
            "source_doc": "http://example.com/jan2024.xlsx",
        }
    ]

    with patch("scripts.download_aafaf._session") as mock_session_fn, \
         patch("scripts.download_aafaf._fetch_aafaf_reports", return_value=sample_records), \
         patch("scripts.download_aafaf._fetch_pr_data_portal", return_value=[]):
        mock_session_fn.return_value = MagicMock()
        result = run(root=tmp_path, force=True)

    assert result["status"] == "OK"
    assert result["rows"] == 1
    out_path = Path(result["path"])
    assert out_path.exists()
    df = pd.read_csv(out_path, dtype=str)
    assert list(df.columns) == AAFAF_COLUMNS
    assert len(df) == 1


def test_run_skips_portal_when_aafaf_has_data(tmp_path):
    """run() does not call _fetch_pr_data_portal when AAFAF reports return data."""
    sample_records = [
        {col: "v" for col in AAFAF_COLUMNS}
    ]

    with patch("scripts.download_aafaf._session") as mock_session_fn, \
         patch("scripts.download_aafaf._fetch_aafaf_reports", return_value=sample_records) as mock_aafaf, \
         patch("scripts.download_aafaf._fetch_pr_data_portal") as mock_portal:
        mock_session_fn.return_value = MagicMock()
        run(root=tmp_path, force=True)

    mock_aafaf.assert_called_once()
    mock_portal.assert_not_called()


def test_run_tries_portal_when_aafaf_empty(tmp_path):
    """run() falls back to _fetch_pr_data_portal when AAFAF reports return nothing."""
    with patch("scripts.download_aafaf._session") as mock_session_fn, \
         patch("scripts.download_aafaf._fetch_aafaf_reports", return_value=[]) as mock_aafaf, \
         patch("scripts.download_aafaf._fetch_pr_data_portal", return_value=[]) as mock_portal:
        mock_session_fn.return_value = MagicMock()
        run(root=tmp_path, force=True)

    mock_aafaf.assert_called_once()
    mock_portal.assert_called_once()
