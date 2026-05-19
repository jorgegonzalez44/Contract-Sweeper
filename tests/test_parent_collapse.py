"""Tests for scripts/parent_collapse.py — classify_entity_type, collapse, compute_stats."""

import csv
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.parent_collapse import (
    _parent_key,
    classify_entity_type,
    collapse,
    compute_stats,
    run,
)

_LOG = logging.getLogger("test")


# ---------------------------------------------------------------------------
# classify_entity_type
# ---------------------------------------------------------------------------

class TestClassifyEntityType:
    def test_government_from_name_municipality(self):
        assert classify_entity_type("Municipality of San Juan") == "government"

    def test_government_from_name_authority(self):
        assert classify_entity_type("Puerto Rico Aqueduct Authority") == "government"

    def test_government_from_name_prasa(self):
        assert classify_entity_type("PRASA") == "government"

    def test_government_from_name_prepa(self):
        assert classify_entity_type("Puerto Rico Electric Power Authority PREPA") == "government"

    def test_government_from_name_department(self):
        assert classify_entity_type("Department of Health") == "government"

    def test_government_from_business_types(self):
        # business_types keyword takes priority over name
        assert classify_entity_type("ABC Corp", "government entity") == "government"

    def test_government_bt_state(self):
        assert classify_entity_type("State Agency X", "state") == "government"

    def test_nonprofit_from_name_university(self):
        assert classify_entity_type("University of Puerto Rico") == "nonprofit"

    def test_nonprofit_from_name_hospital(self):
        assert classify_entity_type("Centro Medico Hospital") == "nonprofit"

    def test_nonprofit_from_name_foundation(self):
        assert classify_entity_type("Flamboyan Foundation") == "nonprofit"

    def test_nonprofit_from_business_types(self):
        assert classify_entity_type("Some Health Services", "nonprofit organization") == "nonprofit"

    def test_nonprofit_bt_educational(self):
        assert classify_entity_type("Learning Institute", "educational institution") == "nonprofit"

    def test_corporate_from_business_types_corporation(self):
        assert classify_entity_type("Acme Services", "corporation") == "corporate"

    def test_corporate_from_business_types_llc(self):
        assert classify_entity_type("Acme Services", "limited liability company") == "corporate"

    def test_corporate_default_unrecognized(self):
        # Default for any unrecognized commercial entity is "corporate"
        assert classify_entity_type("XYZ Tech Solutions") == "corporate"

    def test_empty_name_returns_corporate(self):
        assert classify_entity_type("") == "corporate"

    def test_empty_both_returns_corporate(self):
        assert classify_entity_type("", "") == "corporate"

    def test_business_types_keyword_overrides_name(self):
        # "Hospital" in name would normally → nonprofit, but bt overrides
        assert classify_entity_type("Hospital Damas", "government") == "government"


# ---------------------------------------------------------------------------
# _parent_key
# ---------------------------------------------------------------------------

class TestParentKey:
    def test_resolved_parent_returns_parent_fields(self):
        row = {"parent_uei": "PRNT123456", "parent_name": "Parent Corp",
               "uei": "CHILD000001", "vendor_name": "Child Co"}
        assert _parent_key(row) == ("PRNT123456", "Parent Corp")

    def test_unresolved_falls_back_to_self(self):
        row = {"parent_uei": "", "parent_name": "",
               "uei": "SELF123456", "vendor_name": "Solo Corp"}
        assert _parent_key(row) == ("SELF123456", "Solo Corp")

    def test_missing_parent_name_falls_back(self):
        # parent_uei present but parent_name empty → falls back to self
        row = {"parent_uei": "PRNT999", "parent_name": "",
               "uei": "SELF001", "vendor_name": "Standalone Inc"}
        assert _parent_key(row) == ("SELF001", "Standalone Inc")

    def test_missing_parent_uei_falls_back(self):
        # parent_name present but parent_uei empty → falls back to self
        row = {"parent_uei": "", "parent_name": "Some Parent",
               "uei": "SELF002", "vendor_name": "Child Entity"}
        assert _parent_key(row) == ("SELF002", "Child Entity")

    def test_whitespace_stripped(self):
        row = {"parent_uei": "  PRNT123  ", "parent_name": "  Parent Corp  ",
               "uei": "CHILD001", "vendor_name": "Child"}
        uei, name = _parent_key(row)
        assert uei == "PRNT123"
        assert name == "Parent Corp"


# ---------------------------------------------------------------------------
# collapse
# ---------------------------------------------------------------------------

