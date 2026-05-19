"""Tests for scripts/parent_collapse.py — entity collapse and alias registry."""

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
    write_alias_registry,
    write_collapsed,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _logger():
    log = logging.getLogger("test_parent_collapse")
    log.addHandler(logging.NullHandler())
    return log


def _row(
    vendor_name="Acme Corp",
    uei="AAAA12345678",
    parent_uei="PRNT12345678",
    parent_name="Acme Holdings",
    business_types="corporation",
    total_obligation="1000000",
    record_count="10",
    source="usaspending",
) -> dict:
    return {
        "vendor_name": vendor_name,
        "uei": uei,
        "parent_uei": parent_uei,
        "parent_name": parent_name,
        "business_types": business_types,
        "total_obligation": total_obligation,
        "record_count": record_count,
        "source": source,
    }


# ---------------------------------------------------------------------------
# classify_entity_type
# ---------------------------------------------------------------------------

class TestClassifyEntityType:
    def test_municipality_in_name_is_government(self):
        assert classify_entity_type("Municipality of San Juan") == "government"

    def test_municipio_in_name_is_government(self):
        assert classify_entity_type("Municipio de Ponce") == "government"

    def test_authority_in_name_is_government(self):
        assert classify_entity_type("Puerto Rico Aqueduct And Sewer Authority") == "government"

    def test_department_in_name_is_government(self):
        assert classify_entity_type("Department of Education PR") == "government"

    def test_prasa_keyword_is_government(self):
        assert classify_entity_type("PRASA Main Office") == "government"

    def test_prepa_keyword_is_government(self):
        assert classify_entity_type("PREPA Electric Authority") == "government"

    def test_government_in_business_types_is_government(self):
        assert classify_entity_type("Random Name", "government entity") == "government"

    def test_municipality_in_business_types_is_government(self):
        assert classify_entity_type("San Juan City", "municipality type") == "government"

    def test_state_in_business_types_is_government(self):
        assert classify_entity_type("Commonwealth Agency", "state body") == "government"

    def test_university_in_name_is_nonprofit(self):
        assert classify_entity_type("University of Puerto Rico") == "nonprofit"

    def test_hospital_in_name_is_nonprofit(self):
        assert classify_entity_type("Hospital del Maestro") == "nonprofit"

    def test_foundation_in_name_is_nonprofit(self):
        assert classify_entity_type("Red Cross Foundation") == "nonprofit"

    def test_health_in_name_is_nonprofit(self):
        assert classify_entity_type("PR Health Sciences Center") == "nonprofit"

    def test_nonprofit_in_business_types_is_nonprofit(self):
        assert classify_entity_type("Helpers Corp", "nonprofit organization") == "nonprofit"

    def test_educational_in_business_types_is_nonprofit(self):
        assert classify_entity_type("Learning Center", "educational institution") == "nonprofit"

    def test_corporation_in_business_types_is_corporate(self):
        assert classify_entity_type("Generic Entity", "corporation") == "corporate"

    def test_limited_liability_in_business_types_is_corporate(self):
        assert classify_entity_type("Island LLC", "limited liability company") == "corporate"

    def test_generic_company_name_defaults_to_corporate(self):
        assert classify_entity_type("Acme Corp LLC") == "corporate"

    def test_empty_name_defaults_to_corporate(self):
        # default fall-through → "corporate" (not "unknown")
        assert classify_entity_type("") == "corporate"

    def test_numeric_only_defaults_to_corporate(self):
        assert classify_entity_type("12345") == "corporate"

    def test_business_types_beats_name_keyword_government(self):
        # explicit government business_type overrides ambiguous name
        assert classify_entity_type("Island Services", "government") == "government"

    def test_business_types_beats_name_keyword_nonprofit(self):
        assert classify_entity_type("Island Services", "nonprofit") == "nonprofit"

    def test_case_insensitive_name_match(self):
        assert classify_entity_type("municipality of bayamon") == "government"


# ---------------------------------------------------------------------------
# _parent_key
# ---------------------------------------------------------------------------

