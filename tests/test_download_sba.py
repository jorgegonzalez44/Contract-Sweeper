"""Tests for scripts/download_sba.py — SBA Disaster Loan downloader."""

import io
import json
import logging
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Suppress noisy log output from the module under test
logging.getLogger("test").setLevel(logging.CRITICAL)
logging.getLogger("download_sba").setLevel(logging.CRITICAL)

from scripts.download_sba import (
    _derive_fiscal_year,
    _file_has_data,
    _pick_resource,
    _records_to_df,
    _csv_to_master,
    MASTER_COLUMNS,
    run,
)


# ---------------------------------------------------------------------------
# Pure helper: _derive_fiscal_year
# ---------------------------------------------------------------------------

class TestDeriveFiscalYear:
    def test_jan_through_sep_returns_same_year(self):
        assert _derive_fiscal_year("2022-01-15") == "2022"

    def test_oct_through_dec_returns_next_year(self):
        assert _derive_fiscal_year("2022-10-01") == "2023"

    def test_december_returns_next_year(self):
        assert _derive_fiscal_year("2021-12-31") == "2022"

    def test_september_boundary_returns_same_year(self):
        assert _derive_fiscal_year("2021-09-30") == "2021"

    def test_empty_string_returns_empty(self):
        assert _derive_fiscal_year("") == ""

    def test_none_returns_empty(self):
        assert _derive_fiscal_year(None) == ""

    def test_invalid_date_string_returns_empty(self):
        assert _derive_fiscal_year("not-a-date") == ""

    def test_nan_returns_empty(self):
        assert _derive_fiscal_year(float("nan")) == ""


# ---------------------------------------------------------------------------
# Pure helper: _pick_resource
# ---------------------------------------------------------------------------

class TestPickResource:
    def test_picks_csv_resource_over_others(self):
        resources = [
            {"id": "r1", "format": "JSON", "name": "json-data", "url": "http://example.com/a"},
            {"id": "r2", "format": "CSV", "name": "csv-data", "url": "http://example.com/b"},
        ]
        logger = MagicMock()
        rid, rurl = _pick_resource(resources, logger)
        assert rid == "r2"
        assert rurl == "http://example.com/b"

    def test_prefers_business_csv_resource(self):
        resources = [
            {"id": "r1", "format": "CSV", "name": "home loans", "url": "http://example.com/home"},
            {"id": "r2", "format": "CSV", "name": "business loans", "url": "http://example.com/biz"},
        ]
        logger = MagicMock()
        rid, rurl = _pick_resource(resources, logger)
        assert rid == "r2"
        assert "biz" in rurl

    def test_returns_none_none_for_empty_list(self):
        logger = MagicMock()
        rid, rurl = _pick_resource([], logger)
        assert rid is None
        assert rurl is None

    def test_falls_back_to_first_resource_when_no_csv(self):
        resources = [
            {"id": "r1", "format": "EXCEL", "name": "data", "url": "http://example.com/e"},
        ]
        logger = MagicMock()
        rid, rurl = _pick_resource(resources, logger)
        assert rid == "r1"


# ---------------------------------------------------------------------------
# Pure helper: _records_to_df
# ---------------------------------------------------------------------------

