"""
Tests for scripts/download_fema.py

Covers:
  - Pure helper functions: _derive_fiscal_year, URL/pagination logic
  - _normalize_pa: row normalization for PA records
  - _normalize_hmgp: row normalization for HMGP/HMA records
  - download_pa / download_hmgp: caching (skip-if-exists) and successful write
  - run(): integration with mocked HTTP
"""

import logging
import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch, MagicMock

# Suppress noisy log output from the module under test
logging.getLogger("test").setLevel(logging.CRITICAL)
logging.getLogger("download_fema").setLevel(logging.CRITICAL)

import scripts.download_fema as df_mod
from scripts.download_fema import (
    _derive_fiscal_year,
    _normalize_pa,
    _normalize_hmgp,
    MASTER_COLUMNS,
)


# ---------------------------------------------------------------------------
# _derive_fiscal_year — pure helper, no I/O
# ---------------------------------------------------------------------------

class TestDeriveFiscalYear:
    def test_month_before_october_same_year(self):
        """Dates Jan–Sep stay in the same fiscal year."""
        assert _derive_fiscal_year("2020-06-15") == 2020

    def test_october_advances_fiscal_year(self):
        """October 1 marks the start of the *next* FY."""
        assert _derive_fiscal_year("2020-10-01") == 2021

    def test_december_advances_fiscal_year(self):
        """December is still in the next FY."""
        assert _derive_fiscal_year("2019-12-31") == 2020

    def test_none_returns_none(self):
        assert _derive_fiscal_year(None) is None

    def test_empty_string_returns_none(self):
        assert _derive_fiscal_year("") is None

    def test_unparseable_string_returns_none(self):
        assert _derive_fiscal_year("not-a-date") is None

    def test_timestamp_with_time_component(self):
        """ISO 8601 timestamps with time part should parse correctly."""
        # 2018-10-15 → FY2019
        assert _derive_fiscal_year("2018-10-15T00:00:00.000Z") == 2019


# ---------------------------------------------------------------------------
# _normalize_pa — row mapping, no I/O
# ---------------------------------------------------------------------------

class TestNormalizePa:
    PA_RECORD = {
        "disasterNumber": "4339",
        "applicantName": "Municipio de San Juan",
        "projectAmount": 500_000.0,
        "federalShareObligated": 400_000.0,
        "projectWorksheetDate": "2018-03-10T00:00:00.000Z",
        "applicationTitle": "Debris Removal",
        "damageCategory": "Roads",
        "state": "Puerto Rico",
        "county": "San Juan",
    }

    def test_returns_dataframe_with_master_columns(self):
        df = _normalize_pa([self.PA_RECORD], source_file="test.csv")
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == MASTER_COLUMNS

    def test_award_id_format(self):
        df = _normalize_pa([self.PA_RECORD], source_file="test.csv")
        assert df.iloc[0]["award_id"] == "FEMA-PA-4339"

    def test_uses_project_amount_when_nonzero(self):
        """projectAmount takes precedence over federalShareObligated."""
        df = _normalize_pa([self.PA_RECORD], source_file="test.csv")
        assert df.iloc[0]["obligated_amount"] == 500_000.0

    def test_falls_back_to_federal_share_when_project_amount_zero(self):
        rec = dict(self.PA_RECORD, projectAmount=0, federalShareObligated=300_000.0)
        df = _normalize_pa([rec], source_file="test.csv")
        assert df.iloc[0]["obligated_amount"] == 300_000.0

    def test_pop_state_normalized_to_pr(self):
        df = _normalize_pa([self.PA_RECORD], source_file="test.csv")
        assert df.iloc[0]["pop_state"] == "PR"

    def test_award_date_strips_time(self):
        df = _normalize_pa([self.PA_RECORD], source_file="test.csv")
        assert df.iloc[0]["award_date"] == "2018-03-10"

    def test_fiscal_year_derived(self):
        # 2018-03-10 → FY2018
        df = _normalize_pa([self.PA_RECORD], source_file="test.csv")
        assert df.iloc[0]["fiscal_year"] == 2018

    def test_awarding_agency_constant(self):
        df = _normalize_pa([self.PA_RECORD], source_file="test.csv")
        assert df.iloc[0]["awarding_agency"] == "Federal Emergency Management Agency"

    def test_source_dataset_constant(self):
        df = _normalize_pa([self.PA_RECORD], source_file="test.csv")
        assert df.iloc[0]["source_dataset"] == "fema_pa"

    def test_award_category_constant(self):
        df = _normalize_pa([self.PA_RECORD], source_file="test.csv")
        assert df.iloc[0]["award_category"] == "disaster_assistance"

    def test_empty_records_returns_empty_dataframe(self):
        df = _normalize_pa([], source_file="test.csv")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert list(df.columns) == MASTER_COLUMNS

    def test_unknown_disaster_number(self):
        rec = dict(self.PA_RECORD, disasterNumber="")
        df = _normalize_pa([rec], source_file="test.csv")
        assert df.iloc[0]["award_id"] == "FEMA-PA-UNKNOWN"

    def test_multiple_records(self):
        records = [self.PA_RECORD, dict(self.PA_RECORD, disasterNumber="9999")]
        df = _normalize_pa(records, source_file="test.csv")
        assert len(df) == 2


