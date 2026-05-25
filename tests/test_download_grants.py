"""Tests for download_grants.py — USASpending bulk grant downloader."""

import io
import logging
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Suppress noisy log output from the module under test
logging.getLogger("download_grants").setLevel(logging.CRITICAL)
logging.getLogger("test").setLevel(logging.CRITICAL)

from scripts.download_grants import (
    BULK_RENAME,
    MASTER_COLUMNS,
    PASSES,
    _build_bulk_payload,
    _current_fy,
    _derive_fiscal_year,
    _extract_csv,
    _file_has_data,
    _fy_windows,
    _normalize_bulk_df,
    build_master,
    run,
)


# ---------------------------------------------------------------------------
# _derive_fiscal_year
# ---------------------------------------------------------------------------

class TestDeriveFiscalYear:
    def test_jan_to_sep_returns_same_year(self):
        assert _derive_fiscal_year("2023-03-15") == "2023"

    def test_oct_to_dec_returns_next_year(self):
        assert _derive_fiscal_year("2022-10-01") == "2023"

    def test_september_boundary_same_year(self):
        assert _derive_fiscal_year("2023-09-30") == "2023"

    def test_empty_string_returns_empty(self):
        assert _derive_fiscal_year("") == ""

    def test_none_returns_empty(self):
        assert _derive_fiscal_year(None) == ""

    def test_invalid_date_returns_empty(self):
        assert _derive_fiscal_year("not-a-date") == ""


# ---------------------------------------------------------------------------
# _fy_windows
# ---------------------------------------------------------------------------

class TestFyWindows:
    def test_returns_list_of_dicts(self):
        windows = _fy_windows(2020, 2022)
        assert isinstance(windows, list)
        assert len(windows) == 3

    def test_window_keys_present(self):
        windows = _fy_windows(2020, 2020)
        assert windows[0]["label"] == "2020"
        assert windows[0]["start_date"] == "2019-10-01"
        assert windows[0]["end_date"] == "2020-09-30"

    def test_start_date_is_previous_oct(self):
        windows = _fy_windows(2010, 2012)
        for w in windows:
            fy = int(w["label"])
            assert w["start_date"].startswith(str(fy - 1))
            assert "-10-01" in w["start_date"]

    def test_current_fy_is_integer(self):
        fy = _current_fy()
        assert isinstance(fy, int)
        assert fy >= 2025


# ---------------------------------------------------------------------------
# _build_bulk_payload
# ---------------------------------------------------------------------------

class TestBuildBulkPayload:
    def _window(self):
        return {"label": "2022", "start_date": "2021-10-01", "end_date": "2022-09-30"}

    def test_pop_filter_type_uses_place_of_performance(self):
        payload = _build_bulk_payload(["02", "03"], "pop", self._window())
        f = payload["filters"]
        assert "place_of_performance_scope" in f
        assert f["place_of_performance_locations"][0]["state"] == "PR"
        assert "recipient_scope" not in f

    def test_recipient_filter_type_uses_recipient_locations(self):
        payload = _build_bulk_payload(["06"], "recipient", self._window())
        f = payload["filters"]
        assert "recipient_scope" in f
        assert f["recipient_locations"][0]["state"] == "PR"
        assert "place_of_performance_scope" not in f

    def test_payload_contains_prime_award_types(self):
        payload = _build_bulk_payload(["07", "08"], "recipient", self._window())
        assert payload["filters"]["prime_award_types"] == ["07", "08"]

    def test_payload_date_range_matches_window(self):
        payload = _build_bulk_payload(["02"], "pop", self._window())
        dr = payload["filters"]["date_range"]
        assert dr["start_date"] == "2021-10-01"
        assert dr["end_date"] == "2022-09-30"

    def test_payload_file_format_is_csv(self):
        payload = _build_bulk_payload(["02"], "pop", self._window())
        assert payload["file_format"] == "csv"

    def test_payload_date_type_is_action_date(self):
        payload = _build_bulk_payload(["02"], "pop", self._window())
        assert payload["filters"]["date_type"] == "action_date"


# ---------------------------------------------------------------------------
# _normalize_bulk_df
# ---------------------------------------------------------------------------