class TestRecordsToDf:
    def _make_records(self):
        return [
            {
                "ApplicationNumber": "0001",
                "BorrowerName": "ACME Corp PR",
                "LoanAmount": "50000",
                "DateApproved": "2022-03-01",
                "State": "PR",
                "County": "San Juan",
                "DisasterName": "Hurricane Maria",
            },
            {
                "ApplicationNumber": "0002",
                "BorrowerName": "Island Builders LLC",
                "LoanAmount": "120000",
                "DateApproved": "2022-11-15",
                "State": "PR",
                "County": "Bayamón",
                "DisasterName": "Hurricane Fiona",
            },
        ]

    def test_returns_dataframe_with_master_columns(self):
        df = _records_to_df(self._make_records(), "test.csv")
        assert isinstance(df, pd.DataFrame)
        for col in MASTER_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"

    def test_pr_rows_are_kept(self):
        df = _records_to_df(self._make_records(), "test.csv")
        assert len(df) == 2

    def test_non_pr_rows_are_filtered_out(self):
        records = self._make_records()
        records.append({
            "ApplicationNumber": "9999",
            "BorrowerName": "Florida Co",
            "LoanAmount": "10000",
            "DateApproved": "2022-01-01",
            "State": "FL",
            "County": "Miami-Dade",
            "DisasterName": "Hurricane Ian",
        })
        df = _records_to_df(records, "test.csv")
        assert len(df) == 2  # FL record excluded

    def test_award_id_prefixed_with_SBA(self):
        df = _records_to_df(self._make_records(), "test.csv")
        assert all(df["award_id"].str.startswith("SBA-"))

    def test_fiscal_year_derived_correctly(self):
        df = _records_to_df(self._make_records(), "test.csv")
        # March 2022 → FY2022; November 2022 → FY2023
        assert df.iloc[0]["fiscal_year"] == "2022"
        assert df.iloc[1]["fiscal_year"] == "2023"

    def test_source_dataset_set_to_sba_loans(self):
        df = _records_to_df(self._make_records(), "test.csv")
        assert all(df["source_dataset"] == "sba_loans")

    def test_award_category_set_to_loan(self):
        df = _records_to_df(self._make_records(), "test.csv")
        assert all(df["award_category"] == "loan")

    def test_source_file_matches_argument(self):
        df = _records_to_df(self._make_records(), "my_file.csv")
        assert all(df["source_file"] == "my_file.csv")

    def test_empty_records_returns_empty_df_with_columns(self):
        df = _records_to_df([], "test.csv")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        for col in MASTER_COLUMNS:
            assert col in df.columns

    def test_ckan_internal_id_column_is_dropped(self):
        records = self._make_records()
        for r in records:
            r["_id"] = 42
        df = _records_to_df(records, "test.csv")
        assert "_id" not in df.columns

    def test_awarding_agency_is_sba(self):
        df = _records_to_df(self._make_records(), "test.csv")
        assert all(df["awarding_agency"] == "Small Business Administration")


# ---------------------------------------------------------------------------
# Pure helper: _csv_to_master (thin wrapper)
# ---------------------------------------------------------------------------

class TestCsvToMaster:
    def test_csv_to_master_returns_master_columns(self):
        raw = pd.DataFrame([
            {
                "ApplicationNumber": "A001",
                "BorrowerName": "PR Company",
                "LoanAmount": "75000",
                "DateApproved": "2023-06-01",
                "State": "PR",
                "County": "Ponce",
                "DisasterName": "Earthquake",
            }
        ])
        result = _csv_to_master(raw, "raw.csv")
        for col in MASTER_COLUMNS:
            assert col in result.columns

    def test_csv_to_master_filters_non_pr(self):
        raw = pd.DataFrame([
            {"ApplicationNumber": "A001", "BorrowerName": "PR Co", "LoanAmount": "1000",
             "DateApproved": "2023-01-01", "State": "PR", "County": "SJ", "DisasterName": "D1"},
            {"ApplicationNumber": "A002", "BorrowerName": "TX Co", "LoanAmount": "2000",
             "DateApproved": "2023-01-01", "State": "TX", "County": "Harris", "DisasterName": "D2"},
        ])
        result = _csv_to_master(raw, "raw.csv")
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _file_has_data
# ---------------------------------------------------------------------------

