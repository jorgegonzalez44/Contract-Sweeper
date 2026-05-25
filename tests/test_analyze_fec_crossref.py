"""Tests for scripts/analyze_fec_crossref.py — FEC campaign contribution crossref."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_fec_crossref import _normalize, build_crossref


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_awards(root: Path, rows: list[dict]) -> None:
    path = root / "data" / "staging" / "processed" / "pr_all_awards_master.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["recipient_name", "obligated_amount", "award_id", "source_dataset"]
    pd.DataFrame([{k: r.get(k, "") for k in fields} for r in rows]).to_csv(path, index=False)


def _write_fec(root: Path, rows: list[dict]) -> None:
    path = root / "data" / "staging" / "processed" / "pr_fec_contributions.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "contributor_name", "contribution_receipt_amount", "committee_name",
        "candidate_name", "contribution_receipt_date",
    ]
    pd.DataFrame([{k: r.get(k, "") for k in fields} for r in rows]).to_csv(path, index=False)


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_empty_string_returns_empty(self):
        assert _normalize("") == ""

    def test_nan_returns_empty(self):
        assert _normalize(float("nan")) == ""

    def test_none_returns_empty(self):
        assert _normalize(None) == ""

    def test_uppercases(self):
        assert _normalize("acme corp") == "ACME"

    def test_strips_inc_suffix(self):
        assert _normalize("ACME INC") == "ACME"

    def test_strips_llc_suffix(self):
        assert _normalize("Delta LLC") == "DELTA"

    def test_strips_llp_suffix(self):
        assert _normalize("Smith Partners LLP") == "SMITH PARTNERS"

    def test_strips_corp_suffix(self):
        assert _normalize("Global Corp") == "GLOBAL"

    def test_strips_co_suffix(self):
        assert _normalize("Widgets CO") == "WIDGETS"

    def test_strips_ltd_suffix(self):
        assert _normalize("Acme LTD") == "ACME"

    def test_strips_lp_suffix(self):
        assert _normalize("Partners LP") == "PARTNERS"

    def test_strips_pc_suffix(self):
        assert _normalize("Law Firm PC") == "LAW FIRM"

    def test_strips_pllc_suffix(self):
        assert _normalize("Law PLLC") == "LAW"

    def test_strips_dba_suffix(self):
        assert _normalize("Store DBA") == "STORE"

    def test_strips_the_suffix(self):
        assert _normalize("Company THE") == "COMPANY"

    def test_strips_and_suffix(self):
        assert _normalize("Smith AND") == "SMITH"

    def test_strips_of_suffix(self):
        assert _normalize("City OF") == "CITY"

    def test_multiple_trailing_suffixes(self):
        # "CORP INC" → strips INC, then CORP
        assert _normalize("Acme Corp Inc") == "ACME"

    def test_strips_punctuation(self):
        assert _normalize("Acme, Corp.") == "ACME"

    def test_collapses_multiple_spaces(self):
        assert _normalize("Acme   Corp   Inc") == "ACME"

    def test_hospital_not_stripped(self):
        # HOSPITAL is not in _SUFFIXES — critical difference from entity_profiles
        assert _normalize("General Hospital") == "GENERAL HOSPITAL"

    def test_health_not_stripped(self):
        # HEALTH is not in _SUFFIXES
        assert _normalize("Island Health") == "ISLAND HEALTH"

    def test_mid_token_suffix_not_stripped(self):
        # "INC" only stripped when trailing — "INCORPORATED" should stay
        assert _normalize("Incorporated Solutions") == "INCORPORATED SOLUTIONS"

    def test_interior_suffix_word_not_removed(self):
        # "AND" in the middle should not be removed (only trailing)
        result = _normalize("Smith And Jones Inc")
        assert "AND" in result or result == "SMITH AND JONES"


# ---------------------------------------------------------------------------
# build_crossref
# ---------------------------------------------------------------------------

class TestBuildCrossref:
    def test_missing_awards_returns_status(self, tmp_path):
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        result = build_crossref(root=tmp_path)
        assert result["rows"] == 0
        assert result["status"] == "MISSING_AWARDS"

    def test_missing_fec_returns_status(self, tmp_path):
        _write_awards(tmp_path, [
            {"recipient_name": "Acme Inc", "obligated_amount": "100000",
             "award_id": "AWD001", "source_dataset": "usaspending"},
        ])
        result = build_crossref(root=tmp_path)
        assert result["rows"] == 0
        assert result["status"] == "MISSING_FEC"

    def test_matched_entities_returned(self, tmp_path):
        _write_awards(tmp_path, [
            {"recipient_name": "Acme Inc", "obligated_amount": "500000",
             "award_id": "AWD001", "source_dataset": "usaspending"},
        ])
        _write_fec(tmp_path, [
            {"contributor_name": "ACME", "contribution_receipt_amount": "5000",
             "committee_name": "Committee A", "candidate_name": "Candidate X",
             "contribution_receipt_date": "2022-01-01"},
        ])
        result = build_crossref(root=tmp_path)
        assert result["rows"] == 1
        assert result["status"] == "OK"

    def test_no_matches_returns_empty(self, tmp_path):
        _write_awards(tmp_path, [
            {"recipient_name": "Alpha Corp", "obligated_amount": "100000",
             "award_id": "AWD001", "source_dataset": "usaspending"},
        ])
        _write_fec(tmp_path, [
            {"contributor_name": "Totally Different", "contribution_receipt_amount": "1000",
             "committee_name": "Committee B", "candidate_name": "",
             "contribution_receipt_date": "2022-01-01"},
        ])
        result = build_crossref(root=tmp_path)
        assert result["rows"] == 0
        assert result["status"] == "EMPTY"

    def test_output_file_written(self, tmp_path):
        _write_awards(tmp_path, [
            {"recipient_name": "Beta LLC", "obligated_amount": "200000",
             "award_id": "AWD002", "source_dataset": "usaspending"},
        ])
        _write_fec(tmp_path, [
            {"contributor_name": "BETA", "contribution_receipt_amount": "2000",
             "committee_name": "PAC A", "candidate_name": "",
             "contribution_receipt_date": "2022-06-15"},
        ])
        build_crossref(root=tmp_path)
        out_path = tmp_path / "data" / "staging" / "processed" / "pr_fec_crossref.csv"
        assert out_path.exists()

    def test_matched_row_has_both_award_and_fec_columns(self, tmp_path):
        _write_awards(tmp_path, [
            {"recipient_name": "Gamma Corp", "obligated_amount": "300000",
             "award_id": "AWD003", "source_dataset": "usaspending"},
        ])
        _write_fec(tmp_path, [
            {"contributor_name": "GAMMA", "contribution_receipt_amount": "3000",
             "committee_name": "PAC B", "candidate_name": "",
             "contribution_receipt_date": "2022-03-10"},
        ])
        build_crossref(root=tmp_path)
        out_path = tmp_path / "data" / "staging" / "processed" / "pr_fec_crossref.csv"
        df = pd.read_csv(out_path)
        assert "total_awards_obligated" in df.columns
        assert "total_contributions" in df.columns
        assert "award_recipient_name" in df.columns
        assert "fec_contributor_name" in df.columns

    def test_unmatched_award_not_in_output(self, tmp_path):
        _write_awards(tmp_path, [
            {"recipient_name": "Delta Inc", "obligated_amount": "100000",
             "award_id": "AWD001", "source_dataset": "usaspending"},
            {"recipient_name": "NoMatch Corp", "obligated_amount": "50000",
             "award_id": "AWD002", "source_dataset": "usaspending"},
        ])
        _write_fec(tmp_path, [
            {"contributor_name": "DELTA", "contribution_receipt_amount": "1000",
             "committee_name": "PAC", "candidate_name": "",
             "contribution_receipt_date": "2022-01-01"},
        ])
        build_crossref(root=tmp_path)
        out_path = tmp_path / "data" / "staging" / "processed" / "pr_fec_crossref.csv"
        df = pd.read_csv(out_path)
        names = df["award_recipient_name"].tolist()
        assert not any("NoMatch" in str(n) for n in names)

    def test_normalization_enables_case_insensitive_match(self, tmp_path):
        # Award uses "acme inc" (lowercase), FEC uses "ACME INC" — both normalize to "ACME"
        _write_awards(tmp_path, [
            {"recipient_name": "acme inc", "obligated_amount": "100000",
             "award_id": "AWD001", "source_dataset": "usaspending"},
        ])
        _write_fec(tmp_path, [
            {"contributor_name": "ACME INC", "contribution_receipt_amount": "1000",
             "committee_name": "PAC", "candidate_name": "",
             "contribution_receipt_date": "2022-01-01"},
        ])
        result = build_crossref(root=tmp_path)
        assert result["rows"] == 1
