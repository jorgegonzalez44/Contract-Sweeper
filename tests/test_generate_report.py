"""Tests for scripts/generate_report.py — investigative report synthesis."""

import json
import logging
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.generate_report import (
    _fmt_usd,
    _load,
    _num,
    _pending,
    _section_awards,
    run,
)


def _logger():
    log = logging.getLogger("test_generate_report")
    log.addHandler(logging.NullHandler())
    return log


# ---------------------------------------------------------------------------
# _load
# ---------------------------------------------------------------------------

class TestLoad:
    def test_missing_file_returns_empty_dataframe(self, tmp_path):
        result = _load(tmp_path / "nonexistent.csv", "test", _logger())
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_existing_file_returns_dataframe(self, tmp_path):
        csv = tmp_path / "data.csv"
        pd.DataFrame({"col": ["a", "b"]}).to_csv(csv, index=False)
        result = _load(csv, "test", _logger())
        assert len(result) == 2
        assert "col" in result.columns

    def test_does_not_raise_on_missing_path(self, tmp_path):
        result = _load(tmp_path / "missing.csv", "label", _logger())  # must not raise
        assert isinstance(result, pd.DataFrame)


# ---------------------------------------------------------------------------
# _fmt_usd
# ---------------------------------------------------------------------------

class TestFmtUsd:
    def test_billions(self):
        assert _fmt_usd(2_500_000_000) == "$2.50B"

    def test_millions(self):
        assert _fmt_usd(1_500_000) == "$1.5M"

    def test_thousands(self):
        assert _fmt_usd(50_000) == "$50K"

    def test_small_value(self):
        assert _fmt_usd(999) == "$999"

    def test_zero(self):
        assert _fmt_usd(0) == "$0"

    def test_invalid_returns_na(self):
        assert _fmt_usd("not-a-number") == "N/A"

    def test_none_returns_na(self):
        assert _fmt_usd(None) == "N/A"

    def test_string_numeric_works(self):
        assert _fmt_usd("1000000") == "$1.0M"


# ---------------------------------------------------------------------------
# _num
# ---------------------------------------------------------------------------

class TestNum:
    def test_valid_column_returns_numeric(self):
        df = pd.DataFrame({"amount": ["100", "200.5", "300"]})
        result = _num(df, "amount")
        assert result.tolist() == pytest.approx([100.0, 200.5, 300.0])

    def test_missing_column_returns_zeros(self):
        df = pd.DataFrame({"other": ["a", "b"]})
        result = _num(df, "missing_col")
        assert (result == 0.0).all()

    def test_non_numeric_values_coerced_to_zero(self):
        df = pd.DataFrame({"amount": ["N/A", "100", "---"]})
        result = _num(df, "amount")
        assert result.iloc[0] == 0.0
        assert result.iloc[1] == 100.0
        assert result.iloc[2] == 0.0


# ---------------------------------------------------------------------------
# _pending
# ---------------------------------------------------------------------------

class TestPending:
    def test_returns_string(self):
        result = _pending("test label")
        assert isinstance(result, str)

    def test_contains_label(self):
        result = _pending("Federal awards section")
        assert "Federal awards section" in result


# ---------------------------------------------------------------------------
# _section_awards
# ---------------------------------------------------------------------------

class TestSectionAwards:
    def _award_df(self, rows: list[dict]) -> pd.DataFrame:
        return pd.DataFrame(rows)

    def test_empty_df_returns_pending_string(self):
        text, data = _section_awards(pd.DataFrame(), top_n=10)
        assert "pending" in text.lower()
        assert isinstance(data, dict)

    def test_returns_two_tuple(self):
        df = self._award_df([
            {"canonical_name": "Corp A", "total_obligated": "1000000",
             "award_count": "5", "source_datasets": "usaspending", "fiscal_year_range": "2020-2022"},
        ])
        result = _section_awards(df, top_n=10)
        assert len(result) == 2

    def test_markdown_table_in_output(self):
        df = self._award_df([
            {"canonical_name": "Corp A", "total_obligated": "1000000",
             "award_count": "5", "source_datasets": "usaspending", "fiscal_year_range": "2020-2022"},
        ])
        text, _ = _section_awards(df, top_n=10)
        assert "|" in text  # markdown table pipe characters

    def test_entity_name_in_output(self):
        df = self._award_df([
            {"canonical_name": "Island Builder Corp", "total_obligated": "5000000",
             "award_count": "10", "source_datasets": "usaspending|contracts",
             "fiscal_year_range": "2021-2023"},
        ])
        text, _ = _section_awards(df, top_n=10)
        assert "Island Builder Corp" in text


# ---------------------------------------------------------------------------
# run() — integration with tmp_path
# ---------------------------------------------------------------------------

class TestRunIntegration:
    def test_all_inputs_missing_writes_both_output_files(self, tmp_path):
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        run(root=tmp_path, force=True)
        report = tmp_path / "data" / "reports" / "pr_investigative_report.md"
        summary = tmp_path / "data" / "reports" / "pr_report_summary.json"
        assert report.exists()
        assert summary.exists()

    def test_all_inputs_missing_returns_ok_status(self, tmp_path):
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        result = run(root=tmp_path, force=True)
        assert result["status"] == "OK"

    def test_all_inputs_missing_data_layers_is_zero(self, tmp_path):
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        result = run(root=tmp_path, force=True)
        assert result["data_layers"] == 0

    def test_summary_json_has_required_keys(self, tmp_path):
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        run(root=tmp_path, force=True)
        summary = tmp_path / "data" / "reports" / "pr_report_summary.json"
        data = json.loads(summary.read_text())
        for key in ("generated_at", "data_layers", "awards", "power_network"):
            assert key in data

    def test_force_false_returns_cached_when_report_exists(self, tmp_path):
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        (tmp_path / "data" / "reports").mkdir(parents=True)
        (tmp_path / "data" / "reports" / "pr_investigative_report.md").write_text("existing")
        result = run(root=tmp_path, force=False)
        assert result["status"] == "CACHED"

    def test_with_entity_master_increments_data_layers(self, tmp_path):
        proc = tmp_path / "data" / "staging" / "processed"
        proc.mkdir(parents=True)
        entity_df = pd.DataFrame([{
            "canonical_name": "Test Corp", "total_obligated": "1000000",
            "award_count": "3", "source_datasets": "usaspending",
            "fiscal_year_range": "2022-2023",
        }])
        entity_df.to_csv(proc / "entity_master.csv", index=False)
        result = run(root=tmp_path, force=True)
        assert result["data_layers"] >= 1

    def test_result_contains_report_and_summary_paths(self, tmp_path):
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        result = run(root=tmp_path, force=True)
        assert "report_path" in result
        assert "summary_path" in result