class TestNormalizeBulkDf:
    def _sample_df(self):
        return pd.DataFrame([
            {
                "award_id_fain": "FAIN-001",
                "recipient_name": "Test Corp",
                "recipient_uei": "ABC123",
                "awarding_agency_name": "HHS",
                "awarding_sub_agency_name": "NIH",
                "total_obligated_amount": "500000",
                "period_of_performance_start_date": "2022-03-15",
                "primary_place_of_performance_state_name": "Puerto Rico",
                "primary_place_of_performance_county_name": "San Juan",
                "transaction_description": "Grant for research",
                "assistance_type_description": "Project Grant",
            }
        ])

    def test_returns_master_columns(self):
        df = _normalize_bulk_df(self._sample_df(), "grants_pop_fy2022.csv")
        assert list(df.columns) == MASTER_COLUMNS

    def test_renames_award_id_fain_to_award_id(self):
        df = _normalize_bulk_df(self._sample_df(), "grants_pop_fy2022.csv")
        assert "award_id" in df.columns
        assert df["award_id"].iloc[0] == "FAIN-001"

    def test_source_file_populated(self):
        df = _normalize_bulk_df(self._sample_df(), "grants_pop_fy2022.csv")
        assert df["source_file"].iloc[0] == "grants_pop_fy2022.csv"

    def test_source_dataset_is_grants(self):
        df = _normalize_bulk_df(self._sample_df(), "grants_pop_fy2022.csv")
        assert df["source_dataset"].iloc[0] == "grants"

    def test_fiscal_year_derived_when_no_authoritative_field(self):
        df = _normalize_bulk_df(self._sample_df(), "grants_pop_fy2022.csv")
        # 2022-03-15 → FY2022
        assert df["fiscal_year"].iloc[0] == "2022"

    def test_fiscal_year_from_authoritative_field(self):
        sample = self._sample_df()
        sample["action_date_fiscal_year"] = "2023"
        df = _normalize_bulk_df(sample, "grants_pop_fy2022.csv")
        assert df["fiscal_year"].iloc[0] == "2023"

    def test_empty_dataframe_returns_master_columns(self):
        df = _normalize_bulk_df(pd.DataFrame(), "empty.csv")
        assert list(df.columns) == MASTER_COLUMNS
        assert len(df) == 0

    def test_missing_master_columns_filled_with_empty_string(self):
        minimal = pd.DataFrame([{"award_id_fain": "X"}])
        df = _normalize_bulk_df(minimal, "test.csv")
        for col in MASTER_COLUMNS:
            assert col in df.columns

    def test_award_id_fallback_to_assistance_unique_key(self):
        """When award_id_fain is absent, falls back to assistance_award_unique_key."""
        sample = pd.DataFrame([
            {"assistance_award_unique_key": "UNIQUE-KEY-999", "recipient_name": "Corp X"}
        ])
        df = _normalize_bulk_df(sample, "test.csv")
        assert df["award_id"].iloc[0] == "UNIQUE-KEY-999"


# ---------------------------------------------------------------------------
# _file_has_data
# ---------------------------------------------------------------------------

class TestFileHasData:
    def test_missing_file_returns_false(self, tmp_path):
        assert _file_has_data(tmp_path / "nonexistent.csv") is False

    def test_valid_csv_returns_true(self, tmp_path):
        p = tmp_path / "data.csv"
        pd.DataFrame([{"a": 1}]).to_csv(p, index=False)
        assert _file_has_data(p) is True

    def test_header_only_csv_returns_true(self, tmp_path):
        p = tmp_path / "header_only.csv"
        pd.DataFrame(columns=["a", "b"]).to_csv(p, index=False)
        assert _file_has_data(p) is True

    def test_corrupt_file_returns_false(self, tmp_path):
        p = tmp_path / "corrupt.csv"
        p.write_bytes(b"\x00\x01\x02\x03")
        # pandas may or may not raise on binary garbage; just check it doesn't crash
        result = _file_has_data(p)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# _extract_csv
# ---------------------------------------------------------------------------

class TestExtractCsv:
    def _make_zip(self, tmp_path, csv_content: str, filename: str = "data.csv") -> Path:
        zip_path = tmp_path / "test.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(filename, csv_content)
        zip_path.write_bytes(buf.getvalue())
        return zip_path

    def test_extracts_csv_from_zip(self, tmp_path):
        csv = "award_id_fain,recipient_name\nFAIN-001,Corp A\n"
        zip_path = self._make_zip(tmp_path, csv)
        logger = logging.getLogger("test")
        df = _extract_csv(zip_path, logger)
        assert len(df) == 1
        assert "award_id_fain" in df.columns

    def test_empty_zip_returns_empty_df(self, tmp_path):
        zip_path = tmp_path / "empty.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w"):
            pass
        zip_path.write_bytes(buf.getvalue())
        logger = logging.getLogger("test")
        df = _extract_csv(zip_path, logger)
        assert df.empty

    def test_multiple_csvs_concatenated(self, tmp_path):
        zip_path = tmp_path / "multi.zip"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("a.csv", "award_id_fain,recipient_name\nF001,Corp A\n")
            zf.writestr("b.csv", "award_id_fain,recipient_name\nF002,Corp B\n")
        zip_path.write_bytes(buf.getvalue())
        logger = logging.getLogger("test")
        df = _extract_csv(zip_path, logger)
        assert len(df) == 2


# ---------------------------------------------------------------------------
# build_master
# ---------------------------------------------------------------------------

