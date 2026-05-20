"""Tests for scripts/download_hud_drgr_public.py — HUD CDBG-DR public data downloader."""

import logging
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Suppress noisy log output
logging.getLogger("download_hud_drgr_public").setLevel(logging.CRITICAL)
logging.getLogger("test").setLevel(logging.CRITICAL)

from scripts.download_hud_drgr_public import (
    CFDA_CDBG_DR,
    CFDA_CDBG_MIT,
    DRGR_GRANT_COLUMNS,
    EGIS_CDBG_ENDPOINTS,
    HUD_EGIS_BASE,
    USA_SPENDING_URL,
    _deduplicate,
    _empty_df,
    _safe_float,
    _safe_int,
    _year_from_date,
    run,
)


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------

class TestSafeFloat:
    def test_integer_value(self):
        assert _safe_float(1000) == 1000.0

    def test_string_with_commas(self):
        assert _safe_float("1,234,567.89") == 1234567.89

    def test_plain_string(self):
        assert _safe_float("99.5") == 99.5

    def test_none_returns_none(self):
        assert _safe_float(None) is None

    def test_invalid_string_returns_none(self):
        assert _safe_float("N/A") is None

    def test_empty_string_returns_none(self):
        assert _safe_float("") is None

    def test_zero_returns_zero(self):
        assert _safe_float(0) == 0.0


# ---------------------------------------------------------------------------
# _safe_int
# ---------------------------------------------------------------------------

class TestSafeInt:
    def test_integer_value(self):
        assert _safe_int(2021) == 2021

    def test_string_value(self):
        assert _safe_int("2019") == 2019

    def test_none_returns_none(self):
        assert _safe_int(None) is None

    def test_non_numeric_string_returns_none(self):
        assert _safe_int("abc") is None

    def test_float_string_returns_none(self):
        # int("2019.5") raises ValueError
        assert _safe_int("2019.5") is None


# ---------------------------------------------------------------------------
# _year_from_date
# ---------------------------------------------------------------------------

class TestYearFromDate:
    def test_iso_date_returns_year(self):
        assert _year_from_date("2020-06-15") == 2020

    def test_year_only_string(self):
        assert _year_from_date("2018") == 2018

    def test_empty_string_returns_none(self):
        assert _year_from_date("") is None

    def test_none_returns_none(self):
        assert _year_from_date(None) is None

    def test_partial_date(self):
        assert _year_from_date("2017-01") == 2017


# ---------------------------------------------------------------------------
# _empty_df
# ---------------------------------------------------------------------------

class TestEmptyDf:
    def test_returns_dataframe(self):
        df = _empty_df()
        assert isinstance(df, pd.DataFrame)

    def test_has_correct_columns(self):
        df = _empty_df()
        assert list(df.columns) == DRGR_GRANT_COLUMNS

    def test_has_zero_rows(self):
        df = _empty_df()
        assert len(df) == 0


# ---------------------------------------------------------------------------
# _deduplicate
# ---------------------------------------------------------------------------

class TestDeduplicate:
    def _make_record(self, grant_number, source="USASpending"):
        return {
            "grant_number": grant_number,
            "grantee_name": "Test Grantee",
            "grantee_normalized": "TEST GRANTEE",
            "disaster_number": "",
            "appropriation_year": 2017,
            "award_date": "2017-01-01",
            "grant_amount": 1_000_000.0,
            "amount_drawn": None,
            "amount_remaining": None,
            "program_type": "CDBG-DR",
            "cfda_number": "14.269",
            "source_system": source,
            "pull_date": "2024-01-01",
        }

    def test_empty_list_returns_empty_df(self):
        df = _deduplicate([])
        assert isinstance(df, pd.DataFrame)
        assert list(df.columns) == DRGR_GRANT_COLUMNS
        assert len(df) == 0

    def test_single_record_preserved(self):
        records = [self._make_record("B-17-DL-72-0001")]
        df = _deduplicate(records)
        assert len(df) == 1
        assert df.iloc[0]["grant_number"] == "B-17-DL-72-0001"

    def test_deduplicates_by_grant_number(self):
        records = [
            self._make_record("B-17-DL-72-0001", "USASpending"),
            self._make_record("B-17-DL-72-0001", "HUD_EGIS"),
            self._make_record("B-19-DL-72-0002", "USASpending"),
        ]
        df = _deduplicate(records)
        assert len(df) == 2

    def test_keeps_first_occurrence_on_duplicate(self):
        records = [
            self._make_record("DUP-001", "USASpending"),
            self._make_record("DUP-001", "HUD_EGIS"),
        ]
        df = _deduplicate(records)
        assert df.iloc[0]["source_system"] == "USASpending"

    def test_returns_dataframe_with_correct_columns(self):
        records = [self._make_record("B-17-DL-72-0003")]
        df = _deduplicate(records)
        assert list(df.columns) == DRGR_GRANT_COLUMNS

    def test_index_reset_after_dedup(self):
        records = [
            self._make_record("A-001"),
            self._make_record("A-001"),
            self._make_record("A-002"),
        ]
        df = _deduplicate(records)
        assert list(df.index) == [0, 1]


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------