class TestParentKey:
    def test_resolved_row_returns_parent_uei_and_name(self):
        row = _row(uei="SELF0001", parent_uei="PRNT0001", parent_name="Parent Corp")
        assert _parent_key(row) == ("PRNT0001", "Parent Corp")

    def test_no_parent_uei_falls_back_to_self(self):
        row = _row(uei="SELF0001", parent_uei="", parent_name="", vendor_name="Solo Corp")
        puei, pname = _parent_key(row)
        assert puei == "SELF0001"
        assert pname == "Solo Corp"

    def test_parent_name_without_uei_falls_back_to_self(self):
        row = _row(uei="SELF0001", parent_uei="", parent_name="Orphan Holdings", vendor_name="Sub Corp")
        puei, pname = _parent_key(row)
        assert puei == "SELF0001"
        assert pname == "Sub Corp"

    def test_strips_whitespace(self):
        row = _row(uei="  SELF01  ", parent_uei="  PRNT01  ", parent_name="  Parent Co  ")
        puei, pname = _parent_key(row)
        assert puei == "PRNT01"
        assert pname == "Parent Co"


# ---------------------------------------------------------------------------
# collapse
# ---------------------------------------------------------------------------

class TestCollapse:
    def test_children_collapse_under_parent(self):
        rows = [
            _row(vendor_name="Sub A", uei="SUBA00000001", parent_uei="PRNT00000001", parent_name="Parent Corp", total_obligation="500000"),
            _row(vendor_name="Sub B", uei="SUBB00000001", parent_uei="PRNT00000001", parent_name="Parent Corp", total_obligation="300000"),
        ]
        collapsed, _ = collapse(rows, {}, _logger())
        assert len(collapsed) == 1
        parent = collapsed[0]
        assert parent["parent_uei"] == "PRNT00000001"
        assert parent["parent_name"] == "Parent Corp"
        assert parent["total_obligation"] == pytest.approx(800000)
        assert parent["child_count"] == 2

    def test_self_parenting_uei_becomes_root(self):
        row = _row(vendor_name="Root Corp", uei="ROOT0000001", parent_uei="ROOT0000001", parent_name="Root Corp")
        collapsed, _ = collapse([row], {}, _logger())
        assert len(collapsed) == 1
        assert collapsed[0]["parent_uei"] == "ROOT0000001"

    def test_unresolved_entity_becomes_its_own_root(self):
        row = _row(vendor_name="Standalone Corp", uei="STND0000001", parent_uei="", parent_name="")
        collapsed, _ = collapse([row], {}, _logger())
        assert len(collapsed) == 1
        assert collapsed[0]["parent_name"] == "Standalone Corp"
        assert collapsed[0]["parent_uei"] == "STND0000001"

    def test_alias_registry_maps_variant_to_canonical(self):
        row = _row(vendor_name="Acme Sub", uei="ACME0000001", parent_uei="PRNT0000001", parent_name="Acme Holdings")
        _, registry = collapse([row], {}, _logger())
        assert "Acme Holdings" in registry or "Acme Sub" in registry
        # at least the vendor name should appear
        assert "Acme Sub" in registry
        assert registry["Acme Sub"]["canonical_name"] == "Acme Holdings"

    def test_alias_registry_canonical_uei(self):
        row = _row(vendor_name="Sub Corp", uei="SUB00000001", parent_uei="PRNT0000001", parent_name="Parent Corp")
        _, registry = collapse([row], {}, _logger())
        assert registry["Sub Corp"]["canonical_uei"] == "PRNT0000001"

    def test_multiple_parents_produce_multiple_collapsed_rows(self):
        rows = [
            _row(vendor_name="Corp A", uei="AAAA0000001", parent_uei="PRNT0000001", parent_name="Parent A", total_obligation="1000000"),
            _row(vendor_name="Corp B", uei="BBBB0000001", parent_uei="PRNT0000002", parent_name="Parent B", total_obligation="500000"),
        ]
        collapsed, _ = collapse(rows, {}, _logger())
        assert len(collapsed) == 2

    def test_collapsed_rows_sorted_by_obligation_descending(self):
        rows = [
            _row(vendor_name="Small", uei="SMAL0000001", parent_uei="PRNT0000001", parent_name="Small Parent", total_obligation="100"),
            _row(vendor_name="Big", uei="BIGG0000001", parent_uei="PRNT0000002", parent_name="Big Parent", total_obligation="9999999"),
        ]
        collapsed, _ = collapse(rows, {}, _logger())
        assert collapsed[0]["total_obligation"] > collapsed[1]["total_obligation"]

    def test_children_field_is_semicolon_separated_string(self):
        rows = [
            _row(vendor_name="Sub A", uei="SUBA0000001", parent_uei="PRNT0000001", parent_name="Parent Corp"),
            _row(vendor_name="Sub B", uei="SUBB0000001", parent_uei="PRNT0000001", parent_name="Parent Corp"),
        ]
        collapsed, _ = collapse(rows, {}, _logger())
        children = collapsed[0]["children"]
        assert isinstance(children, str)
        assert "Sub A" in children
        assert "Sub B" in children

    def test_empty_input_produces_empty_output(self):
        collapsed, registry = collapse([], {}, _logger())
        assert collapsed == []
        assert registry == {}

    def test_entity_type_set_from_name_classification(self):
        row = _row(vendor_name="Municipality of Test", uei="MUNI0000001", parent_uei="", parent_name="")
        collapsed, _ = collapse([row], {}, _logger())
        assert collapsed[0]["entity_type"] == "government"

    def test_entity_type_set_for_nonprofit(self):
        row = _row(vendor_name="University of Test", uei="UNIV0000001", parent_uei="", parent_name="")
        collapsed, _ = collapse([row], {}, _logger())
        assert collapsed[0]["entity_type"] == "nonprofit"

    def test_record_count_aggregated(self):
        rows = [
            _row(vendor_name="Sub A", uei="SUBA0000001", parent_uei="PRNT0000001", parent_name="Parent Corp", record_count="5"),
            _row(vendor_name="Sub B", uei="SUBB0000001", parent_uei="PRNT0000001", parent_name="Parent Corp", record_count="8"),
        ]
        collapsed, _ = collapse(rows, {}, _logger())
        assert collapsed[0]["total_records"] == 13


