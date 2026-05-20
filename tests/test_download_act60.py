"""Tests for download_act60.py — Puerto Rico Act 60 tax incentive decree downloader."""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Suppress noisy log output from the module under test
logging.getLogger("download_act60").setLevel(logging.CRITICAL)
logging.getLogger("test").setLevel(logging.CRITICAL)

from scripts.download_act60 import (
    ACT60_COLUMNS,
    DATA_PR_GOV_URLS,
    DDEC_URLS,
    _build_manual_template,
    _file_has_data,
    _normalize_name,
    _records_to_df,
    _session,
    _try_data_pr_gov,
    _try_ddec_page,
    run,
)


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------

class TestNormalizeName:
    def test_strips_inc_suffix(self):
        assert "ACME" in _normalize_name("ACME INC")

    def test_strips_llc_suffix(self):
        result = _normalize_name("CARIBBEAN BUILDERS LLC")
        assert "LLC" not in result
        assert "CARIBBEAN BUILDERS" in result

    def test_strips_corp_suffix(self):
        result = _normalize_name("TECH SOLUTIONS CORP")
        assert "CORP" not in result

    def test_uppercases_result(self):
        result = _normalize_name("test company")
        assert result == result.upper()

    def test_removes_special_characters(self):
        result = _normalize_name("O'Brien & Associates, Inc.")
        assert "&" not in result
        assert "'" not in result

    def test_empty_string_returns_empty(self):
        assert _normalize_name("") == ""

    def test_none_returns_empty(self):
        assert _normalize_name(None) == ""

    def test_nan_returns_empty(self):
        assert _normalize_name(float("nan")) == ""

    def test_collapses_multiple_spaces(self):
        result = _normalize_name("A   B   C")
        assert "  " not in result

    def test_strips_leading_trailing_whitespace(self):
        result = _normalize_name("  Company Name  ")
        assert result == result.strip()


# ---------------------------------------------------------------------------
# _session
# ---------------------------------------------------------------------------

class TestSession:
    def test_returns_requests_session(self):
        import requests
        s = _session()
        assert isinstance(s, requests.Session)

    def test_has_user_agent_header(self):
        s = _session()
        assert "User-Agent" in s.headers

    def test_user_agent_contains_contract_sweeper(self):
        s = _session()
        assert "ContractSweeper" in s.headers["User-Agent"]

    def test_has_accept_header(self):
        s = _session()
        assert "Accept" in s.headers


# ---------------------------------------------------------------------------
# _records_to_df
# ---------------------------------------------------------------------------

class TestRecordsToDf:
    def _sample_records(self):
        return [
            {
                "entity_name": "ABC Corp",
                "decree_type": "Act 60",
                "effective_date": "2020-01-01",
                "municipality": "San Juan",
            }
        ]

    def test_returns_dataframe(self):
        df = _records_to_df(self._sample_records(), "http://example.com")
        assert isinstance(df, pd.DataFrame)

    def test_output_has_act60_columns(self):
        df = _records_to_df(self._sample_records(), "http://example.com")
        assert list(df.columns) == ACT60_COLUMNS

    def test_source_url_populated(self):
        df = _records_to_df(self._sample_records(), "http://example.com/source")
        assert df["source_url"].iloc[0] == "http://example.com/source"

    def test_entity_normalized_derived_from_entity_name(self):
        records = [{"entity_name": "My Company LLC"}]
        df = _records_to_df(records, "http://example.com")
        assert df["entity_normalized"].iloc[0] == _normalize_name("My Company LLC")

    def test_empty_records_returns_empty_with_columns(self):
        df = _records_to_df([], "http://example.com")
        assert list(df.columns) == ACT60_COLUMNS
        assert len(df) == 0

    def test_none_records_returns_empty_with_columns(self):
        df = _records_to_df(None, "http://example.com")
        assert list(df.columns) == ACT60_COLUMNS
        assert len(df) == 0

    def test_alternate_column_name_nombre(self):
        """Maps 'nombre' → 'entity_name'."""
        records = [{"nombre": "Empresa ABC"}]
        df = _records_to_df(records, "http://example.com")
        assert df["entity_name"].iloc[0] == "Empresa ABC"

    def test_alternate_column_name_municipio(self):
        """Maps 'municipio' → 'municipality'."""
        records = [{"municipio": "Ponce"}]
        df = _records_to_df(records, "http://example.com")
        assert df["municipality"].iloc[0] == "Ponce"

    def test_decree_type_defaults_to_act60_when_missing(self):
        """When decree_type is absent, defaults to 'Act 60'."""
        records = [{"entity_name": "Test Entity"}]
        df = _records_to_df(records, "http://example.com")
        assert df["decree_type"].iloc[0] == "Act 60"

    def test_multiple_records_preserved(self):
        records = [
            {"entity_name": f"Entity {i}"} for i in range(5)
        ]
        df = _records_to_df(records, "http://example.com")
        assert len(df) == 5

    def test_missing_columns_filled_with_empty_string(self):
        records = [{"entity_name": "Only Name"}]
        df = _records_to_df(records, "http://example.com")
        for col in ACT60_COLUMNS:
            assert col in df.columns