class TestFileHasData:
    def test_returns_false_for_missing_file(self, tmp_path):
        assert _file_has_data(tmp_path / "nonexistent.csv") is False

    def test_returns_false_for_header_only_csv(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("col1,col2\n")
        assert _file_has_data(p) is False

    def test_returns_true_for_csv_with_data(self, tmp_path):
        p = tmp_path / "data.csv"
        p.write_text("col1,col2\nval1,val2\n")
        assert _file_has_data(p) is True


# ---------------------------------------------------------------------------
# Integration: run() caching behaviour
# ---------------------------------------------------------------------------

class TestRunCaching:
    def test_run_skips_download_when_raw_file_exists(self, tmp_path):
        """run(root=tmp_path) should NOT hit the network when raw file is present."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "sba"
        raw_dir.mkdir(parents=True)
        raw_file = raw_dir / "sba_disaster_loans_pr.csv"
        # Write a minimal CSV with PR data
        raw_file.write_text(
            "ApplicationNumber,BorrowerName,LoanAmount,DateApproved,State,County,DisasterName\n"
            "1001,Test Company PR,50000,2022-05-01,PR,San Juan,Hurricane Test\n"
        )

        with patch("scripts.download_sba.requests.Session") as mock_sess_cls:
            result = run(root=tmp_path)
            # Session should not be instantiated (no network calls made)
            mock_sess_cls.assert_not_called()

        assert result["status"] == "OK"
        assert result["rows"] >= 1

    def test_run_returns_summary_dict(self, tmp_path):
        """run() always returns a dict with expected keys."""
        # Write a raw file so we skip the network path
        raw_dir = tmp_path / "data" / "staging" / "raw" / "sba"
        raw_dir.mkdir(parents=True)
        (raw_dir / "sba_disaster_loans_pr.csv").write_text(
            "ApplicationNumber,BorrowerName,LoanAmount,DateApproved,State,County,DisasterName\n"
            "2001,Another PR Co,80000,2023-01-10,PR,Ponce,Earthquake\n"
        )
        result = run(root=tmp_path)
        for key in ("rows", "raw_rows", "master_path", "raw_path", "status"):
            assert key in result, f"Missing key: {key}"

    def test_run_writes_master_csv(self, tmp_path):
        """run() writes master CSV to expected location."""
        raw_dir = tmp_path / "data" / "staging" / "raw" / "sba"
        raw_dir.mkdir(parents=True)
        (raw_dir / "sba_disaster_loans_pr.csv").write_text(
            "ApplicationNumber,BorrowerName,LoanAmount,DateApproved,State,County,DisasterName\n"
            "3001,PR Construction Inc,200000,2022-07-04,PR,Bayamon,Hurricane\n"
        )
        run(root=tmp_path)
        master = tmp_path / "data" / "staging" / "processed" / "pr_sba_loans_master.csv"
        assert master.exists()
        df = pd.read_csv(master, dtype=str)
        for col in MASTER_COLUMNS:
            assert col in df.columns


# ---------------------------------------------------------------------------
# Integration: run() with mocked HTTP (force path)
# ---------------------------------------------------------------------------

class TestRunWithMockedHttp:
    def _make_ckan_package_response(self, resource_id="test-rid-001"):
        return {
            "success": True,
            "result": {
                "resources": [
                    {
                        "id": resource_id,
                        "format": "CSV",
                        "name": "business loans",
                        "url": "http://fake.sba.gov/data.csv",
                    }
                ]
            },
        }

    def _make_csv_response(self):
        content = (
            "ApplicationNumber,BorrowerName,LoanAmount,DateApproved,State,County,DisasterName\n"
            "5001,Mock PR Corp,100000,2022-04-01,PR,San Juan,Mock Disaster\n"
            "5002,Another Mock Corp,200000,2022-11-01,PR,Caguas,Mock Disaster 2\n"
        )
        resp = MagicMock()
        resp.status_code = 200
        resp.iter_content.return_value = [content.encode("utf-8")]
        return resp

    @patch("scripts.download_sba._session")
    def test_run_downloads_when_no_raw_file(self, mock_session_fn, tmp_path):
        """run() triggers download when raw file is absent (force path via _run)."""
        from scripts.download_sba import _run

        mock_session = MagicMock()
        mock_session_fn.return_value = mock_session

        pkg_resp = MagicMock()
        pkg_resp.status_code = 200
        pkg_resp.json.return_value = self._make_ckan_package_response()
        pkg_resp.raise_for_status.return_value = None

        csv_resp = self._make_csv_response()

        mock_session.get.side_effect = [pkg_resp, csv_resp]

        result = _run(root=tmp_path, force=True)

        assert isinstance(result, dict)
        assert "status" in result

    @patch("scripts.download_sba._session")
    def test_run_force_ignores_existing_file(self, mock_session_fn, tmp_path):
        """_run(force=True) ignores existing raw file and attempts download."""
        from scripts.download_sba import _run

        # Pre-create a stale raw file
        raw_dir = tmp_path / "data" / "staging" / "raw" / "sba"
        raw_dir.mkdir(parents=True)
        stale = raw_dir / "sba_disaster_loans_pr.csv"
        stale.write_text(
            "ApplicationNumber,BorrowerName,LoanAmount,DateApproved,State,County,DisasterName\n"
            "OLD,Old Corp,1,2020-01-01,PR,SJ,Old\n"
        )

        mock_session = MagicMock()
        mock_session_fn.return_value = mock_session

        # Make package lookup fail so we exercise fallback path gracefully
        pkg_resp = MagicMock()
        pkg_resp.status_code = 404
        pkg_resp.raise_for_status.side_effect = Exception("404")
        mock_session.get.return_value = pkg_resp

        # Should not raise even when network fails
        result = _run(root=tmp_path, force=True)
        assert isinstance(result, dict)
        assert "status" in result

    @patch("scripts.download_sba._find_resource")
    @patch("scripts.download_sba._session")
    def test_run_handles_no_resource_found(self, mock_session_fn, mock_find_resource, tmp_path):
        """run() writes empty master when no resource is discoverable."""
        from scripts.download_sba import _run

        mock_session_fn.return_value = MagicMock()
        mock_find_resource.return_value = (None, None)

        result = _run(root=tmp_path, force=True)

        assert result["rows"] == 0
        assert result["status"] == "EMPTY"
        master = Path(result["master_path"])
        assert master.exists()
        df = pd.read_csv(master, dtype=str)
        assert list(df.columns) == MASTER_COLUMNS
