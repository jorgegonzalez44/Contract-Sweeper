# PR2.6 — Entity Gate Recalibration Report

**Generated:** 2026-05-16  
**Branch:** claude/pre-pr3-entity-gate-tasks-lM1j4  
**Scripts:** `scripts/validation_gates.py`, `scripts/parent_collapse.py`  

---

## Problem Statement

The previous universal `parent_uei_rate` gate (threshold ≥ 0.60) incorrectly blocked
datasets where government authorities, municipalities, and nonprofit institutions comprised
a significant portion of vendors. These entity types have no SAM parent UEI by design — they
are the root entities in the federal spending hierarchy. Applying the same parent UEI
requirement to, e.g., the Municipality of San Juan (which has no SAM parent) as to a corporate
subsidiary produced spurious pipeline failures.

---

## Changes

### Removed
- `parent_uei_rate` as a universal pipeline gate (was: `≥ 0.60`)

### Added — `scripts/validation_gates.py`

Four entity-type-stratified gates replace the single blunt gate:

| Gate | Threshold | Scope |
|---|---|---|
| `entity_type_assignment_rate` | ≥ 0.90 | All parent entities must be classified |
| `government_entity_classification_rate` | ≥ 0.95 | Government candidates correctly labelled |
| `corporate_parent_uei_rate` | ≥ 0.50 | Corporate vendors with distinct parent UEI |
| `high_value_unresolved_review_rate` | ≤ 0.10 | Non-root HV corporates without parent UEI |

### Added — `scripts/parent_collapse.py`

- `classify_entity_type(name, business_types)` heuristic (government/nonprofit/corporate/unknown)
- Collapse of child entities under resolved parent
- `alias_registry.json` output for downstream cross-referencing

### Added — `data/source_registry.yaml`

- Source-level coverage targets and expected entity type mix per dataset
- Canonical record of deprecated gates for audit trail

---

## Validation Run — Current Dataset

```
total_parent_entities : 19
entity_type_counts    : government=5, nonprofit=3, corporate=11, unknown=0
```

| Gate | Value | Threshold | Result |
|---|---|---|---|
| entity_type_assignment_rate | 1.0000 | ≥ 0.90 | **PASS** |
| government_entity_classification_rate | 1.0000 | ≥ 0.95 | **PASS** |
| corporate_parent_uei_rate | 0.8333 | ≥ 0.50 | **PASS** |
| high_value_unresolved_review_rate | 0.0909 | ≤ 0.10 | **PASS** |

**Overall: PASS** — no blockers.

One high-value corporate entity (V-COMS Inc, $2.3B) remains unresolved
and is surfaced in the `high_value_unresolved_review_rate` gate detail for
manual review prior to PR3.

---

## Test Coverage

| Test file | New tests | All pass? |
|---|---|---|
| `tests/test_validation_gates.py` | 19 | Yes |

Full suite: **424 passed, 4 skipped** (was 405 + 4 before PR2.6).

---

## Outputs

| File | Description |
|---|---|
| `scripts/validation_gates.py` | Entity-type-stratified gate runner |
| `scripts/parent_collapse.py` | Hierarchy collapse + alias registry builder |
| `data/source_registry.yaml` | Gate thresholds + source coverage targets |
| `data/manifests/validation_report.json` | Machine-readable gate results |
| `data/staging/processed/enrichment/alias_registry.json` | 29 vendor name → canonical entity mappings |
| `data/staging/processed/enrichment/parent_collapsed.csv` | 19 parent-level collapsed rows |
| `reports/pr2_5_sam_parent_resolution_report.md` | PR2.5 closeout (SAM parent resolution) |
| `reports/pr2_6_entity_gate_recalibration_report.md` | This report |

---

## Next Steps (PR3)

- Feed `alias_registry.json` into `build_unified_master.py` for recipient deduplication
- Wire `validation_gates.run()` into CI smoke test (`scripts/run_smoke_tests.sh`)
- Resolve V-COMS Inc manually and update `entity_hierarchy.csv`
