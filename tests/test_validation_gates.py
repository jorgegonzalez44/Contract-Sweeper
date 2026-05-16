"""Tests for scripts/validation_gates.py — entity-type-stratified gates."""

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.validation_gates import (
    GateResult,
    HIGH_VALUE_THRESHOLD,
    gate_corporate_parent_uei,
    gate_entity_type_assignment,
    gate_government_classification,
    gate_high_value_unresolved,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collapsed_row(
    name="Acme Corp",
    entity_type="corporate",
    parent_uei="PRNT12345678",
    total_obligation="1000000",
) -> dict:
    return {
        "parent_name": name,
        "entity_type": entity_type,
        "parent_uei": parent_uei,
        "total_obligation": total_obligation,
        "total_records": "10",
        "child_count": "1",
    }


def _hierarchy_row(
    vendor_name="Acme Corp",
    uei="SELF12345678",
    parent_uei="PRNT12345678",
    parent_name="Acme Holdings",
    business_types="corporation",
    total_obligation="1000000",
) -> dict:
    return {
        "vendor_name": vendor_name,
        "uei": uei,
        "parent_uei": parent_uei,
        "parent_name": parent_name,
        "business_types": business_types,
        "total_obligation": total_obligation,
        "record_count": "10",
        "match_confidence": "0.90",
        "source": "usaspending",
    }


# ---------------------------------------------------------------------------
# gate_entity_type_assignment
# ---------------------------------------------------------------------------

class TestEntityTypeAssignmentGate:
    def test_passes_when_all_classified(self):
        rows = [
            _collapsed_row(entity_type="corporate"),
            _collapsed_row(entity_type="government"),
            _collapsed_row(entity_type="nonprofit"),
        ]
        result = gate_entity_type_assignment(rows)
        assert result.passed is True
        assert result.value == 1.0

    def test_fails_when_too_many_unknown(self):
        rows = [_collapsed_row(entity_type="unknown")] * 5 + [
            _collapsed_row(entity_type="corporate")
        ]
        result = gate_entity_type_assignment(rows)
        assert result.passed is False
        assert result.value < 0.90

    def test_empty_rows_fails(self):
        result = gate_entity_type_assignment([])
        assert result.passed is False
        assert result.value == 0.0

    def test_exactly_at_threshold_passes(self):
        rows = (
            [_collapsed_row(entity_type="corporate")] * 9
            + [_collapsed_row(entity_type="unknown")] * 1
        )
        result = gate_entity_type_assignment(rows)
        assert result.value == 0.9
        assert result.passed is True


# ---------------------------------------------------------------------------
# gate_government_classification
# ---------------------------------------------------------------------------

class TestGovernmentClassificationGate:
    def test_passes_when_all_gov_labelled(self):
        # Name triggers government heuristic; entity_type matches
        rows = [
            _collapsed_row(name="Municipality of San Juan", entity_type="government"),
            _collapsed_row(name="Puerto Rico Aqueduct And Sewer Authority", entity_type="government"),
        ]
        result = gate_government_classification(rows)
        assert result.passed is True
        assert result.value == 1.0

    def test_vacuously_passes_with_no_gov_candidates(self):
        rows = [
            _collapsed_row(name="Acme Tech Corp", entity_type="corporate"),
            _collapsed_row(name="Delta Solutions LLC", entity_type="corporate"),
        ]
        result = gate_government_classification(rows)
        assert result.passed is True
        assert result.value == 1.0
        assert "vacuously" in result.detail

    def test_fails_when_gov_labelled_as_corporate(self):
        rows = [
            _collapsed_row(name="Municipality of Ponce", entity_type="corporate"),
            _collapsed_row(name="Municipality of Ponce 2", entity_type="corporate"),
            _collapsed_row(name="Municipality of Ponce 3", entity_type="corporate"),
            _collapsed_row(name="Municipality of Ponce 4", entity_type="corporate"),
            _collapsed_row(name="Municipality of Ponce 5", entity_type="corporate"),
            _collapsed_row(name="Municipality of Ponce 6", entity_type="government"),
        ]
        result = gate_government_classification(rows)
        assert result.passed is False


# ---------------------------------------------------------------------------
# gate_corporate_parent_uei
# ---------------------------------------------------------------------------

class TestCorporateParentUEIGate:
    def test_passes_when_majority_resolved(self):
        rows = [
            _hierarchy_row(vendor_name="Corp A", uei="AAAAAAAAAAAA", parent_uei="PPPPPPPPPPPP"),
            _hierarchy_row(vendor_name="Corp B", uei="BBBBBBBBBBBB", parent_uei="PPPPPPPPPPPP"),
            _hierarchy_row(vendor_name="Corp C", uei="CCCCCCCCCCCC", parent_uei=""),
        ]
        result = gate_corporate_parent_uei(rows)
        assert result.passed is True
        assert result.value == pytest.approx(2 / 3, abs=0.01)

    def test_fails_when_none_resolved(self):
        rows = [
            _hierarchy_row(vendor_name="Corp A", uei="AAAAAAAAAAAA", parent_uei=""),
            _hierarchy_row(vendor_name="Corp B", uei="BBBBBBBBBBBB", parent_uei=""),
        ]
        result = gate_corporate_parent_uei(rows)
        assert result.passed is False
        assert result.value == 0.0

    def test_self_parenting_uei_not_counted_as_resolved(self):
        # parent_uei == own uei → self-parenting, not a true parent
        rows = [
            _hierarchy_row(vendor_name="Corp A", uei="SELFSELF0001", parent_uei="SELFSELF0001"),
        ]
        result = gate_corporate_parent_uei(rows)
        assert result.value == 0.0
        assert result.passed is False

    def test_excludes_government_and_nonprofit_entities(self):
        rows = [
            _hierarchy_row(vendor_name="Municipality of Foo", business_types="municipality; government", parent_uei=""),
            _hierarchy_row(vendor_name="University of Foo", business_types="university; nonprofit; educational", parent_uei=""),
            _hierarchy_row(vendor_name="Corp A", uei="AAAA", parent_uei="BBBB"),
        ]
        result = gate_corporate_parent_uei(rows)
        # Only Corp A should be counted; 1/1 resolved → passes
        assert result.value == 1.0
        assert result.passed is True

    def test_vacuously_passes_with_no_corporate_rows(self):
        rows = [
            _hierarchy_row(vendor_name="Municipality of Foo", business_types="government", parent_uei=""),
        ]
        result = gate_corporate_parent_uei(rows)
        assert result.passed is True
        assert "vacuously" in result.detail


# ---------------------------------------------------------------------------
# gate_high_value_unresolved
# ---------------------------------------------------------------------------

class TestHighValueUnresolvedGate:
    def _hv_obligation(self) -> str:
        return str(HIGH_VALUE_THRESHOLD + 1)

    def test_passes_when_all_resolved(self):
        rows = [
            _hierarchy_row(
                vendor_name="Big Corp", uei="BIGC12345678",
                parent_uei="PRNT12345678", parent_name="Big Holdings",
                total_obligation=self._hv_obligation(),
            )
        ]
        result = gate_high_value_unresolved(rows)
        assert result.passed is True
        assert result.value == 0.0

    def test_fails_when_majority_unresolved(self):
        rows = [
            _hierarchy_row(
                vendor_name=f"Unresolved Corp {i}",
                uei=f"UNRES{i:07d}",
                parent_uei="",
                parent_name="",
                total_obligation=self._hv_obligation(),
            )
            for i in range(5)
        ] + [
            _hierarchy_row(
                vendor_name="Resolved Corp",
                uei="RSLVD1234567",
                parent_uei="PRNT12345678",
                parent_name="Parent Corp",
                total_obligation=self._hv_obligation(),
            )
        ]
        result = gate_high_value_unresolved(rows)
        assert result.passed is False

    def test_ignores_low_value_entities(self):
        rows = [
            _hierarchy_row(
                vendor_name="Small Corp",
                uei="SMAL12345678",
                parent_uei="",
                parent_name="",
                total_obligation="1000",  # below threshold
            )
        ]
        result = gate_high_value_unresolved(rows)
        assert result.passed is True
        assert "vacuously" in result.detail

    def test_excludes_known_parent_entities_from_unresolved_count(self):
        # "Parent Corp" appears as parent_name of child → it's a root, not unresolved
        rows = [
            _hierarchy_row(
                vendor_name="Parent Corp",
                uei="PRNT12345678",
                parent_uei="",
                parent_name="",
                total_obligation=self._hv_obligation(),
            ),
            _hierarchy_row(
                vendor_name="Child Corp",
                uei="CHLD12345678",
                parent_uei="PRNT12345678",
                parent_name="Parent Corp",
                total_obligation=self._hv_obligation(),
            ),
        ]
        result = gate_high_value_unresolved(rows)
        # "Parent Corp" excluded as known parent; "Child Corp" is resolved → 0/1 unresolved
        assert result.passed is True
        assert result.value == 0.0

    def test_vacuously_passes_with_no_high_value_entities(self):
        rows = []
        result = gate_high_value_unresolved(rows)
        assert result.passed is True


# ---------------------------------------------------------------------------
# Integration — run() with tmp_path fixtures
# ---------------------------------------------------------------------------

class TestRunIntegration:
    def _write_collapsed(self, enrichment_dir: Path, rows: list[dict]) -> None:
        fields = ["parent_name", "entity_type", "parent_uei", "total_obligation",
                  "total_records", "child_count", "children", "child_ueis",
                  "resolution_source"]
        p = enrichment_dir / "parent_collapsed.csv"
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in fields})

    def _write_hierarchy(self, enrichment_dir: Path, rows: list[dict]) -> None:
        fields = ["vendor_name", "uei", "parent_uei", "parent_name",
                  "business_types", "total_obligation", "record_count",
                  "match_confidence", "source"]
        p = enrichment_dir / "entity_hierarchy.csv"
        with open(p, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in fields})

    def test_run_produces_validation_report_json(self, tmp_path):
        enrichment_dir = tmp_path / "data" / "staging" / "processed" / "enrichment"
        enrichment_dir.mkdir(parents=True)
        manifests_dir = tmp_path / "data" / "manifests"
        manifests_dir.mkdir(parents=True)

        self._write_collapsed(enrichment_dir, [
            {"parent_name": "Corp A", "entity_type": "corporate",
             "parent_uei": "PRNT12345678", "total_obligation": "1000000"},
        ])
        self._write_hierarchy(enrichment_dir, [
            {"vendor_name": "Corp A", "uei": "CORP12345678",
             "parent_uei": "PRNT12345678", "parent_name": "Corp Holdings",
             "business_types": "corporation", "total_obligation": "1000000"},
        ])

        report = run(root=tmp_path, report_only=True)
        report_path = manifests_dir / "validation_report.json"
        assert report_path.exists()
        data = json.loads(report_path.read_text())
        assert "gates" in data
        assert "overall_pass" in data
        assert data["total_parent_entities"] == 1

    def test_overall_pass_reflects_gate_failures(self, tmp_path):
        enrichment_dir = tmp_path / "data" / "staging" / "processed" / "enrichment"
        enrichment_dir.mkdir(parents=True)
        (tmp_path / "data" / "manifests").mkdir(parents=True)

        # Empty collapsed → entity_type_assignment_rate gate fails
        self._write_collapsed(enrichment_dir, [])
        self._write_hierarchy(enrichment_dir, [])

        report = run(root=tmp_path, report_only=True)
        assert report.overall_pass is False
        assert "entity_type_assignment_rate" in report.blockers