# ---------------------------------------------------------------------------
# _normalize_hmgp — row mapping for HMGP and HMA datasets
# ---------------------------------------------------------------------------

class TestNormalizeHmgp:
    HMGP_RECORD = {
        "disasterNumber": "4339",
        "applicantName": "Puerto Rico DNER",
        "projectTitle": "Slope Stabilization Project",
        "projectAmount": 1_200_000.0,
        "stateName": "Puerto Rico",
        "county": "Utuado",
        "obligationDate": "2019-05-20T00:00:00.000Z",
        "projectNumber": "PR-001",
    }

    HMA_RECORD = {
        "disasterNumber": "4339",
        "subapplicantName": "Municipality of Caguas",
        "projectTitle": "Flood Control",
        "projectAmount": 750_000.0,
        "grantAmount": 600_000.0,
        "stateName": "Puerto Rico",
        "county": "Caguas",
        "applicationDate": "2019-08-01T00:00:00.000Z",
        "subapplicationId": "HMA-002",
    }

    def test_hmgp_returns_master_columns(self):
        df = _normalize_hmgp([self.HMGP_RECORD], "hmgp_summaries", "raw.csv")
        assert list(df.columns) == MASTER_COLUMNS

    def test_hmgp_award_id_format(self):
        df = _normalize_hmgp([self.HMGP_RECORD], "hmgp_summaries", "raw.csv")
        assert df.iloc[0]["award_id"] == "FEMA-HMGP-4339-PR-001"

    def test_hmgp_pop_state_pr(self):
        df = _normalize_hmgp([self.HMGP_RECORD], "hmgp_summaries", "raw.csv")
        assert df.iloc[0]["pop_state"] == "PR"

    def test_hmgp_source_dataset_constant(self):
        df = _normalize_hmgp([self.HMGP_RECORD], "hmgp_summaries", "raw.csv")
        assert df.iloc[0]["source_dataset"] == "fema_hmgp"

    def test_hmgp_award_category_grant(self):
        df = _normalize_hmgp([self.HMGP_RECORD], "hmgp_summaries", "raw.csv")
        assert df.iloc[0]["award_category"] == "grant"

    def test_hma_uses_subapplicant_name(self):
        df = _normalize_hmgp([self.HMA_RECORD], "hma_subapplications", "raw.csv")
        assert df.iloc[0]["recipient_name"] == "Municipality of Caguas"

    def test_hma_award_id_format(self):
        df = _normalize_hmgp([self.HMA_RECORD], "hma_subapplications", "raw.csv")
        assert df.iloc[0]["award_id"] == "FEMA-HMGP-HMA-4339-HMA-002"

    def test_hmgp_fiscal_year_derived(self):
        # 2019-05-20 → FY2019
        df = _normalize_hmgp([self.HMGP_RECORD], "hmgp_summaries", "raw.csv")
        assert df.iloc[0]["fiscal_year"] == 2019

    def test_empty_records_returns_empty_dataframe(self):
        df = _normalize_hmgp([], "hmgp_summaries", "raw.csv")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0