class TestConstants:
    def test_cfda_dr_format(self):
        assert CFDA_CDBG_DR == "14.269"

    def test_cfda_mit_format(self):
        assert CFDA_CDBG_MIT == "14.228"

    def test_usa_spending_url_is_https(self):
        assert USA_SPENDING_URL.startswith("https://")

    def test_egis_endpoints_nonempty(self):
        assert len(EGIS_CDBG_ENDPOINTS) >= 1

    def test_egis_base_is_hud_gov(self):
        assert "hud.gov" in HUD_EGIS_BASE

    def test_drgr_grant_columns_has_required_fields(self):
        required = {"grant_number", "grantee_name", "grant_amount", "source_system", "pull_date"}
        assert required.issubset(set(DRGR_GRANT_COLUMNS))


# ---------------------------------------------------------------------------
# run() — caching path
# ---------------------------------------------------------------------------

class TestRunCaching:
    def test_skips_download_when_output_exists_force_false(self, tmp_path):
        """Pre-existing output file causes run() to return CACHED without HTTP."""
        out_dir = tmp_path / "data" / "normalized"
        out_dir.mkdir(parents=True)
        out_file = out_dir / "hud_drgr_grants.parquet"

        # Write a minimal parquet file so pq_read succeeds
        df_existing = _empty_df()
        df_existing.to_parquet(out_file, index=False)

        with patch("scripts.download_hud_drgr_public._session") as mock_session_fn:
            result = run(root=tmp_path, force=False)

        # HTTP session should never have been created for fetching
        mock_session_fn.assert_not_called()
        assert result["status"] == "CACHED"
        assert "path" in result
        assert "rows" in result

    def test_cached_result_has_correct_row_count(self, tmp_path):
        """CACHED result reports row count from the existing file."""
        out_dir = tmp_path / "data" / "normalized"
        out_dir.mkdir(parents=True)
        out_file = out_dir / "hud_drgr_grants.parquet"

        # Write a file with known row count
        records = [
            {col: "x" for col in DRGR_GRANT_COLUMNS}
            for _ in range(3)
        ]
        pd.DataFrame(records, columns=DRGR_GRANT_COLUMNS).to_parquet(out_file, index=False)

        with patch("scripts.download_hud_drgr_public._session"):
            result = run(root=tmp_path, force=False)

        assert result["status"] == "CACHED"
        assert result["rows"] == 3

    def test_force_true_ignores_cached_file(self, tmp_path):
        """force=True re-downloads even if the output file already exists."""
        out_dir = tmp_path / "data" / "normalized"
        out_dir.mkdir(parents=True)
        out_file = out_dir / "hud_drgr_grants.parquet"
        _empty_df().to_parquet(out_file, index=False)

        # Patch all three fetch functions so no real HTTP calls are made
        with patch("scripts.download_hud_drgr_public._fetch_usaspending", return_value=[]) as m_usa, \
             patch("scripts.download_hud_drgr_public._fetch_egis", return_value=[]) as m_egis, \
             patch("scripts.download_hud_drgr_public._fetch_hud_html", return_value=[]) as m_html, \
             patch("scripts.download_hud_drgr_public._session"):
            result = run(root=tmp_path, force=True)

        m_usa.assert_called_once()
        m_egis.assert_called_once()
        m_html.assert_called_once()
        assert result["status"] in ("OK", "EMPTY")


# ---------------------------------------------------------------------------
# run() — download integration with mocked HTTP
# ---------------------------------------------------------------------------

def _make_usaspending_response(results=None, last_page=1):
    """Build a mock USASpending API response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "results": results or [],
        "page_metadata": {"last_page": last_page},
    }
    return resp


def _make_egis_response(features=None, exceeds=False):
    """Build a mock EGIS ArcGIS REST response."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "features": features or [],
        "exceededTransferLimit": exceeds,
    }
    return resp