# ---------------------------------------------------------------------------
# compute_stats
# ---------------------------------------------------------------------------

class TestComputeStats:
    def _make_collapsed(self, entity_types: list[str]) -> list[dict]:
        return [{"entity_type": et, "parent_uei": f"UEI{i:04d}", "parent_name": f"Entity {i}"}
                for i, et in enumerate(entity_types)]

    def _make_hierarchy(self, n: int, with_parent: int) -> list[dict]:
        rows = []
        for i in range(n):
            if i < with_parent:
                rows.append({"parent_uei": f"PRNT{i:04d}", "parent_name": f"Parent {i}"})
            else:
                rows.append({"parent_uei": "", "parent_name": ""})
        return rows

    def test_entity_type_counts_sum_to_total_parent_entities(self):
        collapsed = self._make_collapsed(["government", "nonprofit", "corporate", "corporate"])
        stats = compute_stats(collapsed, [])
        counts = stats["entity_type_counts"]
        assert sum(counts.values()) == stats["total_parent_entities"]

    def test_entity_type_assignment_rate_all_classified(self):
        collapsed = self._make_collapsed(["government", "corporate", "nonprofit"])
        stats = compute_stats(collapsed, [])
        assert stats["entity_type_assignment_rate"] == pytest.approx(1.0)

    def test_entity_type_assignment_rate_with_unknown(self):
        collapsed = self._make_collapsed(["corporate", "unknown"])
        stats = compute_stats(collapsed, [])
        assert stats["entity_type_assignment_rate"] == pytest.approx(0.5)

    def test_parent_uei_rate_computed_from_hierarchy(self):
        hierarchy = self._make_hierarchy(4, with_parent=2)
        collapsed = self._make_collapsed(["corporate"] * 2)
        stats = compute_stats(collapsed, hierarchy)
        assert stats["parent_uei_rate"] == pytest.approx(0.5)

    def test_empty_collapsed_produces_zero_assignment_rate(self):
        stats = compute_stats([], [])
        # 0 classified / max(0,1) = 0.0
        assert stats["entity_type_assignment_rate"] == pytest.approx(0.0)
        assert stats["total_parent_entities"] == 0

    def test_total_vendors_equals_hierarchy_length(self):
        hierarchy = self._make_hierarchy(7, with_parent=3)
        stats = compute_stats([], hierarchy)
        assert stats["total_vendors"] == 7