def _row(vendor_name, uei, parent_uei="", parent_name="",
         obligation=100_000, records=1, business_types="corporation"):
    return {
        "vendor_name": vendor_name,
        "uei": uei,
        "parent_uei": parent_uei,
        "parent_name": parent_name,
        "total_obligation": str(obligation),
        "record_count": str(records),
        "business_types": business_types,
        "source": "sam",
    }


class TestCollapse:
    def test_empty_input_returns_empty(self):
        rows, registry = collapse([], {}, _LOG)
        assert rows == []
        assert registry == {}

    def test_single_self_parenting_row(self):
        rows, registry = collapse(
            [_row("Solo Corp", "SOLO1234", obligation=500_000)], {}, _LOG
        )
        assert len(rows) == 1
        assert rows[0]["parent_name"] == "Solo Corp"
        assert rows[0]["total_obligation"] == pytest.approx(500_000)

    def test_two_children_collapse_under_parent(self):
        hierarchy = [
            _row("Subsidiary A", "SUB0001", parent_uei="PRNT0001",
                 parent_name="Parent Corp", obligation=300_000),
            _row("Subsidiary B", "SUB0002", parent_uei="PRNT0001",
                 parent_name="Parent Corp", obligation=200_000),
        ]
        rows, _ = collapse(hierarchy, {}, _LOG)
        assert len(rows) == 1
        assert rows[0]["parent_name"] == "Parent Corp"
        assert rows[0]["total_obligation"] == pytest.approx(500_000)
        assert rows[0]["child_count"] == 2

    def test_multiple_parents_stay_separate(self):
        hierarchy = [
            _row("Child A", "A001", parent_uei="P001", parent_name="Alpha Corp"),
            _row("Child B", "B001", parent_uei="P002", parent_name="Beta Corp"),
        ]
        rows, _ = collapse(hierarchy, {}, _LOG)
        assert len(rows) == 2
        parent_names = {r["parent_name"] for r in rows}
        assert parent_names == {"Alpha Corp", "Beta Corp"}

    def test_alias_registry_maps_variant_to_canonical(self):
        hierarchy = [
            _row("Crowley Maritime Corp", "CRWL001",
                 parent_uei="CRWLP001", parent_name="Crowley Holdings Inc",
                 obligation=1_000_000),
        ]
        _, registry = collapse(hierarchy, {}, _LOG)
        assert "Crowley Maritime Corp" in registry
        assert registry["Crowley Maritime Corp"]["canonical_name"] == "Crowley Holdings Inc"
        assert registry["Crowley Maritime Corp"]["canonical_uei"] == "CRWLP001"

    def test_alias_registry_maps_parent_name_too(self):
        hierarchy = [_row("Sub A", "SUB001", parent_uei="PRNT001", parent_name="Parent Corp")]
        _, registry = collapse(hierarchy, {}, _LOG)
        assert "Parent Corp" in registry
        assert registry["Parent Corp"]["canonical_name"] == "Parent Corp"

    def test_entity_type_government_for_authority(self):
        hierarchy = [_row("PRASA", "PRASA001", business_types="government")]
        rows, registry = collapse(hierarchy, {}, _LOG)
        assert rows[0]["entity_type"] == "government"
        assert registry["PRASA"]["entity_type"] == "government"

    def test_entity_type_corporate_default(self):
        hierarchy = [_row("Acme Services LLC", "ACME001", business_types="corporation")]
        rows, _ = collapse(hierarchy, {}, _LOG)
        assert rows[0]["entity_type"] == "corporate"

    def test_children_list_serialized_as_semicolon_string(self):
        hierarchy = [
            _row("Sub A", "S001", parent_uei="P001", parent_name="Parent"),
            _row("Sub B", "S002", parent_uei="P001", parent_name="Parent"),
        ]
        rows, _ = collapse(hierarchy, {}, _LOG)
        assert isinstance(rows[0]["children"], str)
        children = set(rows[0]["children"].split("; "))
        assert "Sub A" in children
        assert "Sub B" in children

    def test_sorted_descending_by_obligation(self):
        hierarchy = [
            _row("Small Corp", "S001", obligation=100_000),
            _row("Big Corp", "B001", obligation=1_000_000),
        ]
        rows, _ = collapse(hierarchy, {}, _LOG)
        assert rows[0]["total_obligation"] > rows[1]["total_obligation"]


# ---------------------------------------------------------------------------
# compute_stats
# ---------------------------------------------------------------------------

def _collapsed(*types):
    return [{"entity_type": t} for t in types]


