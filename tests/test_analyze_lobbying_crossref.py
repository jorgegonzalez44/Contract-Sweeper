"""Tests for scripts/analyze_lobbying_crossref.py — LDA lobbying crossref."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_lobbying_crossref import (
    _merge_pipe,
    _normalize,
    _year_range,
    build_crossref,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_awards(root: Path, rows: list[dict]) -> None:
    path = root / "data" / "staging" / "processed" / "pr_all_awards_master.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["recipient_name", "obligated_amount", "award_id", "source_dataset", "fiscal_year"]
    pd.DataFrame([{k: r.get(k, "") for k in fields} for r in rows]).to_csv(path, index=False)


def _write_lda(root: Path, rows: list[dict]) -> None:
    path = root / "data" / "staging" / "processed" / "pr_lda_filings.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "client_name", "client_state", "client_description",
        "filing_uuid", "filing_year", "income", "expenses",
        "general_issue_codes", "lobbyist_names", "registrant_name",
    ]
    pd.DataFrame([{k: r.get(k, "") for k in fields} for r in rows]).to_csv(path, index=False)


def _lda_row(client: str, state: str = "PR", income: str = "0",
             expenses: str = "50000", uuid: str = "UUID001",
             year: str = "2022", registrant: str = "Lobby Firm A") -> dict:
    return {
        "client_name": client, "client_state": state,
        "client_description": "A PR entity", "filing_uuid": uuid,
        "filing_year": year, "income": income, "expenses": expenses,
        "general_issue_codes": "FED|HHS", "lobbyist_names": "Lobbyist A",
        "registrant_name": registrant,
    }


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_empty_returns_empty(self):
        assert _normalize("") == ""

    def test_nan_returns_empty(self):
        assert _normalize(float("nan")) == ""

    def test_strips_inc(self):
        assert _normalize("Acme INC") == "ACME"

    def test_strips_sa(self):
        # SA is in lobbying suffix set (not in FEC set)
        assert _normalize("Empresa SA") == "EMPRESA"

    def test_strips_sl(self):
        # SL is in lobbying suffix set (not in FEC set)
        assert _normalize("Empresa SL") == "EMPRESA"

    def test_strips_srl(self):
        assert _normalize("Empresa SRL") == "EMPRESA"

    def test_strips_corp(self):
        assert _normalize("Delta Corp") == "DELTA"

    def test_strips_llc(self):
        assert _normalize("Alpha LLC") == "ALPHA"

    def test_strips_punctuation(self):
        result = _normalize("Acme, Corp.")
        assert "," not in result

    def test_collapses_spaces(self):
        result = _normalize("Acme   Corp   Inc")
        assert "  " not in result

    def test_uppercases(self):
        assert _normalize("acme inc") == "ACME"

    def test_multiple_trailing_suffixes(self):
        assert _normalize("Acme Corp Inc") == "ACME"

    def test_hospital_not_stripped(self):
        # HOSPITAL is not a suffix in this script
        assert _normalize("General Hospital") == "GENERAL HOSPITAL"


# ---------------------------------------------------------------------------
# _year_range
# ---------------------------------------------------------------------------

class TestYearRange:
    def test_single_year(self):
        assert _year_range(pd.Series(["2022"])) == "2022"

    def test_range(self):
        assert _year_range(pd.Series(["2019", "2021", "2023"])) == "2019-2023"

    def test_empty_series(self):
        assert _year_range(pd.Series([], dtype=str)) == ""

    def test_non_numeric_ignored(self):
        result = _year_range(pd.Series(["2020", "N/A", "2022"]))
        assert result == "2020-2022"


# ---------------------------------------------------------------------------
# _merge_pipe
# ---------------------------------------------------------------------------

class TestMergePipe:
    def test_basic_dedup(self):
        s = pd.Series(["A|B", "B|C", "A"])
        result = _merge_pipe(s, limit=10)
        parts = result.split("|")
        assert len(parts) == len(set(parts))  # no duplicates
        assert "A" in parts and "B" in parts and "C" in parts

    def test_limit_applied(self):
        s = pd.Series([f"Item{i}" for i in range(20)])
        result = _merge_pipe(s, limit=5)
        assert len(result.split("|")) <= 5

    def test_empty_series_returns_empty(self):
        assert _merge_pipe(pd.Series([], dtype=str), limit=10) == ""

    def test_nan_skipped(self):
        s = pd.Series([float("nan"), "A|B"])
        result = _merge_pipe(s, limit=10)
        assert "A" in result


# ---------------------------------------------------------------------------
# build_crossref
# ---------------------------------------------------------------------------

class TestBuildCrossref:
    def test_missing_awards_returns_status(self, tmp_path):
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        result = build_crossref(root=tmp_path)
        assert result["rows"] == 0
        assert result["status"] == "MISSING_AWARDS"

    def test_missing_lda_returns_status(self, tmp_path):
        _write_awards(tmp_path, [
            {"recipient_name": "Corp A", "obligated_amount": "100000",
             "award_id": "AWD001", "source_dataset": "usaspending"},
        ])
        result = build_crossref(root=tmp_path)
        assert result["rows"] == 0
        assert result["status"] == "MISSING_LDA"

    def test_matched_entities_returned(self, tmp_path):
        _write_awards(tmp_path, [
            {"recipient_name": "Acme Inc", "obligated_amount": "500000",
             "award_id": "AWD001", "source_dataset": "usaspending"},
        ])
        _write_lda(tmp_path, [_lda_row("ACME", expenses="75000")])
        result = build_crossref(root=tmp_path)
        assert result["rows"] == 1
        assert result["status"] == "OK"

    def test_no_matches_returns_empty(self, tmp_path):
        _write_awards(tmp_path, [
            {"recipient_name": "Alpha Corp", "obligated_amount": "100000",
             "award_id": "AWD001", "source_dataset": "usaspending"},
        ])
        _write_lda(tmp_path, [_lda_row("Totally Different Entity")])
        result = build_crossref(root=tmp_path)
        assert result["rows"] == 0
        assert result["status"] == "EMPTY"

    def test_output_file_written(self, tmp_path):
        _write_awards(tmp_path, [
            {"recipient_name": "Beta Inc", "obligated_amount": "200000",
             "award_id": "AWD002", "source_dataset": "usaspending"},
        ])
        _write_lda(tmp_path, [_lda_row("BETA")])
        build_crossref(root=tmp_path)
        out = tmp_path / "data" / "staging" / "processed" / "pr_lobbying_crossref.csv"
        assert out.exists()

    def test_matched_row_has_award_and_lda_columns(self, tmp_path):
        _write_awards(tmp_path, [
            {"recipient_name": "Gamma Corp", "obligated_amount": "300000",
             "award_id": "AWD003", "source_dataset": "usaspending"},
        ])
        _write_lda(tmp_path, [_lda_row("GAMMA", expenses="120000")])
        build_crossref(root=tmp_path)
        df = pd.read_csv(
            tmp_path / "data" / "staging" / "processed" / "pr_lobbying_crossref.csv"
        )
        assert "total_awards_obligated" in df.columns
        assert "total_client_expenses" in df.columns
        assert "award_recipient_name" in df.columns
        assert "lda_client_name" in df.columns

    def test_normalization_enables_match(self, tmp_path):
        # Award: "acme inc" (lowercase), LDA: "ACME INC" — both normalize to "ACME"
        _write_awards(tmp_path, [
            {"recipient_name": "acme inc", "obligated_amount": "100000",
             "award_id": "AWD001", "source_dataset": "usaspending"},
        ])
        _write_lda(tmp_path, [_lda_row("ACME INC")])
        result = build_crossref(root=tmp_path)
        assert result["rows"] == 1

    def test_unmatched_award_not_in_output(self, tmp_path):
        _write_awards(tmp_path, [
            {"recipient_name": "Matched Corp", "obligated_amount": "100000",
             "award_id": "AWD001", "source_dataset": "usaspending"},
            {"recipient_name": "Unmatched Corp", "obligated_amount": "50000",
             "award_id": "AWD002", "source_dataset": "usaspending"},
        ])
        _write_lda(tmp_path, [_lda_row("MATCHED")])
        build_crossref(root=tmp_path)
        df = pd.read_csv(
            tmp_path / "data" / "staging" / "processed" / "pr_lobbying_crossref.csv"
        )
        names = df["award_recipient_name"].tolist()
        assert not any("Unmatched" in str(n) for n in names)
