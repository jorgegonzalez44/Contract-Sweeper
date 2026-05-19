# PR2.5 — SAM Parent Resolution Report

**Generated:** 2026-05-16  
**Branch:** claude/pre-pr3-entity-gate-tasks-lM1j4  
**Script:** `scripts/parent_collapse.py`  

---

## Summary

| Metric | Value |
|---|---|
| Total vendors resolved | 20 |
| Unique parent entities | 19 |
| Vendors with parent UEI resolved | 7 (35.0%) |
| Entity type assignment rate | 100% |

## Entity Type Distribution (Parent Entities)

| Type | Count | Notes |
|---|---|---|
| Government | 5 | Municipalities, authorities (PRASA, PREPA, UPR) |
| Nonprofit | 3 | Hospitals, universities (Hospital Damas, Interamerican, Centro Medico) |
| Corporate | 11 | For-profit contractors |
| Unknown | 0 | All entities classified |

## Parent UEI Resolution by Entity Type

Government and nonprofit entities are typically their own root — no parent UEI expected.
Corporate entities with resolved parents:

| Vendor | Resolved Parent | Source |
|---|---|---|
| Crowley Maritime Corp | Crowley Holdings Inc | USASpending |
| First Bancorp Puerto Rico | FirstBancorp | USASpending |
| Microsoft Puerto Rico Inc | Microsoft Corporation | SAM.gov |
| Hewlett Packard Puerto Rico LLC | HP Inc | SAM.gov |
| Banco Popular de Puerto Rico | Popular Inc | USASpending |
| Louis Berger Group Inc | WSP Global Inc | USASpending |
| Tetra Tech Inc Puerto Rico | Tetra Tech Inc | SAM.gov |

## USASpending Background Lookup — Status

Background entity lookups via `entity_resolution.py` completed against
`https://api.usaspending.gov/api/v2/recipient/` for top-20 vendors by obligation.

- **7/20** corporate entities resolved to a distinct parent entity
- **13/20** entities are self-parenting (government authorities, nonprofits, standalone corps)
- Coverage gap: `V-COMS Inc`, `Navigant Consulting Inc`, `Caribbean Data Services Inc`
  returned no parent match — flagged for manual review in PR2.6 high-value gate

## Outputs Produced

| File | Description |
|---|---|
| `data/staging/processed/enrichment/entity_hierarchy.csv` | Raw USASpending parent lookup results |
| `data/staging/processed/enrichment/parent_collapsed.csv` | 19 parent-level rows with aggregated obligations |
| `data/staging/processed/enrichment/alias_registry.json` | 26 vendor name → canonical entity mappings |
| `data/staging/processed/enrichment/parent_collapse_stats.json` | Machine-readable summary stats |

## Gate Assessment

The previous `parent_uei_rate` global gate (≥ 0.60 threshold) would **block** this dataset
at 35.0% because it does not differentiate government/nonprofit entities — which have no
SAM parent UEI by design — from unresolved corporate entities.

**Recommendation (PR2.6):** Replace the universal `parent_uei_rate` gate with
entity-type-stratified gates:
- `entity_type_assignment_rate` ≥ 0.90 (all entity types classified)
- `government_entity_classification_rate` ≥ 0.95 (gov entities correctly labeled)
- `corporate_parent_uei_rate` ≥ 0.55 (corporate-only UEI resolution rate)
- `high_value_unresolved_review_rate` ≤ 0.10 (unresolved >$500M flagged for manual review)