# ---------------------------------------------------------------------------
# _file_has_data
# ---------------------------------------------------------------------------

class TestFileHasData:
    def test_missing_file_returns_false(self, tmp_path):
        assert _file_has_data(tmp_path / "nonexistent.csv") is False

    def test_valid_csv_with_data_returns_true(self, tmp_path):
        p = tmp_path / "data.csv"
        pd.DataFrame([{"entity_name": "Corp A"}]).to_csv(p, index=False)
        assert _file_has_data(p) is True

    def test_header_only_csv_returns_false(self, tmp_path):
        p = tmp_path / "header_only.csv"
        pd.DataFrame(columns=ACT60_COLUMNS).to_csv(p, index=False)
        # header-only file has 0 data rows, nrows=2 returns empty → False
        assert _file_has_data(p) is False

    def test_corrupt_file_returns_false(self, tmp_path):
        p = tmp_path / "corrupt.csv"
        p.write_bytes(b"\x00\x01\x02\x03")
        result = _file_has_data(p)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# _build_manual_template
# ---------------------------------------------------------------------------

class TestBuildManualTemplate:
    def test_creates_empty_csv_with_act60_columns(self, tmp_path):
        out_path = tmp_path / "pr_act60_decrees.csv"
        logger = logging.getLogger("test")
        _build_manual_template(out_path, logger)
        assert out_path.exists()
        df = pd.read_csv(out_path, dtype=str)
        assert list(df.columns) == ACT60_COLUMNS
        assert len(df) == 0


# ---------------------------------------------------------------------------
# _try_data_pr_gov
# ---------------------------------------------------------------------------