# ---------------------------------------------------------------------------
# download_pa — caching and write path (mocked file system paths)
# ---------------------------------------------------------------------------

class TestDownloadPa:
    """Tests for download_pa() with patched paths and HTTP."""

    def _make_logger(self):
        logger = logging.getLogger("test_download_pa")
        logger.setLevel(logging.CRITICAL)
        return logger

    def test_skip_when_master_exists_force_false(self, tmp_path):
        """download_pa returns cached row count when master exists and force=False."""
        fake_master = tmp_path / "pr_fema_pa_master.csv"
        fake_df = pd.DataFrame([{"col": "val"}])
        fake_df.to_csv(fake_master, index=False)

        with patch.object(df_mod, "PA_MASTER_PATH", fake_master):
            rows, path_str = df_mod.download_pa(force=False, logger=self._make_logger())

        assert rows == 1
        assert path_str == str(fake_master)

    def test_force_true_re_downloads(self, tmp_path):
        """download_pa re-downloads even when master already exists if force=True."""
        fake_master = tmp_path / "pr_fema_pa_master.csv"
        fake_raw_dir = tmp_path / "fema_pa"

        # Stub _fetch_pa_records to return minimal data
        pa_record = {
            "disasterNumber": "4339",
            "applicantName": "Test Entity",
            "projectAmount": 100.0,
            "federalShareObligated": 80.0,
            "projectWorksheetDate": "2021-01-01T00:00:00.000Z",
            "applicationTitle": "Test",
            "state": "Puerto Rico",
            "county": "San Juan",
        }
        with patch.object(df_mod, "PA_MASTER_PATH", fake_master), \
             patch.object(df_mod, "PA_RAW_DIR", fake_raw_dir), \
             patch.object(df_mod, "PA_RAW_PATH", fake_raw_dir / "fema_pa_raw.csv"), \
             patch.object(df_mod, "PROCESSED_DIR", tmp_path), \
             patch("scripts.download_fema._fetch_pa_records", return_value=[pa_record]):
            rows, path_str = df_mod.download_pa(force=True, logger=self._make_logger())

        assert rows == 1
        assert fake_master.exists()


# ---------------------------------------------------------------------------
# download_hmgp — caching and write path
# ---------------------------------------------------------------------------

class TestDownloadHmgp:
    def _make_logger(self):
        logger = logging.getLogger("test_download_hmgp")
        logger.setLevel(logging.CRITICAL)
        return logger

    def test_skip_when_master_exists_force_false(self, tmp_path):
        """download_hmgp returns cached row count when master exists and force=False."""
        fake_master = tmp_path / "pr_fema_hmgp_master.csv"
        fake_df = pd.DataFrame([{"col": "val"}, {"col": "val2"}])
        fake_df.to_csv(fake_master, index=False)

        with patch.object(df_mod, "HMGP_MASTER_PATH", fake_master):
            rows, path_str = df_mod.download_hmgp(force=False, logger=self._make_logger())

        assert rows == 2
        assert path_str == str(fake_master)

    def test_force_true_re_downloads(self, tmp_path):
        """download_hmgp re-downloads when force=True."""
        fake_master = tmp_path / "pr_fema_hmgp_master.csv"
        fake_raw_dir = tmp_path / "fema_hmgp"
        hmgp_record = {
            "disasterNumber": "4339",
            "applicantName": "PR DNER",
            "projectAmount": 200_000.0,
            "stateName": "Puerto Rico",
            "county": "Utuado",
        }
        with patch.object(df_mod, "HMGP_MASTER_PATH", fake_master), \
             patch.object(df_mod, "HMGP_RAW_DIR", fake_raw_dir), \
             patch.object(df_mod, "HMGP_RAW_PATH", fake_raw_dir / "fema_hmgp_raw.csv"), \
             patch.object(df_mod, "PROCESSED_DIR", tmp_path), \
             patch("scripts.download_fema._fetch_hmgp_records",
                   return_value=([hmgp_record], "hmgp_summaries")):
            rows, path_str = df_mod.download_hmgp(force=True, logger=self._make_logger())

        assert rows == 1
        assert fake_master.exists()