# ---------------------------------------------------------------------------
# Integration — run() with tmp_path
# ---------------------------------------------------------------------------

class TestRunIntegration:
    def _write_hierarchy(self, enrichment_dir: Path, rows: list[dict]) -> None:
        import csv
        fields = ["vendor_name", "uei", "parent_uei", "parent_name",
                  "business_types", "total_obligation", "record_count", "source"]
        p = enrichment_dir / "entity_hierarchy.csv"
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in fields})

    def test_run_creates_parent_collapsed_csv(self, tmp_path):
        enrichment_dir = tmp_path / "data" / "staging" / "processed" / "enrichment"
        enrichment_dir.mkdir(parents=True)
        self._write_hierarchy(enrichment_dir, [
            _row(vendor_name="Corp A", uei="CORP0000001", parent_uei="PRNT0000001", parent_name="Corp Holdings"),
        ])
        run(root=tmp_path)
        assert (enrichment_dir / "parent_collapsed.csv").exists()

    def test_run_creates_alias_registry_json(self, tmp_path):
        enrichment_dir = tmp_path / "data" / "staging" / "processed" / "enrichment"
        enrichment_dir.mkdir(parents=True)
        self._write_hierarchy(enrichment_dir, [
            _row(vendor_name="Corp A", uei="CORP0000001", parent_uei="PRNT0000001", parent_name="Corp Holdings"),
        ])
        run(root=tmp_path)
        registry_path = enrichment_dir / "alias_registry.json"
        assert registry_path.exists()
        registry = json.loads(registry_path.read_text())
        assert isinstance(registry, dict)
        assert len(registry) > 0

    def test_run_with_no_hierarchy_file_creates_empty_outputs(self, tmp_path):
        # No entity_hierarchy.csv → run should not crash; outputs still written
        enrichment_dir = tmp_path / "data" / "staging" / "processed" / "enrichment"
        enrichment_dir.mkdir(parents=True)
        stats = run(root=tmp_path)
        assert stats["total_parent_entities"] == 0
        assert (enrichment_dir / "parent_collapsed.csv").exists()
        assert (enrichment_dir / "alias_registry.json").exists()

    def test_run_returns_stats_dict_with_required_keys(self, tmp_path):
        enrichment_dir = tmp_path / "data" / "staging" / "processed" / "enrichment"
        enrichment_dir.mkdir(parents=True)
        self._write_hierarchy(enrichment_dir, [
            _row(vendor_name="Corp A", uei="CORP0000001", parent_uei="PRNT0000001", parent_name="Corp Holdings"),
        ])
        stats = run(root=tmp_path)
        for key in ("total_vendors", "total_parent_entities", "entity_type_counts",
                    "entity_type_assignment_rate", "parent_uei_rate"):
            assert key in stats

    def test_run_collapses_children_correctly(self, tmp_path):
        enrichment_dir = tmp_path / "data" / "staging" / "processed" / "enrichment"
        enrichment_dir.mkdir(parents=True)
        self._write_hierarchy(enrichment_dir, [
            _row(vendor_name="Sub A", uei="SUBA0000001", parent_uei="PRNT0000001",
                 parent_name="Corp Parent", total_obligation="400000"),
            _row(vendor_name="Sub B", uei="SUBB0000001", parent_uei="PRNT0000001",
                 parent_name="Corp Parent", total_obligation="600000"),
        ])
        stats = run(root=tmp_path)
        assert stats["total_parent_entities"] == 1
        assert stats["total_vendors"] == 2
