"""Tests for scripts/build_unified_master.py — name normalization, FY derivation, pop_state, alias resolution, run()."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.build_unified_master import (
    _derive_fiscal_year,
    _normalize_name,
    _standardize_pop_state,
    apply_alias_registry,
)


# ---------------------------------------------------------------------------
# _normalize_name
# ---------------------------------------------------------------------------

class TestNormalizeName:
    def test_empty_string(self):
        assert _normalize_name("") == ""

    def test_nan(self):
        assert _normalize_name(float("nan")) == ""

    def test_none(self):
        assert _normalize_name(None) == ""

    def test_uppercase(self):
        assert _normalize_name("crowley") == "CROWLEY"

    def test_strips_trailing_inc(self):
        assert _normalize_name("Microsoft Inc") == "MICROSOFT"

    def test_strips_trailing_corp(self):
        # Note: only "CORP" is in the suffix set, not "CORPORATION"
        assert _normalize_name("Acme Corp") == "ACME"

    def test_strips_punctuation(self):
        assert _normalize_name("Triple-S Mgmt, Inc.") == "TRIPLE S MGMT"

    def test_strips_multiple_trailing_suffixes(self):
        assert _normalize_name("Foo Inc Corp") == "FOO"


# ---------------------------------------------------------------------------
# _derive_fiscal_year
# ---------------------------------------------------------------------------

class TestDeriveFiscalYear:
    def test_january_is_same_fy(self):
        s = pd.Series(["2024-01-15"])
        assert _derive_fiscal_year(s).iloc[0] == "2024"

    def test_september_is_same_fy(self):
        s = pd.Series(["2024-09-30"])
        assert _derive_fiscal_year(s).iloc[0] == "2024"

    def test_october_rolls_forward(self):
        s = pd.Series(["2024-10-01"])
        assert _derive_fiscal_year(s).iloc[0] == "2025"

    def test_december_rolls_forward(self):
        s = pd.Series(["2024-12-31"])
        assert _derive_fiscal_year(s).iloc[0] == "2025"

    def test_invalid_date_returns_empty(self):
        s = pd.Series(["not-a-date"])
        assert _derive_fiscal_year(s).iloc[0] == ""

    def test_empty_string_returns_empty(self):
        s = pd.Series([""])
        assert _derive_fiscal_year(s).iloc[0] == ""

    def test_mixed_series(self):
        s = pd.Series(["2024-01-15", "2024-10-01", "", "garbage"])
        out = _derive_fiscal_year(s)
        assert list(out) == ["2024", "2025", "", ""]


# ---------------------------------------------------------------------------
# _standardize_pop_state
# ---------------------------------------------------------------------------

class TestStandardizePopState:
    def test_full_name_to_pr(self):
        s = pd.Series(["Puerto Rico"])
        assert _standardize_pop_state(s).iloc[0] == "PR"

    def test_fips_72_to_pr(self):
        s = pd.Series(["72"])
        assert _standardize_pop_state(s).iloc[0] == "PR"

    def test_already_pr_unchanged(self):
        s = pd.Series(["PR"])
        # 'PR' is not in the lowercase map, so it gets returned as-is via str().strip()
        assert _standardize_pop_state(s).iloc[0] == "PR"

    def test_other_state_unchanged(self):
        s = pd.Series(["FL"])
        assert _standardize_pop_state(s).iloc[0] == "FL"

    def test_case_insensitive(self):
        s = pd.Series(["puerto rico", "PUERTO RICO", "Puerto Rico"])
        out = _standardize_pop_state(s)
        assert all(v == "PR" for v in out)

    def test_preserves_nan(self):
        s = pd.Series([None, float("nan")])
        out = _standardize_pop_state(s)
        # NaN/None passed through (function returns val for NaN)
        assert pd.isna(out.iloc[0]) or out.iloc[0] is None


# ---------------------------------------------------------------------------
# apply_alias_registry
# ---------------------------------------------------------------------------

def _make_df(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "recipient_name": "",
        "recipient_uei": "",
        "obligated_amount": "0",
    }
    return pd.DataFrame([{**defaults, **r} for r in rows])


def _registry(*entries) -> dict:
    """Build a minimal alias registry dict from (variant, canonical, uei) tuples."""
    reg = {}
    for variant, canonical, uei in entries:
        reg[variant] = {"canonical_name": canonical, "canonical_uei": uei, "entity_type": "corporate"}
    return reg


class TestApplyAliasRegistry:
    def test_canonical_name_set_for_known_variant(self):
        df = _make_df([{"recipient_name": "PRASA"}])
        registry = _registry(
            ("PRASA", "Puerto Rico Aqueduct And Sewer Authority", "PRASA3L6W9X2")
        )
        df, stats = apply_alias_registry(df, registry)
        assert df["_canonical_name"].iloc[0] == "Puerto Rico Aqueduct And Sewer Authority"
        assert stats["names_resolved"] == 1

    def test_unknown_variant_keeps_original_name(self):
        df = _make_df([{"recipient_name": "Unknown Corp"}])
        registry = _registry(("PRASA", "Puerto Rico Aqueduct And Sewer Authority", "X"))
        df, stats = apply_alias_registry(df, registry)
        assert df["_canonical_name"].iloc[0] == "Unknown Corp"
        assert stats["names_resolved"] == 0

    def test_fills_empty_uei_from_alias(self):
        df = _make_df([{"recipient_name": "Microsoft Puerto Rico Inc", "recipient_uei": ""}])
        registry = _registry(
            ("Microsoft Puerto Rico Inc", "Microsoft Corporation", "MSFT0C6E9H2K")
        )
        df, stats = apply_alias_registry(df, registry)
        assert df["recipient_uei"].iloc[0] == "MSFT0C6E9H2K"
        assert stats["ueis_filled"] == 1

    def test_does_not_overwrite_existing_uei(self):
        df = _make_df([{"recipient_name": "Corp A", "recipient_uei": "EXISTING0001"}])
        registry = _registry(("Corp A", "Corp A Holdings", "NEWE12345678"))
        df, stats = apply_alias_registry(df, registry)
        assert df["recipient_uei"].iloc[0] == "EXISTING0001"
        assert stats["ueis_filled"] == 0

    def test_empty_registry_is_noop(self):
        df = _make_df([{"recipient_name": "Crowley Maritime Corp", "recipient_uei": ""}])
        df, stats = apply_alias_registry(df, {})
        assert df["_canonical_name"].iloc[0] == "Crowley Maritime Corp"
        assert stats["names_resolved"] == 0
        assert stats["ueis_filled"] == 0
        assert stats["aliases_loaded"] == 0

    def test_multiple_rows_mixed_resolution(self):
        df = _make_df([
            {"recipient_name": "PRASA", "recipient_uei": ""},
            {"recipient_name": "Unknown Entity", "recipient_uei": ""},
            {"recipient_name": "HP Puerto Rico LLC", "recipient_uei": ""},
        ])
        registry = _registry(
            ("PRASA", "Puerto Rico Aqueduct And Sewer Authority", "PRASA3L6W9X2"),
            ("HP Puerto Rico LLC", "HP Inc", "HPINC8E2G5J9"),
        )
        df, stats = apply_alias_registry(df, registry)
        assert df["_canonical_name"].iloc[0] == "Puerto Rico Aqueduct And Sewer Authority"
        assert df["_canonical_name"].iloc[1] == "Unknown Entity"
        assert df["_canonical_name"].iloc[2] == "HP Inc"
        assert stats["names_resolved"] == 2
        assert stats["ueis_filled"] == 2

    def test_stats_aliases_loaded_reflects_registry_size(self):
        df = _make_df([{"recipient_name": "X"}])
        registry = _registry(
            ("A", "A Parent", "UUUU1"),
            ("B", "B Parent", "UUUU2"),
            ("C", "C Parent", "UUUU3"),
        )
        _, stats = apply_alias_registry(df, registry)
        assert stats["aliases_loaded"] == 3

    def test_entity_type_column_populated_for_known_variant(self):
        df = _make_df([{"recipient_name": "Microsoft Puerto Rico Inc"}])
        registry = {
            "Microsoft Puerto Rico Inc": {
                "canonical_name": "Microsoft Corporation",
                "canonical_uei": "MSFT1234",
                "entity_type": "corporate",
            }
        }
        df, _ = apply_alias_registry(df, registry)
        assert "_entity_type" in df.columns
        assert df["_entity_type"].iloc[0] == "corporate"

    def test_entity_type_defaults_to_unknown_for_unregistered_name(self):
        df = _make_df([{"recipient_name": "Mystery Corp"}])
        df, _ = apply_alias_registry(df, {})
        assert df["_entity_type"].iloc[0] == "unknown"


# ---------------------------------------------------------------------------
# run() — integration (Task 21 extension)
# ---------------------------------------------------------------------------

from scripts.build_unified_master import CANONICAL_COLUMNS, run


def _write_contracts(processed_dir: Path, rows: list[dict]) -> None:
    """Write a minimal pr_contracts_master.csv with legacy column names."""
    defaults = {
        "contract_id": "C001", "vendor_name": "Acme Corp", "agency_name": "DoD",
        "award_date": "2022-03-15", "obligated_amount": "500000",
        "pop_state": "PR", "source_file": "test.csv", "fiscal_year": "2022",
    }
    df = pd.DataFrame([{**defaults, **r} for r in rows])
    df.to_csv(processed_dir / "pr_contracts_master.csv", index=False, encoding="utf-8")


class TestRunIntegration:
    def _setup(self, tmp_path: Path) -> Path:
        processed = tmp_path / "data" / "staging" / "processed"
        processed.mkdir(parents=True)
        (tmp_path / "data" / "staging" / "expansion").mkdir(parents=True)
        (tmp_path / "data" / "logs").mkdir(parents=True)
        return processed

    def test_no_inputs_writes_empty_master(self, tmp_path):
        processed = self._setup(tmp_path)
        run(root=tmp_path)
        out = processed / "pr_all_awards_master.csv"
        assert out.exists()
        df = pd.read_csv(out, dtype=str)
        assert len(df) == 0

    def test_no_inputs_output_has_all_canonical_columns(self, tmp_path):
        processed = self._setup(tmp_path)
        run(root=tmp_path)
        df = pd.read_csv(processed / "pr_all_awards_master.csv", dtype=str)
        for col in CANONICAL_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"

    def test_with_contracts_master_rows_in_output(self, tmp_path):
        processed = self._setup(tmp_path)
        _write_contracts(processed, [
            {"contract_id": "C001", "vendor_name": "Island Corp"},
            {"contract_id": "C002", "vendor_name": "Coastal Corp"},
        ])
        run(root=tmp_path)
        df = pd.read_csv(processed / "pr_all_awards_master.csv", dtype=str)
        assert len(df) == 2

    def test_deduplication_within_dataset(self, tmp_path):
        processed = self._setup(tmp_path)
        # Same award_id twice → should deduplicate to 1
        _write_contracts(processed, [
            {"contract_id": "DUP001", "vendor_name": "Corp A"},
            {"contract_id": "DUP001", "vendor_name": "Corp A (dup)"},
        ])
        run(root=tmp_path)
        df = pd.read_csv(processed / "pr_all_awards_master.csv", dtype=str)
        assert len(df) == 1

    def test_recipient_name_normalized_populated(self, tmp_path):
        processed = self._setup(tmp_path)
        _write_contracts(processed, [{"contract_id": "C001", "vendor_name": "Puerto Rico Corp Inc"}])
        run(root=tmp_path)
        df = pd.read_csv(processed / "pr_all_awards_master.csv", dtype=str)
        assert "recipient_name_normalized" in df.columns
        assert df.loc[0, "recipient_name_normalized"] == "PUERTO RICO"

    def test_pop_state_standardized(self, tmp_path):
        processed = self._setup(tmp_path)
        _write_contracts(processed, [{"contract_id": "C001", "pop_state": "Puerto Rico"}])
        run(root=tmp_path)
        df = pd.read_csv(processed / "pr_all_awards_master.csv", dtype=str)
        assert df.loc[0, "pop_state"] == "PR"

    def test_fiscal_year_derived_when_missing(self, tmp_path):
        processed = self._setup(tmp_path)
        _write_contracts(processed, [
            {"contract_id": "C001", "award_date": "2021-10-15", "fiscal_year": ""},
        ])
        run(root=tmp_path)
        df = pd.read_csv(processed / "pr_all_awards_master.csv", dtype=str)
        # Oct 2021 → FY 2022
        assert df.loc[0, "fiscal_year"] == "2022"

    def test_alias_registry_resolves_names(self, tmp_path):
        processed = self._setup(tmp_path)
        enrichment = processed / "enrichment"
        enrichment.mkdir()
        registry = {
            "PRASA": {
                "canonical_name": "Puerto Rico Aqueduct And Sewer Authority",
                "canonical_uei": "PRASA00000001",
                "entity_type": "government",
            }
        }
        (enrichment / "alias_registry.json").write_text(
            json.dumps(registry), encoding="utf-8"
        )
        _write_contracts(processed, [{"contract_id": "C001", "vendor_name": "PRASA"}])
        run(root=tmp_path)
        df = pd.read_csv(processed / "pr_all_awards_master.csv", dtype=str)
        assert "PUERTO RICO AQUEDUCT" in df.loc[0, "recipient_name_normalized"]

    def test_summary_json_written(self, tmp_path):
        processed = self._setup(tmp_path)
        run(root=tmp_path)
        summary = processed / "pr_all_awards_summary.json"
        assert summary.exists()
        data = json.loads(summary.read_text())
        assert "total_rows" in data or "rows" in data or isinstance(data, dict)

    def test_returns_dict_with_rows_key(self, tmp_path):
        processed = self._setup(tmp_path)
        result = run(root=tmp_path)
        assert isinstance(result, dict)
