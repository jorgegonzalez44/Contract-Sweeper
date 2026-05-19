"""Tests for scripts/link_hud_drgr_to_contracts.py.

Covers:
- _similarity: SequenceMatcher ratio helper
- _find_match: exact / fuzzy / no-match logic
- run(): missing-inputs → graceful empty output
- run(): with fixture parquets and CSVs → output written with expected columns
"""

import csv
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.link_hud_drgr_to_contracts import (
    _similarity,
    _find_match,
    FUZZY_THRESHOLD,
    LINKAGE_COLUMNS,
    run,
)
from scripts.parquet_utils import pq_write


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_dirs(tmp_path: Path):
    """Create the directory structure expected by run()."""
    (tmp_path / "data" / "normalized").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "staging" / "processed").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "linked").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "logs").mkdir(parents=True, exist_ok=True)


def _write_csv(path: Path, rows: list, fieldnames: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# _similarity
# ---------------------------------------------------------------------------

class TestSimilarity:
    def test_identical_strings_return_one(self):
        assert _similarity("ACME CORP", "ACME CORP") == pytest.approx(1.0)

    def test_empty_first_arg_returns_zero(self):
        assert _similarity("", "ACME CORP") == 0.0

    def test_empty_second_arg_returns_zero(self):
        assert _similarity("ACME CORP", "") == 0.0

    def test_both_empty_returns_zero(self):
        assert _similarity("", "") == 0.0

    def test_partial_overlap_between_zero_and_one(self):
        score = _similarity("ACME CORPORATION", "ACME CORP")
        assert 0.0 < score < 1.0

    def test_completely_different_strings_low_score(self):
        score = _similarity("XYZZY FROBOZZ", "JOHN SMITH")
        assert score < FUZZY_THRESHOLD


# ---------------------------------------------------------------------------
# _find_match
# ---------------------------------------------------------------------------

class TestFindMatch:
    def _exact_lookup(self):
        return {"acme corp", "caribbean builders"}

    def test_exact_match_returns_exact_confidence(self):
        key, confidence = _find_match("acme corp", self._exact_lookup(), list(self._exact_lookup()))
        assert key == "acme corp"
        assert confidence == "exact"

    def test_fuzzy_match_above_threshold(self):
        # Very similar string should produce fuzzy match
        candidates = {"acme corporation"}
        key, confidence = _find_match("acme corporations", candidates, list(candidates))
        assert confidence == "fuzzy"
        assert key == "acme corporation"

    def test_no_match_below_threshold(self):
        candidates = {"totally different company xyz"}
        key, confidence = _find_match("acme corp", candidates, list(candidates))
        assert confidence == "none"
        assert key == ""

    def test_empty_norm_key_returns_none(self):
        key, confidence = _find_match("", {"acme corp"}, ["acme corp"])
        assert key == ""
        assert confidence == "none"

    def test_empty_candidates_returns_none(self):
        key, confidence = _find_match("acme corp", set(), [])
        assert key == ""
        assert confidence == "none"


# ---------------------------------------------------------------------------
# run() — missing inputs → graceful empty output
# ---------------------------------------------------------------------------

class TestRunMissingInputs:
    def test_all_missing_returns_empty_status(self, tmp_path):
        """When no input files exist, run() returns EMPTY status without raising."""
        _setup_dirs(tmp_path)
        result = run(root=tmp_path, force=True)
        assert result["status"] == "EMPTY"
        assert result["linkage_rows"] == 0
        assert result["matched_pct"] == 0.0

    def test_all_missing_writes_empty_csv(self, tmp_path):
        """When no input files exist, an output CSV with correct headers is still written."""
        _setup_dirs(tmp_path)
        run(root=tmp_path, force=True)
        out = tmp_path / "data" / "linked" / "hud_drgr_financial_linkage.csv"
        assert out.exists(), "Output CSV must be written even for empty run"
        df = pd.read_csv(out, dtype=str)
        assert list(df.columns) == LINKAGE_COLUMNS
        assert len(df) == 0

    def test_missing_orgs_but_contracts_present_still_empty(self, tmp_path):
        """Only responsible_orgs_resolved drives the output; contracts alone don't create rows."""
        _setup_dirs(tmp_path)
        proc_dir = tmp_path / "data" / "staging" / "processed"
        _write_csv(
            proc_dir / "pr_contracts_master.csv",
            [{"recipient_name": "ACME CORP", "recipient_name_normalized": "ACME CORP",
              "obligated_amount": "100000"}],
            ["recipient_name", "recipient_name_normalized", "obligated_amount"],
        )
        result = run(root=tmp_path, force=True)
        assert result["status"] == "EMPTY"
        assert result["linkage_rows"] == 0

    def test_cached_result_returned_when_output_exists(self, tmp_path):
        """If output CSV already exists and force=False, status is CACHED."""
        _setup_dirs(tmp_path)
        out = tmp_path / "data" / "linked" / "hud_drgr_financial_linkage.csv"
        # Write a pre-existing output
        pd.DataFrame(columns=LINKAGE_COLUMNS).to_csv(out, index=False)
        result = run(root=tmp_path, force=False)
        assert result["status"] == "CACHED"


# ---------------------------------------------------------------------------
# run() — with fixture parquets/CSVs → output written correctly
# ---------------------------------------------------------------------------

class TestRunWithFixtures:
    def _orgs_df(self):
        return pd.DataFrame({
            "responsible_org": ["ACME Corporation", "Caribbean Builders LLC", "Unknown Org"],
            "responsible_org_normalized": ["ACME CORPORATION", "CARIBBEAN BUILDERS", "UNKNOWN ORG"],
            "grant_number_list": ["B-17-DG-001", "B-17-DG-002", "B-17-DG-003"],
            "activity_count": [5, 3, 1],
            "total_budget_managed": [1_000_000.0, 500_000.0, 50_000.0],
        })

    def _contracts_df(self):
        return pd.DataFrame({
            "recipient_name": ["ACME Corporation", "Other Vendor Inc"],
            "recipient_name_normalized": ["ACME CORPORATION", "OTHER VENDOR"],
            "obligated_amount": ["1000000", "250000"],
        })

    def test_run_writes_output_csv(self, tmp_path):
        """run() with valid parquet input writes output CSV."""
        _setup_dirs(tmp_path)
        norm_dir = tmp_path / "data" / "normalized"
        proc_dir = tmp_path / "data" / "staging" / "processed"

        pq_write(self._orgs_df(), norm_dir / "hud_drgr_responsible_orgs_resolved.parquet")
        _write_csv(
            proc_dir / "pr_contracts_master.csv",
            self._contracts_df().to_dict("records"),
            list(self._contracts_df().columns),
        )

        result = run(root=tmp_path, force=True)
        assert result["status"] == "OK"
        out = tmp_path / "data" / "linked" / "hud_drgr_financial_linkage.csv"
        assert out.exists()

    def test_run_output_has_correct_columns(self, tmp_path):
        """Output CSV contains exactly LINKAGE_COLUMNS."""
        _setup_dirs(tmp_path)
        norm_dir = tmp_path / "data" / "normalized"
        pq_write(self._orgs_df(), norm_dir / "hud_drgr_responsible_orgs_resolved.parquet")

        run(root=tmp_path, force=True)
        out = tmp_path / "data" / "linked" / "hud_drgr_financial_linkage.csv"
        df = pd.read_csv(out, dtype=str)
        assert list(df.columns) == LINKAGE_COLUMNS

    def test_run_output_row_count_matches_orgs(self, tmp_path):
        """One output row per responsible org."""
        _setup_dirs(tmp_path)
        norm_dir = tmp_path / "data" / "normalized"
        pq_write(self._orgs_df(), norm_dir / "hud_drgr_responsible_orgs_resolved.parquet")

        result = run(root=tmp_path, force=True)
        assert result["linkage_rows"] == len(self._orgs_df())

    def test_run_exact_match_produces_high_confidence(self, tmp_path):
        """An org whose normalized name exactly matches a contract name gets 'exact' confidence."""
        _setup_dirs(tmp_path)
        norm_dir = tmp_path / "data" / "normalized"
        proc_dir = tmp_path / "data" / "staging" / "processed"

        orgs = pd.DataFrame({
            "responsible_org": ["Acme Corporation"],
            "responsible_org_normalized": ["ACME CORPORATION"],
            "grant_number_list": ["B-17-DG-001"],
            "activity_count": [2],
            "total_budget_managed": [500_000.0],
        })
        pq_write(orgs, norm_dir / "hud_drgr_responsible_orgs_resolved.parquet")

        contracts = pd.DataFrame({
            "recipient_name": ["Acme Corporation"],
            "recipient_name_normalized": ["ACME CORPORATION"],
            "obligated_amount": ["750000"],
        })
        _write_csv(
            proc_dir / "pr_contracts_master.csv",
            contracts.to_dict("records"),
            list(contracts.columns),
        )

        run(root=tmp_path, force=True)
        out = tmp_path / "data" / "linked" / "hud_drgr_financial_linkage.csv"
        df = pd.read_csv(out, dtype=str)
        assert df.iloc[0]["link_confidence"] == "exact"
        # matched_entity is taken from the name_col (recipient_name_normalized) value
        assert df.iloc[0]["matched_entity"] == "ACME CORPORATION"

    def test_run_fallback_to_all_awards_when_contracts_missing(self, tmp_path):
        """When pr_contracts_master.csv is absent, falls back to pr_all_awards_master.csv."""
        _setup_dirs(tmp_path)
        norm_dir = tmp_path / "data" / "normalized"
        proc_dir = tmp_path / "data" / "staging" / "processed"

        orgs = pd.DataFrame({
            "responsible_org": ["Island Tech LLC"],
            "responsible_org_normalized": ["ISLAND TECH"],
            "grant_number_list": ["B-17-DG-010"],
            "activity_count": [1],
            "total_budget_managed": [200_000.0],
        })
        pq_write(orgs, norm_dir / "hud_drgr_responsible_orgs_resolved.parquet")

        # Only write pr_all_awards_master.csv
        awards = pd.DataFrame({
            "recipient_name": ["Island Tech LLC"],
            "recipient_name_normalized": ["ISLAND TECH"],
            "obligated_amount": ["200000"],
        })
        _write_csv(
            proc_dir / "pr_all_awards_master.csv",
            awards.to_dict("records"),
            list(awards.columns),
        )

        result = run(root=tmp_path, force=True)
        assert result["status"] == "OK"
        out = tmp_path / "data" / "linked" / "hud_drgr_financial_linkage.csv"
        df = pd.read_csv(out, dtype=str)
        assert df.iloc[0]["link_confidence"] == "exact"

    def test_run_unmatched_org_gets_none_confidence(self, tmp_path):
        """An org with no matching contract gets 'none' confidence and empty matched_entity."""
        _setup_dirs(tmp_path)
        norm_dir = tmp_path / "data" / "normalized"
        proc_dir = tmp_path / "data" / "staging" / "processed"

        orgs = pd.DataFrame({
            "responsible_org": ["Completely Unknown Entity"],
            "responsible_org_normalized": ["COMPLETELY UNKNOWN ENTITY"],
            "grant_number_list": [""],
            "activity_count": [0],
            "total_budget_managed": [0.0],
        })
        pq_write(orgs, norm_dir / "hud_drgr_responsible_orgs_resolved.parquet")

        contracts = pd.DataFrame({
            "recipient_name": ["ACME CORP"],
            "recipient_name_normalized": ["ACME CORP"],
            "obligated_amount": ["100000"],
        })
        _write_csv(
            proc_dir / "pr_contracts_master.csv",
            contracts.to_dict("records"),
            list(contracts.columns),
        )

        run(root=tmp_path, force=True)
        out = tmp_path / "data" / "linked" / "hud_drgr_financial_linkage.csv"
        df = pd.read_csv(out, dtype=str)
        assert df.iloc[0]["link_confidence"] == "none"
        # Empty string is written as empty CSV field, read back as NaN
        val = df.iloc[0]["matched_entity"]
        assert val == "" or pd.isna(val)

    def test_run_matched_pct_reflects_matched_orgs(self, tmp_path):
        """matched_pct in return dict reflects fraction of orgs with non-none confidence."""
        _setup_dirs(tmp_path)
        norm_dir = tmp_path / "data" / "normalized"
        proc_dir = tmp_path / "data" / "staging" / "processed"

        # Use names that don't get corporate-suffix stripped by _normalize_name.
        # "ISLAND BUILDERS" normalizes to "ISLAND BUILDERS" (no suffix to strip).
        orgs = pd.DataFrame({
            "responsible_org": ["Island Builders", "No Match Org"],
            "responsible_org_normalized": ["ISLAND BUILDERS", "NO MATCH ORG XYZZY"],
            "grant_number_list": ["B-001", "B-002"],
            "activity_count": [1, 1],
            "total_budget_managed": [100.0, 200.0],
        })
        pq_write(orgs, norm_dir / "hud_drgr_responsible_orgs_resolved.parquet")

        contracts = pd.DataFrame({
            "recipient_name": ["Island Builders"],
            "recipient_name_normalized": ["ISLAND BUILDERS"],
            "obligated_amount": ["100000"],
        })
        _write_csv(
            proc_dir / "pr_contracts_master.csv",
            contracts.to_dict("records"),
            list(contracts.columns),
        )

        result = run(root=tmp_path, force=True)
        # 1 of 2 orgs matched → 50%
        assert result["matched_pct"] == pytest.approx(50.0, abs=1.0)

    def test_run_with_entity_master_fallback(self, tmp_path):
        """When an org matches entity_master but not contracts, entity info is used."""
        _setup_dirs(tmp_path)
        norm_dir = tmp_path / "data" / "normalized"
        proc_dir = tmp_path / "data" / "staging" / "processed"

        orgs = pd.DataFrame({
            "responsible_org": ["PR Health Corp"],
            "responsible_org_normalized": ["PR HEALTH CORP"],
            "grant_number_list": ["B-17-DG-020"],
            "activity_count": [2],
            "total_budget_managed": [300_000.0],
        })
        pq_write(orgs, norm_dir / "hud_drgr_responsible_orgs_resolved.parquet")

        # Entity master with canonical_name_normalized column
        entity = pd.DataFrame({
            "canonical_name_normalized": ["PR HEALTH CORP"],
            "canonical_name": ["PR Health Corporation"],
        })
        _write_csv(
            proc_dir / "entity_master.csv",
            entity.to_dict("records"),
            list(entity.columns),
        )

        run(root=tmp_path, force=True)
        out = tmp_path / "data" / "linked" / "hud_drgr_financial_linkage.csv"
        df = pd.read_csv(out, dtype=str)
        assert df.iloc[0]["link_confidence"] == "exact"
        assert df.iloc[0]["matched_entity"] == "PR Health Corporation"

    def test_run_force_flag_overwrites_existing_output(self, tmp_path):
        """When force=True, an existing output CSV is overwritten."""
        _setup_dirs(tmp_path)
        norm_dir = tmp_path / "data" / "normalized"
        out = tmp_path / "data" / "linked" / "hud_drgr_financial_linkage.csv"

        # Write a stale output
        pd.DataFrame(columns=LINKAGE_COLUMNS).to_csv(out, index=False)

        orgs = pd.DataFrame({
            "responsible_org": ["Fresh Org"],
            "responsible_org_normalized": ["FRESH ORG"],
            "grant_number_list": ["B-999"],
            "activity_count": [1],
            "total_budget_managed": [100.0],
        })
        pq_write(orgs, norm_dir / "hud_drgr_responsible_orgs_resolved.parquet")

        result = run(root=tmp_path, force=True)
        assert result["status"] == "OK"
        df = pd.read_csv(out, dtype=str)
        assert len(df) == 1
        assert df.iloc[0]["responsible_org"] == "Fresh Org"
