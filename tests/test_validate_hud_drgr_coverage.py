"""Tests for scripts/validate_hud_drgr_coverage.py — HUD DRGR coverage validation."""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.parquet_utils import pq_write
from scripts.validate_hud_drgr_coverage import (
    RESOLUTION_THRESHOLD,
    GAP_COLUMNS,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_activities(tmp_path, rows):
    """Write a hud_drgr_activities parquet fixture under tmp_path."""
    norm_dir = tmp_path / "data" / "normalized"
    norm_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    pq_write(df, norm_dir / "hud_drgr_activities.parquet")
    return df


def _make_orgs(tmp_path, rows):
    """Write a hud_drgr_responsible_orgs_resolved parquet fixture."""
    norm_dir = tmp_path / "data" / "normalized"
    norm_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    pq_write(df, norm_dir / "hud_drgr_responsible_orgs_resolved.parquet")
    return df


def _make_linkage(tmp_path, rows):
    """Write a hud_drgr_financial_linkage CSV fixture."""
    linked_dir = tmp_path / "data" / "linked"
    linked_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(linked_dir / "hud_drgr_financial_linkage.csv", index=False, encoding="utf-8")
    return df


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_resolution_threshold_value(self):
        """RESOLUTION_THRESHOLD should be 0.90 (90%)."""
        assert RESOLUTION_THRESHOLD == 0.90

    def test_gap_columns_present(self):
        """GAP_COLUMNS should contain the required column names."""
        required = {"activity_id", "grant_number", "activity_name",
                    "responsible_org", "total_budget", "gap_reason"}
        assert required.issubset(set(GAP_COLUMNS))

    def test_gap_columns_count(self):
        assert len(GAP_COLUMNS) == 6


# ---------------------------------------------------------------------------
# run() — missing inputs (graceful, no exception)
# ---------------------------------------------------------------------------

class TestRunMissingInputs:
    def test_no_inputs_returns_dict(self, tmp_path):
        """run() with no input files must return a dict, not raise."""
        result = run(root=tmp_path)
        assert isinstance(result, dict)

    def test_no_inputs_status_ok(self, tmp_path):
        """Even with missing inputs the status should be OK (empty data processed)."""
        result = run(root=tmp_path)
        assert result["status"] == "OK"

    def test_no_inputs_total_activities_zero(self, tmp_path):
        result = run(root=tmp_path)
        assert result["total_activities"] == 0

    def test_no_inputs_writes_gap_report(self, tmp_path):
        """run() must write a gap_report CSV even when inputs are absent."""
        run(root=tmp_path)
        gap_path = tmp_path / "data" / "validation" / "hud_drgr_gap_report.csv"
        assert gap_path.exists(), "gap report CSV was not created"

    def test_no_inputs_writes_unlinked_report(self, tmp_path):
        """run() must write an unlinked_activities CSV even when inputs are absent."""
        run(root=tmp_path)
        unlinked_path = tmp_path / "data" / "review" / "hud_drgr_unlinked_activities.csv"
        assert unlinked_path.exists(), "unlinked activities CSV was not created"

    def test_no_inputs_gap_report_has_correct_columns(self, tmp_path):
        run(root=tmp_path)
        gap_path = tmp_path / "data" / "validation" / "hud_drgr_gap_report.csv"
        df = pd.read_csv(gap_path)
        for col in GAP_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"

    def test_no_inputs_resolved_pct_zero(self, tmp_path):
        result = run(root=tmp_path)
        assert result["resolved_pct"] == 0.0

    def test_cached_skips_when_output_exists(self, tmp_path):
        """Second run() without force=True returns CACHED status."""
        run(root=tmp_path)
        result2 = run(root=tmp_path)
        assert result2["status"] == "CACHED"

    def test_force_reruns_when_output_exists(self, tmp_path):
        """run(force=True) overwrites existing outputs and returns OK."""
        run(root=tmp_path)
        result2 = run(root=tmp_path, force=True)
        assert result2["status"] == "OK"


# ---------------------------------------------------------------------------
# run() — with fixture parquets
# ---------------------------------------------------------------------------

class TestRunWithFixtures:
    def _base_activities(self):
        return [
            {
                "activity_id": "ACT-001",
                "grant_number": "GR-001",
                "activity_name": "Activity One",
                "responsible_org": "Org A",
                "responsible_org_normalized": "org_a",
                "total_budget": "1000000",
            },
            {
                "activity_id": "ACT-002",
                "grant_number": "GR-002",
                "activity_name": "Activity Two",
                "responsible_org": "Org B",
                "responsible_org_normalized": "org_b",
                "total_budget": "200000",
            },
            {
                "activity_id": "ACT-003",
                "grant_number": "GR-003",
                "activity_name": "Activity Three",
                "responsible_org": "",
                "responsible_org_normalized": "",
                "total_budget": "50000",
            },
        ]

    def test_total_activities_counted(self, tmp_path):
        _make_activities(tmp_path, self._base_activities())
        result = run(root=tmp_path)
        assert result["total_activities"] == 3

    def test_gap_report_includes_no_org_row(self, tmp_path):
        """Activity with empty responsible_org should appear in gap report."""
        _make_activities(tmp_path, self._base_activities())
        result = run(root=tmp_path)
        gap_path = tmp_path / "data" / "validation" / "hud_drgr_gap_report.csv"
        df = pd.read_csv(gap_path)
        no_org = df[df["gap_reason"] == "no_responsible_org"]
        assert len(no_org) >= 1

    def test_gap_report_unlinked_org_reason(self, tmp_path):
        """Activity whose normalized org is not in linkage gets 'org_not_linked_to_contract'."""
        _make_activities(tmp_path, self._base_activities())
        # Linkage only covers org_a
        _make_linkage(tmp_path, [
            {"responsible_org_normalized": "org_a", "link_confidence": "high"},
        ])
        result = run(root=tmp_path, force=True)
        gap_path = tmp_path / "data" / "validation" / "hud_drgr_gap_report.csv"
        df = pd.read_csv(gap_path)
        unlinked = df[df["gap_reason"] == "org_not_linked_to_contract"]
        assert len(unlinked) >= 1

    def test_resolved_pct_computed_from_linkage(self, tmp_path):
        """resolved_pct reflects proportion of linkage rows with confidence != 'none'."""
        _make_activities(tmp_path, self._base_activities())
        _make_linkage(tmp_path, [
            {"responsible_org_normalized": "org_a", "link_confidence": "high"},
            {"responsible_org_normalized": "org_b", "link_confidence": "none"},
        ])
        result = run(root=tmp_path)
        # 1 of 2 rows resolved → 50 %
        assert result["resolved_pct"] == 50.0

    def test_coverage_pass_true_when_above_threshold(self, tmp_path):
        """coverage_pass is True when resolved_pct >= 90."""
        _make_activities(tmp_path, self._base_activities())
        _make_linkage(tmp_path, [
            {"responsible_org_normalized": "org_a", "link_confidence": "high"},
            {"responsible_org_normalized": "org_b", "link_confidence": "high"},
            {"responsible_org_normalized": "org_c", "link_confidence": "high"},
            {"responsible_org_normalized": "org_d", "link_confidence": "high"},
            {"responsible_org_normalized": "org_e", "link_confidence": "high"},
            {"responsible_org_normalized": "org_f", "link_confidence": "high"},
            {"responsible_org_normalized": "org_g", "link_confidence": "high"},
            {"responsible_org_normalized": "org_h", "link_confidence": "high"},
            {"responsible_org_normalized": "org_i", "link_confidence": "high"},
            {"responsible_org_normalized": "org_j", "link_confidence": "none"},
        ])
        result = run(root=tmp_path)
        # 9/10 = 90% → PASS
        assert result["coverage_pass"]

    def test_coverage_pass_false_when_below_threshold(self, tmp_path):
        """coverage_pass is False when resolved_pct < 90."""
        _make_activities(tmp_path, self._base_activities())
        _make_linkage(tmp_path, [
            {"responsible_org_normalized": "org_a", "link_confidence": "high"},
            {"responsible_org_normalized": "org_b", "link_confidence": "none"},
        ])
        result = run(root=tmp_path)
        assert not result["coverage_pass"]

    def test_high_value_unlinked_activity_appears_in_review(self, tmp_path):
        """High-value (>=500k) unlinked activities appear in hud_drgr_unlinked_activities."""
        activities = [
            {
                "activity_id": "ACT-HV",
                "grant_number": "GR-HV",
                "activity_name": "Big Project",
                "responsible_org": "Unknown Org",
                "responsible_org_normalized": "unknown_org",
                "total_budget": "750000",
            },
        ]
        _make_activities(tmp_path, activities)
        # Linkage has no entry for unknown_org
        _make_linkage(tmp_path, [
            {"responsible_org_normalized": "other_org", "link_confidence": "high"},
        ])
        result = run(root=tmp_path)
        unlinked_path = tmp_path / "data" / "review" / "hud_drgr_unlinked_activities.csv"
        df = pd.read_csv(unlinked_path)
        assert len(df) >= 1

    def test_low_value_unlinked_activity_not_in_review(self, tmp_path):
        """Low-value (<500k) activities that are linked should NOT be in unlinked report."""
        activities = [
            {
                "activity_id": "ACT-LV",
                "grant_number": "GR-LV",
                "activity_name": "Small Project",
                "responsible_org": "Org A",
                "responsible_org_normalized": "org_a",
                "total_budget": "100000",
            },
        ]
        _make_activities(tmp_path, activities)
        _make_linkage(tmp_path, [
            {"responsible_org_normalized": "org_a", "link_confidence": "high"},
        ])
        result = run(root=tmp_path)
        unlinked_path = tmp_path / "data" / "review" / "hud_drgr_unlinked_activities.csv"
        df = pd.read_csv(unlinked_path)
        # org_a is linked and budget is below HIGH_VALUE → should not be in unlinked
        act_ids = df["activity_id"].tolist() if "activity_id" in df.columns else []
        assert "ACT-LV" not in act_ids

    def test_return_dict_has_required_keys(self, tmp_path):
        _make_activities(tmp_path, self._base_activities())
        result = run(root=tmp_path)
        for key in ("total_activities", "resolved_pct", "coverage_pass",
                    "unlinked_count", "status"):
            assert key in result, f"Missing key: {key}"

    def test_gap_report_all_columns_present(self, tmp_path):
        _make_activities(tmp_path, self._base_activities())
        run(root=tmp_path)
        gap_path = tmp_path / "data" / "validation" / "hud_drgr_gap_report.csv"
        df = pd.read_csv(gap_path)
        for col in GAP_COLUMNS:
            assert col in df.columns

    def test_unlinked_count_in_result(self, tmp_path):
        """result['unlinked_count'] should equal the number of rows in the unlinked CSV."""
        activities = [
            {
                "activity_id": "ACT-001",
                "grant_number": "GR-001",
                "activity_name": "Project 1",
                "responsible_org": "Org A",
                "responsible_org_normalized": "org_a",
                "total_budget": "600000",
            },
        ]
        _make_activities(tmp_path, activities)
        # No linkage → org_a is not linked, budget >= 500k → in unlinked
        result = run(root=tmp_path)
        unlinked_path = tmp_path / "data" / "review" / "hud_drgr_unlinked_activities.csv"
        df = pd.read_csv(unlinked_path)
        assert result["unlinked_count"] == len(df)