class TestComputeStats:
    def test_empty_returns_zeros(self):
        stats = compute_stats([], [])
        assert stats["total_vendors"] == 0
        assert stats["total_parent_entities"] == 0
        assert stats["entity_type_assignment_rate"] == 0

    def test_all_corporate(self):
        collapsed = _collapsed("corporate", "corporate", "corporate")
        stats = compute_stats(collapsed, [{}, {}, {}])
        assert stats["entity_type_counts"]["corporate"] == 3
        assert stats["entity_type_assignment_rate"] == pytest.approx(1.0)

    def test_mixed_types_counted_correctly(self):
        collapsed = _collapsed("government", "nonprofit", "corporate", "corporate")
        stats = compute_stats(collapsed, [{} for _ in range(4)])
        counts = stats["entity_type_counts"]
        assert counts["government"] == 1
        assert counts["nonprofit"] == 1
        assert counts["corporate"] == 2
        assert counts["unknown"] == 0

    def test_unknown_type_reduces_assignment_rate(self):
        collapsed = _collapsed("corporate", "corporate", "unknown")
        stats = compute_stats(collapsed, [{}, {}, {}])
        # compute_stats rounds to 4 decimal places: 2/3 rounds to 0.6667
        assert stats["entity_type_assignment_rate"] == pytest.approx(2 / 3, abs=5e-4)

    def test_entity_type_counts_sum_equals_total_parent_entities(self):
        collapsed = _collapsed("government", "nonprofit", "corporate", "corporate", "unknown")
        stats = compute_stats(collapsed, [{} for _ in range(5)])
        counts = stats["entity_type_counts"]
        total_classified = sum(counts.values())
        assert total_classified == stats["total_parent_entities"]

    def test_vendors_with_parent_uei_count(self):
        hierarchy = [
            {"parent_uei": "PRNT001", "parent_name": "Parent A"},
            {"parent_uei": "",        "parent_name": ""},
            {"parent_uei": "PRNT002", "parent_name": "Parent B"},
        ]
        stats = compute_stats([], hierarchy)
        assert stats["vendors_with_parent_uei"] == 2

    def test_vendors_with_parent_uei_requires_both_fields(self):
        hierarchy = [
            {"parent_uei": "PRNT001", "parent_name": ""},   # missing name → not counted
            {"parent_uei": "",        "parent_name": "P2"},  # missing uei → not counted
        ]
        stats = compute_stats([], hierarchy)
        assert stats["vendors_with_parent_uei"] == 0

    def test_parent_uei_rate_calculation(self):
        hierarchy = [
            {"parent_uei": "P001", "parent_name": "Parent A"},
            {"parent_uei": "",     "parent_name": ""},
        ]
        stats = compute_stats([], hierarchy)
        assert stats["parent_uei_rate"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# run() integration
# ---------------------------------------------------------------------------

def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


class TestRunIntegration:
    def _enrichment_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "data" / "staging" / "processed" / "enrichment"
        d.mkdir(parents=True)
        return d

    def test_run_with_no_inputs_completes_cleanly(self, tmp_path):
        stats = run(root=tmp_path)
        assert stats["total_vendors"] == 0
        assert stats["total_parent_entities"] == 0
        enrichment_dir = tmp_path / "data" / "staging" / "processed" / "enrichment"
        assert (enrichment_dir / "parent_collapsed.csv").exists()
        assert (enrichment_dir / "alias_registry.json").exists()
        assert (enrichment_dir / "parent_collapse_stats.json").exists()

    def test_run_writes_correct_stats_json(self, tmp_path):
        enrichment_dir = self._enrichment_dir(tmp_path)
        _write_csv(
            enrichment_dir / "entity_hierarchy.csv",
            [
                {"vendor_name": "Crowley Maritime Corp", "uei": "CRWL001",
                 "parent_uei": "CRWLP001", "parent_name": "Crowley Holdings Inc",
                 "total_obligation": "1000000", "record_count": "5",
                 "business_types": "corporation", "source": "sam",
                 "rank": "1", "match_confidence": "high"},
                {"vendor_name": "PRASA", "uei": "PRASA001",
                 "parent_uei": "", "parent_name": "",
                 "total_obligation": "500000", "record_count": "3",
                 "business_types": "government", "source": "sam",
                 "rank": "2", "match_confidence": "high"},
            ],
            ["vendor_name", "uei", "parent_uei", "parent_name",
             "total_obligation", "record_count", "business_types", "source",
             "rank", "match_confidence"],
        )
        stats = run(root=tmp_path)
        assert stats["total_vendors"] == 2
        assert stats["total_parent_entities"] == 2
        counts = stats["entity_type_counts"]
        assert counts["corporate"] >= 1
        assert counts["government"] >= 1
        alias_path = enrichment_dir / "alias_registry.json"
        registry = json.loads(alias_path.read_text())
        assert "Crowley Maritime Corp" in registry
        assert "PRASA" in registry
