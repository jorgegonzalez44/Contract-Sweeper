"""Tests for scripts/dominance_analysis.py — market concentration analysis."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.dominance_analysis import (
    TOP_N_DEFAULT,
    apply_parent_consolidation,
    compute_geo_concentration,
    compute_hhi_per_agency,
    compute_single_source,
    compute_top_vendors,
    compute_yoy_trends,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _df(*rows) -> pd.DataFrame:
    """Build a minimal master DataFrame from (vendor, agency, amount, fy) tuples."""
    data = [
        {"vendor_name": v, "agency_name": a, "obligated_amount": amt, "fiscal_year": fy}
        for v, a, amt, fy in rows
    ]
    return pd.DataFrame(data)


def _write_master(root: Path, rows: list[dict]) -> Path:
    path = root / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


# ---------------------------------------------------------------------------
# compute_top_vendors
# ---------------------------------------------------------------------------

class TestComputeTopVendors:
    def test_sort_descending(self):
        df = _df(
            ("Vendor A", "Agency X", 500_000, 2022),
            ("Vendor B", "Agency X", 1_000_000, 2022),
            ("Vendor C", "Agency X", 250_000, 2022),
        )
        result = compute_top_vendors(df, top_n=3)
        obligations = result["total_obligation"].tolist()
        assert obligations == sorted(obligations, reverse=True)

    def test_top_n_truncation(self):
        df = _df(*[
            (f"Vendor {i}", "Agency X", 100_000 * i, 2022)
            for i in range(1, 11)
        ])
        result = compute_top_vendors(df, top_n=5)
        assert len(result) == 5

    def test_top_n_larger_than_data(self):
        df = _df(
            ("Vendor A", "Agency X", 100_000, 2022),
            ("Vendor B", "Agency X", 200_000, 2022),
        )
        result = compute_top_vendors(df, top_n=25)
        assert len(result) == 2

    def test_rank_column_starts_at_1(self):
        df = _df(
            ("Vendor A", "Agency X", 100_000, 2022),
            ("Vendor B", "Agency X", 200_000, 2022),
        )
        result = compute_top_vendors(df, top_n=5)
        assert list(result["rank"]) == [1, 2]

    def test_market_share_sums_to_100(self):
        df = _df(
            ("Vendor A", "Agency X", 300_000, 2022),
            ("Vendor B", "Agency X", 700_000, 2022),
        )
        result = compute_top_vendors(df, top_n=5)
        assert sum(result["market_share_pct"]) == pytest.approx(100.0, abs=0.1)

    def test_market_share_pct_values(self):
        df = _df(
            ("Vendor A", "Agency X", 500_000, 2022),
            ("Vendor B", "Agency X", 500_000, 2022),
        )
        result = compute_top_vendors(df, top_n=5)
        assert result["market_share_pct"].tolist() == pytest.approx([50.0, 50.0], abs=0.1)

    def test_custom_col_entity_name(self):
        df = _df(
            ("Vendor A", "Agency X", 100_000, 2022),
        )
        df["entity_name"] = df["vendor_name"]
        result = compute_top_vendors(df, top_n=5, col="entity_name")
        assert "vendor_name" in result.columns
        assert result.iloc[0]["vendor_name"] == "Vendor A"

    def test_aggregates_multiple_rows_per_vendor(self):
        df = _df(
            ("Vendor A", "Agency X", 200_000, 2021),
            ("Vendor A", "Agency Y", 300_000, 2022),
        )
        result = compute_top_vendors(df, top_n=5)
        assert len(result) == 1
        assert result.iloc[0]["total_obligation"] == 500_000


# ---------------------------------------------------------------------------
# compute_hhi_per_agency
# ---------------------------------------------------------------------------

class TestComputeHHIPerAgency:
    def test_monopoly_hhi_equals_10000(self):
        df = _df(
            ("Only Vendor", "Agency X", 1_000_000, 2022),
        )
        result = compute_hhi_per_agency(df)
        row = result[result["agency_name"] == "Agency X"].iloc[0]
        assert row["hhi"] == pytest.approx(10_000.0, abs=1.0)

    def test_duopoly_50_50_hhi_equals_5000(self):
        df = _df(
            ("Vendor A", "Agency X", 500_000, 2022),
            ("Vendor B", "Agency X", 500_000, 2022),
        )
        result = compute_hhi_per_agency(df)
        row = result[result["agency_name"] == "Agency X"].iloc[0]
        assert row["hhi"] == pytest.approx(5_000.0, abs=1.0)

    def test_uniform_4_vendor_hhi_equals_2500(self):
        df = _df(*[
            (f"Vendor {i}", "Agency X", 250_000, 2022)
            for i in range(4)
        ])
        result = compute_hhi_per_agency(df)
        row = result[result["agency_name"] == "Agency X"].iloc[0]
        assert row["hhi"] == pytest.approx(2_500.0, abs=1.0)

    def test_uniform_10_vendor_hhi_equals_1000(self):
        df = _df(*[
            (f"Vendor {i}", "Agency X", 100_000, 2022)
            for i in range(10)
        ])
        result = compute_hhi_per_agency(df)
        row = result[result["agency_name"] == "Agency X"].iloc[0]
        assert row["hhi"] == pytest.approx(1_000.0, abs=1.0)

    def test_concentration_labels(self):
        # Monopoly → HIGH (HHI=10000), 4 equal → MODERATE (HHI=2500), 10 equal → LOW (HHI=1000)
        mono_df = _df(("V", "Mono", 1_000_000, 2022))
        four_df = _df(*[(f"V{i}", "Four", 250_000, 2022) for i in range(4)])
        ten_df  = _df(*[(f"V{i}", "Ten",  100_000, 2022) for i in range(10)])

        all_df = pd.concat([mono_df, four_df, ten_df], ignore_index=True)
        result = compute_hhi_per_agency(all_df)

        def label(agency):
            return result[result["agency_name"] == agency].iloc[0]["concentration"]

        assert label("Mono") == "HIGH"
        assert label("Four") == "MODERATE"
        assert label("Ten")  == "LOW"

    def test_sorted_descending_by_hhi(self):
        df = pd.concat([
            _df(("V", "Agency Low", 100_000, 2022), ("V2", "Agency Low", 100_000, 2022)),
            _df(("Only V", "Agency High", 1_000_000, 2022)),
        ], ignore_index=True)
        result = compute_hhi_per_agency(df)
        hhis = result["hhi"].tolist()
        assert hhis == sorted(hhis, reverse=True)

    def test_excludes_zero_total_agencies(self):
        df = _df(("Vendor A", "Empty Agency", 0, 2022))
        result = compute_hhi_per_agency(df)
        assert result.empty

    def test_multiple_agencies_independent(self):
        df = _df(
            ("V1", "Agency A", 1_000_000, 2022),
            ("V1", "Agency B", 500_000, 2022),
            ("V2", "Agency B", 500_000, 2022),
        )
        result = compute_hhi_per_agency(df)
        hhi_a = result[result["agency_name"] == "Agency A"].iloc[0]["hhi"]
        hhi_b = result[result["agency_name"] == "Agency B"].iloc[0]["hhi"]
        assert hhi_a == pytest.approx(10_000.0, abs=1.0)
        assert hhi_b == pytest.approx(5_000.0, abs=1.0)


# ---------------------------------------------------------------------------
# apply_parent_consolidation
# ---------------------------------------------------------------------------

class TestApplyParentConsolidation:
    def _hier(self, vendor: str, parent: str) -> pd.DataFrame:
        return pd.DataFrame([{"vendor_name": vendor, "parent_name": parent}])

    def test_maps_vendor_to_parent(self):
        df = _df(("Vendor A", "Agency X", 100_000, 2022))
        hierarchy = self._hier("Vendor A", "Parent Corp")
        result = apply_parent_consolidation(df, hierarchy)
        assert result.iloc[0]["entity_name"] == "Parent Corp"

    def test_no_hierarchy_match_keeps_original(self):
        df = _df(("Vendor B", "Agency X", 100_000, 2022))
        hierarchy = self._hier("Vendor A", "Parent Corp")
        result = apply_parent_consolidation(df, hierarchy)
        assert result.iloc[0]["entity_name"] == "Vendor B"

    def test_does_not_mutate_original_df(self):
        df = _df(("Vendor A", "Agency X", 100_000, 2022))
        original_cols = set(df.columns)
        hierarchy = self._hier("Vendor A", "Parent Corp")
        apply_parent_consolidation(df, hierarchy)
        assert set(df.columns) == original_cols

    def test_empty_parent_name_keeps_vendor(self):
        df = _df(("Vendor A", "Agency X", 100_000, 2022))
        hierarchy = pd.DataFrame([{"vendor_name": "Vendor A", "parent_name": ""}])
        result = apply_parent_consolidation(df, hierarchy)
        assert result.iloc[0]["entity_name"] == "Vendor A"


# ---------------------------------------------------------------------------
# compute_yoy_trends
# ---------------------------------------------------------------------------

class TestComputeYoYTrends:
    def test_returns_dataframe_with_fiscal_year_column(self):
        df = _df(
            ("Vendor A", "Agency X", 100_000, 2021),
            ("Vendor A", "Agency X", 150_000, 2022),
        )
        result = compute_yoy_trends(df, top_n=1)
        assert "fiscal_year" in result.columns

    def test_pivot_contains_top_vendor(self):
        df = _df(
            ("Big Vendor", "Agency X", 1_000_000, 2021),
            ("Small Vendor", "Agency X", 10_000, 2021),
        )
        result = compute_yoy_trends(df, top_n=1)
        assert "Big Vendor" in result.columns

    def test_missing_year_filled_with_zero(self):
        # Vendor A only present in 2021, not 2022
        df = _df(
            ("Vendor A", "Agency X", 100_000, 2021),
            ("Vendor B", "Agency X", 200_000, 2022),
        )
        result = compute_yoy_trends(df, top_n=2)
        fy_2022_row = result[result["fiscal_year"] == 2022]
        if "Vendor A" in result.columns and len(fy_2022_row) > 0:
            assert fy_2022_row.iloc[0]["Vendor A"] == 0

    def test_top_n_limits_vendor_columns(self):
        df = _df(*[
            (f"Vendor {i}", "Agency X", 100_000 * (10 - i), 2022)
            for i in range(10)
        ])
        result = compute_yoy_trends(df, top_n=3)
        vendor_cols = [c for c in result.columns if c != "fiscal_year"]
        assert len(vendor_cols) == 3


# ---------------------------------------------------------------------------
# compute_single_source
# ---------------------------------------------------------------------------

class TestComputeSingleSource:
    def test_single_agency_vendor_categorized_correctly(self):
        df = _df(
            ("Vendor A", "Agency X", 100_000, 2022),
            ("Vendor A", "Agency X", 200_000, 2022),
        )
        result = compute_single_source(df)
        row = result[result["vendor_name"] == "Vendor A"].iloc[0]
        assert row["category"] == "single_agency"
        assert row["agency_count"] == 1

    def test_few_agencies_category(self):
        df = _df(
            ("Vendor B", "Agency X", 100_000, 2022),
            ("Vendor B", "Agency Y", 100_000, 2022),
            ("Vendor B", "Agency Z", 100_000, 2022),
        )
        result = compute_single_source(df)
        row = result[result["vendor_name"] == "Vendor B"].iloc[0]
        assert row["category"] == "few_agencies"

    def test_multi_agency_category(self):
        df = _df(*[
            ("Vendor C", f"Agency {i}", 100_000, 2022)
            for i in range(4)
        ])
        result = compute_single_source(df)
        row = result[result["vendor_name"] == "Vendor C"].iloc[0]
        assert row["category"] == "multi_agency"

    def test_sorted_descending_by_agency_count(self):
        df = _df(
            ("Multi Vendor", "Agency A", 100_000, 2022),
            ("Multi Vendor", "Agency B", 100_000, 2022),
            ("Multi Vendor", "Agency C", 100_000, 2022),
            ("Multi Vendor", "Agency D", 100_000, 2022),
            ("Single Vendor", "Agency A", 100_000, 2022),
        )
        result = compute_single_source(df)
        counts = result["agency_count"].tolist()
        assert counts == sorted(counts, reverse=True)


# ---------------------------------------------------------------------------
# compute_geo_concentration
# ---------------------------------------------------------------------------

class TestComputeGeoConcentration:
    def test_returns_empty_when_no_pop_state_column(self):
        df = _df(("Vendor A", "Agency X", 100_000, 2022))
        result = compute_geo_concentration(df)
        assert result.empty

    def test_aggregates_by_state(self):
        df = _df(
            ("Vendor A", "Agency X", 300_000, 2022),
            ("Vendor B", "Agency X", 700_000, 2022),
        )
        df["pop_state"] = ["PR", "PR"]
        result = compute_geo_concentration(df)
        assert len(result) == 1
        assert result.iloc[0]["total_obligation"] == 1_000_000

    def test_share_sums_to_100(self):
        df = _df(
            ("Vendor A", "Agency X", 300_000, 2022),
            ("Vendor B", "Agency Y", 700_000, 2022),
        )
        df["pop_state"] = ["PR", "TX"]
        result = compute_geo_concentration(df)
        assert result["share_pct"].sum() == pytest.approx(100.0, abs=0.1)

    def test_sorted_descending_by_obligation(self):
        df = _df(
            ("Vendor A", "Agency X", 300_000, 2022),
            ("Vendor B", "Agency Y", 700_000, 2022),
        )
        df["pop_state"] = ["TX", "PR"]
        result = compute_geo_concentration(df)
        assert result.iloc[0]["pop_state"] == "PR"


# ---------------------------------------------------------------------------
# run() integration
# ---------------------------------------------------------------------------

class TestRunIntegration:
    def _master_rows(self) -> list[dict]:
        return [
            {"vendor_name": "Vendor Alpha", "agency_name": "Agency One",
             "obligated_amount": "1000000", "fiscal_year": "2022"},
            {"vendor_name": "Vendor Beta", "agency_name": "Agency One",
             "obligated_amount": "500000", "fiscal_year": "2021"},
            {"vendor_name": "Vendor Alpha", "agency_name": "Agency Two",
             "obligated_amount": "250000", "fiscal_year": "2022"},
        ]

    def test_run_writes_summary_json(self, tmp_path):
        _write_master(tmp_path, self._master_rows())
        result = run(root=tmp_path, top_n=5)
        summary_path = tmp_path / "data" / "staging" / "processed" / "dominance_summary.json"
        assert summary_path.exists()
        data = json.loads(summary_path.read_text())
        assert "total_rows" in data
        assert "unique_vendors" in data
        assert "total_obligation_usd" in data

    def test_run_writes_top_vendors_csv(self, tmp_path):
        _write_master(tmp_path, self._master_rows())
        run(root=tmp_path, top_n=5)
        csv_path = tmp_path / "data" / "staging" / "processed" / "dominance_top_vendors_raw.csv"
        assert csv_path.exists()
        df = pd.read_csv(csv_path)
        assert "vendor_name" in df.columns
        assert "total_obligation" in df.columns

    def test_run_writes_hhi_csv(self, tmp_path):
        _write_master(tmp_path, self._master_rows())
        run(root=tmp_path, top_n=5)
        hhi_path = tmp_path / "data" / "staging" / "processed" / "dominance_hhi_per_agency.csv"
        assert hhi_path.exists()

    def test_run_summary_vendor_count(self, tmp_path):
        _write_master(tmp_path, self._master_rows())
        result = run(root=tmp_path, top_n=5)
        assert result["unique_vendors"] == 2

    def test_run_top_vendor_is_highest_obligation(self, tmp_path):
        _write_master(tmp_path, self._master_rows())
        result = run(root=tmp_path, top_n=5)
        # Vendor Alpha: 1000000 + 250000 = 1250000; Vendor Beta: 500000
        assert result["top_vendor"] == "Vendor Alpha"
        assert result["top_vendor_obligation"] == pytest.approx(1_250_000, abs=1)

    def test_run_without_hierarchy_skips_consolidated(self, tmp_path):
        _write_master(tmp_path, self._master_rows())
        result = run(root=tmp_path, top_n=5)
        assert "top_vendors_consolidated" not in result.get("outputs", {})

    def test_run_uses_unified_schema_when_no_vendor_name(self, tmp_path):
        rows = [
            {"recipient_name": "Corp A", "awarding_agency": "Dept X",
             "obligated_amount": "750000", "fiscal_year": "2022"},
            {"recipient_name": "Corp B", "awarding_agency": "Dept X",
             "obligated_amount": "250000", "fiscal_year": "2022"},
        ]
        _write_master(tmp_path, rows)
        result = run(root=tmp_path, top_n=5)
        assert result["top_vendor"] == "Corp A"