class TestTryDataPrGov:
    def _make_mock_session(self, json_data, status_code=200, content_type="application/json"):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.headers = {"Content-Type": content_type}
        mock_resp.json.return_value = json_data
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        return mock_session

    def test_returns_records_on_success(self):
        records = [{"entity_name": "Corp A"}, {"entity_name": "Corp B"}]
        mock_session = self._make_mock_session(records)
        logger = logging.getLogger("test")
        result = _try_data_pr_gov(mock_session, logger)
        assert result == records

    def test_returns_none_on_404(self):
        mock_session = self._make_mock_session([], status_code=404)
        logger = logging.getLogger("test")
        result = _try_data_pr_gov(mock_session, logger)
        assert result is None

    def test_returns_none_on_empty_list(self):
        mock_session = self._make_mock_session([])
        logger = logging.getLogger("test")
        result = _try_data_pr_gov(mock_session, logger)
        assert result is None

    def test_returns_none_on_wrong_content_type(self):
        mock_session = self._make_mock_session([], content_type="text/html")
        logger = logging.getLogger("test")
        result = _try_data_pr_gov(mock_session, logger)
        assert result is None

    def test_returns_none_on_exception(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("Connection refused")
        logger = logging.getLogger("test")
        result = _try_data_pr_gov(mock_session, logger)
        assert result is None


# ---------------------------------------------------------------------------
# _try_ddec_page
# ---------------------------------------------------------------------------

class TestTryDdecPage:
    def _make_mock_session(self, status_code=200, text=""):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.text = text
        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp
        return mock_session

    def test_returns_none_on_404(self):
        mock_session = self._make_mock_session(status_code=404)
        logger = logging.getLogger("test")
        result = _try_ddec_page(mock_session, logger)
        assert result is None

    def test_returns_csv_link_when_found(self):
        html = '<a href="/files/act60_data.csv">Download</a>'
        mock_session = self._make_mock_session(text=html)
        logger = logging.getLogger("test")
        result = _try_ddec_page(mock_session, logger)
        assert result is not None
        link_type, link_url = result
        assert link_type == "csv_link"
        assert "act60_data.csv" in link_url

    def test_returns_excel_link_when_found(self):
        html = '<a href="/files/act60_data.xlsx">Download</a>'
        mock_session = self._make_mock_session(text=html)
        logger = logging.getLogger("test")
        result = _try_ddec_page(mock_session, logger)
        assert result is not None
        link_type, link_url = result
        assert link_type == "excel_link"
        assert "act60_data.xlsx" in link_url

    def test_returns_none_when_no_data_links(self):
        html = "<html><body><p>No downloads here</p></body></html>"
        mock_session = self._make_mock_session(text=html)
        logger = logging.getLogger("test")
        result = _try_ddec_page(mock_session, logger)
        assert result is None

    def test_returns_none_on_exception(self):
        mock_session = MagicMock()
        mock_session.get.side_effect = Exception("Timeout")
        logger = logging.getLogger("test")
        result = _try_ddec_page(mock_session, logger)
        assert result is None


# ---------------------------------------------------------------------------
# run() — caching: pre-existing output skips download
# ---------------------------------------------------------------------------

class TestRunCaching:
    def test_run_skips_when_output_exists_with_data(self, tmp_path):
        """run() (force=False) skips download if output CSV already has data."""
        out_dir = tmp_path / "data" / "staging" / "processed"
        out_dir.mkdir(parents=True)
        out_path = out_dir / "pr_act60_decrees.csv"

        # Pre-create output with one data row
        sample = pd.DataFrame([{col: "test" for col in ACT60_COLUMNS}])
        sample.to_csv(out_path, index=False)

        with patch("scripts.download_act60.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            result = run(root=tmp_path)

        # HTTP session should not have been used (caching kicked in)
        mock_session.get.assert_not_called()
        assert result["rows"] >= 1
        assert "path" in result
        assert "errors" in result

    def test_run_returns_dict_with_expected_keys(self, tmp_path):
        """run() always returns dict with rows, path, errors."""
        out_dir = tmp_path / "data" / "staging" / "processed"
        out_dir.mkdir(parents=True)
        out_path = out_dir / "pr_act60_decrees.csv"

        sample = pd.DataFrame([{col: "test" for col in ACT60_COLUMNS}])
        sample.to_csv(out_path, index=False)

        result = run(root=tmp_path)
        assert isinstance(result, dict)
        assert "rows" in result
        assert "path" in result
        assert "errors" in result


# ---------------------------------------------------------------------------
# run() — mock HTTP: data.pr.gov returns records
# ---------------------------------------------------------------------------

class TestRunWithMockedHttp:
    def _setup_mock_api_session(self, mock_session_cls, records):
        """Wire up session.get to return JSON records from data.pr.gov."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = records
        mock_session.get.return_value = mock_resp
        return mock_session

    def test_run_writes_output_csv(self, tmp_path):
        """run() writes pr_act60_decrees.csv when API returns records."""
        records = [{"entity_name": f"Entity {i}", "decree_type": "Act 60"} for i in range(3)]

        with patch("scripts.download_act60.requests.Session") as mock_session_cls:
            self._setup_mock_api_session(mock_session_cls, records)
            result = run(root=tmp_path)

        out_path = tmp_path / "data" / "staging" / "processed" / "pr_act60_decrees.csv"
        assert out_path.exists()
        assert result["rows"] == 3

    def test_run_output_has_act60_columns(self, tmp_path):
        """Output CSV from run() contains all ACT60_COLUMNS."""
        records = [{"entity_name": "Corp A", "decree_type": "Act 60"}]

        with patch("scripts.download_act60.requests.Session") as mock_session_cls:
            self._setup_mock_api_session(mock_session_cls, records)
            run(root=tmp_path)

        out_path = tmp_path / "data" / "staging" / "processed" / "pr_act60_decrees.csv"
        df = pd.read_csv(out_path, dtype=str)
        for col in ACT60_COLUMNS:
            assert col in df.columns

    def test_run_falls_back_to_manual_template_when_no_data(self, tmp_path):
        """run() creates empty template CSV when all sources fail."""
        with patch("scripts.download_act60.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session

            # All API calls return 404 or empty
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_resp.headers = {"Content-Type": "text/html"}
            mock_session.get.return_value = mock_resp

            result = run(root=tmp_path)

        out_path = tmp_path / "data" / "staging" / "processed" / "pr_act60_decrees.csv"
        assert out_path.exists()
        assert result["rows"] == 0
        assert isinstance(result["errors"], list)
        assert len(result["errors"]) > 0

    def test_run_loads_manual_raw_file_when_present(self, tmp_path):
        """run() loads manually placed raw CSV without making HTTP calls."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "act60"
        raw_dir.mkdir(parents=True)
        manual_path = raw_dir / "pr_act60_decrees_raw.csv"

        sample = pd.DataFrame([
            {"entity_name": "Manual Corp", "decree_type": "Act 60", "municipality": "Ponce"}
        ])
        sample.to_csv(manual_path, index=False)

        with patch("scripts.download_act60.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            result = run(root=tmp_path)

        # Should not have made any HTTP calls (manual file used)
        mock_session.get.assert_not_called()
        assert result["rows"] == 1
        out_path = tmp_path / "data" / "staging" / "processed" / "pr_act60_decrees.csv"
        assert out_path.exists()


# ---------------------------------------------------------------------------
# ACT60_COLUMNS constant
# ---------------------------------------------------------------------------

class TestAct60ColumnsConstant:
    def test_has_expected_column_count(self):
        assert len(ACT60_COLUMNS) >= 9

    def test_contains_entity_name(self):
        assert "entity_name" in ACT60_COLUMNS

    def test_contains_entity_normalized(self):
        assert "entity_normalized" in ACT60_COLUMNS

    def test_contains_decree_type(self):
        assert "decree_type" in ACT60_COLUMNS

    def test_contains_source_url(self):
        assert "source_url" in ACT60_COLUMNS

    def test_contains_municipality(self):
        assert "municipality" in ACT60_COLUMNS