# ---------------------------------------------------------------------------
# run() — integration with mocked download_pa / download_hmgp
# ---------------------------------------------------------------------------

class TestRun:
    def test_run_returns_expected_keys(self, tmp_path):
        """run() returns dict with pa_rows, hmgp_rows, pa_path, hmgp_path."""
        with patch("scripts.download_fema.download_pa", return_value=(10, "/tmp/pa.csv")), \
             patch("scripts.download_fema.download_hmgp", return_value=(5, "/tmp/hmgp.csv")):
            result = df_mod.run(root=tmp_path)

        assert "pa_rows" in result
        assert "hmgp_rows" in result
        assert "pa_path" in result
        assert "hmgp_path" in result

    def test_run_returns_correct_row_counts(self, tmp_path):
        """run() propagates row counts from download functions."""
        with patch("scripts.download_fema.download_pa", return_value=(42, "/tmp/pa.csv")), \
             patch("scripts.download_fema.download_hmgp", return_value=(7, "/tmp/hmgp.csv")):
            result = df_mod.run(root=tmp_path)

        assert result["pa_rows"] == 42
        assert result["hmgp_rows"] == 7

    def test_run_uses_existing_masters_when_present(self, tmp_path):
        """run() with pre-created output files uses cached data (force=False behaviour)."""
        fake_pa_master = tmp_path / "pr_fema_pa_master.csv"
        fake_hmgp_master = tmp_path / "pr_fema_hmgp_master.csv"

        # Create dummy master files (5 rows each)
        dummy = pd.DataFrame([{"award_id": f"FEMA-PA-{i}"} for i in range(5)])
        dummy.to_csv(fake_pa_master, index=False)
        dummy.to_csv(fake_hmgp_master, index=False)

        with patch.object(df_mod, "PA_MASTER_PATH", fake_pa_master), \
             patch.object(df_mod, "HMGP_MASTER_PATH", fake_hmgp_master):
            result = df_mod.run(root=tmp_path)

        # Cached read: each master has 5 rows
        assert result["pa_rows"] == 5
        assert result["hmgp_rows"] == 5


# ---------------------------------------------------------------------------
# _paginate URL construction — verify OData params are in the raw URL
# ---------------------------------------------------------------------------

class TestPaginateUrlBuilding:
    """Verify that _paginate builds correct raw URLs without percent-encoding $ signs."""

    def test_url_contains_top_and_skip(self):
        """_paginate must embed $top and $skip in the URL (not percent-encoded)."""
        captured_urls = []

        def fake_get_with_retry(url, logger):
            captured_urls.append(url)
            # Return a single page then signal empty second page
            if "$skip=0" in url:
                return {"metadata": {"count": 1}, "TestKey": [{"id": 1}]}
            return {"metadata": {"count": 1}, "TestKey": []}

        with patch("scripts.download_fema._get_with_retry", side_effect=fake_get_with_retry), \
             patch("scripts.download_fema.time.sleep"):
            import logging as _logging
            logger = _logging.getLogger("test_paginate")
            logger.setLevel(_logging.CRITICAL)
            df_mod._paginate("https://example.com/api", "TestKey", {}, logger)

        assert len(captured_urls) >= 1
        first_url = captured_urls[0]
        assert "$top=" in first_url
        assert "$skip=" in first_url
        assert "%24" not in first_url  # $ must NOT be percent-encoded

    def test_filter_clause_appended(self):
        """_paginate appends $filter to the URL when provided."""
        captured_urls = []

        def fake_get_with_retry(url, logger):
            captured_urls.append(url)
            return {"TestKey": []}  # empty → stop after first call

        with patch("scripts.download_fema._get_with_retry", side_effect=fake_get_with_retry), \
             patch("scripts.download_fema.time.sleep"):
            import logging as _logging
            logger = _logging.getLogger("test_paginate_filter")
            logger.setLevel(_logging.CRITICAL)
            df_mod._paginate(
                "https://example.com/api",
                "TestKey",
                {"$filter": "state eq 'PR'"},
                logger,
            )

        assert len(captured_urls) >= 1
        assert "$filter=state eq 'PR'" in captured_urls[0]