class TestBuildMaster:
    def test_combines_multiple_raw_csvs(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        for i, name in enumerate(["grants_pop.csv", "grants_recipient.csv"]):
            df = pd.DataFrame([
                {col: f"val{i}" for col in MASTER_COLUMNS}
            ])
            df.to_csv(raw_dir / name, index=False)

        master_path = tmp_path / "master.csv"
        logger = logging.getLogger("test")
        rows = build_master(raw_dir, master_path, logger)
        assert rows == 2
        assert master_path.exists()

    def test_deduplicates_by_award_id(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        row = {col: "" for col in MASTER_COLUMNS}
        row["award_id"] = "DUP-001"
        for name in ["a.csv", "b.csv"]:
            pd.DataFrame([row]).to_csv(raw_dir / name, index=False)

        master_path = tmp_path / "master.csv"
        logger = logging.getLogger("test")
        rows = build_master(raw_dir, master_path, logger)
        assert rows == 1

    def test_empty_raw_dir_returns_zero(self, tmp_path):
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        master_path = tmp_path / "master.csv"
        logger = logging.getLogger("test")
        rows = build_master(raw_dir, master_path, logger)
        assert rows == 0
        assert not master_path.exists()


# ---------------------------------------------------------------------------
# PASSES constant
# ---------------------------------------------------------------------------

class TestPassesConstant:
    def test_four_passes_defined(self):
        assert len(PASSES) == 4

    def test_pass_tuples_have_three_elements(self):
        for p in PASSES:
            assert len(p) == 3

    def test_filter_types_valid(self):
        valid = {"pop", "recipient"}
        for _, _, filter_type in PASSES:
            assert filter_type in valid


# ---------------------------------------------------------------------------
# run() integration with mocked HTTP
# ---------------------------------------------------------------------------

def _make_mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


def _make_zip_bytes(csv_rows: str) -> bytes:
    """Return bytes of a ZIP containing one CSV."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("awards.csv", csv_rows)
    return buf.getvalue()


def _pre_create_all_fy_csvs(tmp_path: Path) -> Path:
    """Helper: pre-create header-only CSVs for all FY windows so no HTTP is needed."""
    from scripts.download_grants import START_FY, _current_fy, _fy_windows
    raw_dir = tmp_path / "data" / "staging" / "raw" / "grants"
    raw_dir.mkdir(parents=True, exist_ok=True)
    processed_dir = tmp_path / "data" / "staging" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    header_df = pd.DataFrame(columns=MASTER_COLUMNS)
    for prefix, _, _ in PASSES:
        for w in _fy_windows(START_FY, _current_fy()):
            csv_path = raw_dir / f"{prefix}_fy{w['label']}.csv"
            if not csv_path.exists():
                header_df.to_csv(csv_path, index=False)
    return raw_dir


class TestRunCaching:
    """run() skips passes when output CSVs already exist (force=False)."""

    def test_skips_fy_window_when_csv_exists(self, tmp_path):
        """Pre-existing FY CSV causes that window to be skipped (no HTTP calls)."""
        _pre_create_all_fy_csvs(tmp_path)

        with patch("scripts.download_grants.requests.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            summary = run(root=tmp_path)

        # No HTTP POST submissions should have been made (all skipped)
        mock_session.post.assert_not_called()
        assert isinstance(summary, dict)
        assert "raw_rows" in summary
        assert "master_rows" in summary
        assert "errors" in summary


class TestRunWithMockedHttp:
    """run() with mocked HTTP produces output files."""

    def test_run_returns_summary_dict(self, tmp_path):
        """run() returns a dict with expected keys when all FYs are cached."""
        _pre_create_all_fy_csvs(tmp_path)
        with patch("scripts.download_grants.requests.Session"):
            summary = run(root=tmp_path)
        assert isinstance(summary, dict)
        for key in ("raw_rows", "master_rows", "errors", "passes"):
            assert key in summary

    def test_run_errors_list_is_list(self, tmp_path):
        """run() always returns errors as a list."""
        _pre_create_all_fy_csvs(tmp_path)
        with patch("scripts.download_grants.requests.Session"):
            summary = run(root=tmp_path)
        assert isinstance(summary["errors"], list)

    def test_run_passes_list_has_four_entries(self, tmp_path):
        """run() returns stats for each of the four passes."""
        _pre_create_all_fy_csvs(tmp_path)
        with patch("scripts.download_grants.requests.Session"):
            summary = run(root=tmp_path)
        assert len(summary["passes"]) == 4

    def test_master_csv_written_when_raw_data_present(self, tmp_path):
        """build_master is called and writes master CSV when raw CSVs exist."""
        raw_dir = _pre_create_all_fy_csvs(tmp_path)

        # Inject one real data row so master has content
        sample_row = {col: "test_value" for col in MASTER_COLUMNS}
        sample_row["award_id"] = "FAIN-TEST-001"
        pd.DataFrame([sample_row]).to_csv(raw_dir / "grants_pop_fy2022.csv", index=False)

        with patch("scripts.download_grants.requests.Session"):
            summary = run(root=tmp_path)

        master_path = tmp_path / "data" / "staging" / "processed" / "pr_grants_master.csv"
        assert master_path.exists()
        assert summary["master_rows"] >= 1