class TestRunWithMockedHttp:
    def test_run_returns_dict_with_required_keys(self, tmp_path):
        """run() always returns a dict with rows, path, and status."""
        with patch("scripts.download_hud_drgr_public._fetch_usaspending", return_value=[]), \
             patch("scripts.download_hud_drgr_public._fetch_egis", return_value=[]), \
             patch("scripts.download_hud_drgr_public._fetch_hud_html", return_value=[]), \
             patch("scripts.download_hud_drgr_public._session"):
            result = run(root=tmp_path)

        assert isinstance(result, dict)
        assert "rows" in result
        assert "path" in result
        assert "status" in result

    def test_run_empty_sources_returns_empty_status(self, tmp_path):
        """When all sources return nothing, status is EMPTY."""
        with patch("scripts.download_hud_drgr_public._fetch_usaspending", return_value=[]), \
             patch("scripts.download_hud_drgr_public._fetch_egis", return_value=[]), \
             patch("scripts.download_hud_drgr_public._fetch_hud_html", return_value=[]), \
             patch("scripts.download_hud_drgr_public._session"):
            result = run(root=tmp_path)

        assert result["status"] == "EMPTY"
        assert result["rows"] == 0

    def test_run_writes_output_file(self, tmp_path):
        """run() creates the parquet output file."""
        with patch("scripts.download_hud_drgr_public._fetch_usaspending", return_value=[]), \
             patch("scripts.download_hud_drgr_public._fetch_egis", return_value=[]), \
             patch("scripts.download_hud_drgr_public._fetch_hud_html", return_value=[]), \
             patch("scripts.download_hud_drgr_public._session"):
            result = run(root=tmp_path)

        out_path = Path(result["path"])
        # Accept either .parquet or .csv (parquet_utils CSV fallback)
        assert out_path.exists() or out_path.with_suffix(".csv").exists()

    def test_run_with_usaspending_data_returns_ok(self, tmp_path):
        """When USASpending returns records, status is OK."""
        from datetime import date
        records = [
            {
                "grant_number": "B-17-DL-72-0001",
                "grantee_name": "Puerto Rico",
                "grantee_normalized": "PUERTO RICO",
                "disaster_number": "",
                "appropriation_year": 2017,
                "award_date": "2017-01-01",
                "grant_amount": 5_000_000.0,
                "amount_drawn": None,
                "amount_remaining": None,
                "program_type": "CDBG-DR",
                "cfda_number": "14.269",
                "source_system": "USASpending",
                "pull_date": str(date.today()),
            }
        ]

        with patch("scripts.download_hud_drgr_public._fetch_usaspending", return_value=records), \
             patch("scripts.download_hud_drgr_public._fetch_egis", return_value=[]), \
             patch("scripts.download_hud_drgr_public._fetch_hud_html", return_value=[]), \
             patch("scripts.download_hud_drgr_public._session"):
            result = run(root=tmp_path)

        assert result["status"] == "OK"
        assert result["rows"] == 1

    def test_run_deduplicates_across_sources(self, tmp_path):
        """Records with the same grant_number from different sources are deduplicated."""
        from datetime import date
        shared_grant = "B-17-DL-72-0001"
        make_rec = lambda src: {
            "grant_number": shared_grant,
            "grantee_name": "PR",
            "grantee_normalized": "PR",
            "disaster_number": "",
            "appropriation_year": 2017,
            "award_date": "2017-01-01",
            "grant_amount": 1_000_000.0,
            "amount_drawn": None,
            "amount_remaining": None,
            "program_type": "CDBG-DR",
            "cfda_number": "14.269",
            "source_system": src,
            "pull_date": str(date.today()),
        }

        with patch("scripts.download_hud_drgr_public._fetch_usaspending", return_value=[make_rec("USASpending")]), \
             patch("scripts.download_hud_drgr_public._fetch_egis", return_value=[make_rec("HUD_EGIS")]), \
             patch("scripts.download_hud_drgr_public._fetch_hud_html", return_value=[]), \
             patch("scripts.download_hud_drgr_public._session"):
            result = run(root=tmp_path)

        assert result["rows"] == 1
        assert result["status"] == "OK"

    def test_run_path_points_to_normalized_dir(self, tmp_path):
        """Output path is inside data/normalized/."""
        with patch("scripts.download_hud_drgr_public._fetch_usaspending", return_value=[]), \
             patch("scripts.download_hud_drgr_public._fetch_egis", return_value=[]), \
             patch("scripts.download_hud_drgr_public._fetch_hud_html", return_value=[]), \
             patch("scripts.download_hud_drgr_public._session"):
            result = run(root=tmp_path)

        assert "normalized" in result["path"]
        assert "hud_drgr_grants" in result["path"]

    def test_run_fetch_exception_handled_gracefully(self, tmp_path):
        """Exceptions in individual fetch calls are caught; run() still completes."""
        with patch("scripts.download_hud_drgr_public._fetch_usaspending", side_effect=RuntimeError("boom")), \
             patch("scripts.download_hud_drgr_public._fetch_egis", return_value=[]), \
             patch("scripts.download_hud_drgr_public._fetch_hud_html", return_value=[]), \
             patch("scripts.download_hud_drgr_public._session"):
            result = run(root=tmp_path)

        assert result["status"] in ("OK", "EMPTY")
        assert isinstance(result["rows"], int)
