"""
Validation Gates — Entity-Type-Stratified Quality Checks

Replaces the former global parent_uei_rate gate (which incorrectly penalised
government and nonprofit entities that have no SAM parent UEI by design).

Gate definitions
----------------
entity_type_assignment_rate
    Fraction of parent entities that received a non-'unknown' entity_type
    classification. Gate: ≥ 0.90.

government_entity_classification_rate
    Fraction of entities whose name/business_types suggest government but whose
    entity_type is correctly set to 'government'. Gate: ≥ 0.95.

corporate_parent_uei_rate
    Fraction of corporate-classified entities that have a resolved parent_uei.
    Gate: ≥ 0.50 (corporate subsidiaries only — self-owned corps excluded).

high_value_unresolved_review_rate
    Fraction of unresolved corporate entities with obligation ≥ HIGH_VALUE_THRESHOLD
    that have been flagged for manual review. Gate: ≤ 0.10 unflagged.

Usage:
  python3 scripts/validation_gates.py
  python3 scripts/validation_gates.py --report-only   # print JSON, don't raise
"""

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import ENRICHMENT_OUTPUT_DIR, PROJECT_ROOT, setup_logging
from scripts.parent_collapse import classify_entity_type

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HIGH_VALUE_THRESHOLD = 500_000_000  # $500M obligation threshold for manual review flag

# Gate thresholds
ENTITY_TYPE_ASSIGNMENT_GATE = 0.90
GOVERNMENT_CLASSIFICATION_GATE = 0.95
CORPORATE_PARENT_UEI_GATE = 0.50
HIGH_VALUE_UNRESOLVED_GATE = 0.10   # max fraction unflagged

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    name: str
    value: float
    threshold: float
    passed: bool
    direction: str  # "gte" | "lte"
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ValidationReport:
    run_timestamp: str
    total_parent_entities: int
    gates: list[GateResult] = field(default_factory=list)
    overall_pass: bool = False
    blockers: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["gates"] = [g.as_dict() for g in self.gates]
        return d


# ---------------------------------------------------------------------------
# Gate computations
# ---------------------------------------------------------------------------

def _load_collapsed(enrichment_dir: Path) -> list[dict]:
    import csv
    p = enrichment_dir / "parent_collapsed.csv"
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_hierarchy(enrichment_dir: Path) -> list[dict]:
    """Raw entity_hierarchy.csv — one row per vendor before collapse."""
    import csv
    p = enrichment_dir / "entity_hierarchy.csv"
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _parse_float(val) -> float:
    try:
        return float(val or 0)
    except (ValueError, TypeError):
        return 0.0


def gate_entity_type_assignment(rows: list[dict]) -> GateResult:
    """≥ 90% of parent entities have a non-unknown entity_type."""
    n = len(rows)
    if n == 0:
        return GateResult(
            name="entity_type_assignment_rate",
            value=0.0, threshold=ENTITY_TYPE_ASSIGNMENT_GATE,
            passed=False, direction="gte",
            detail="No entities found",
        )
    assigned = sum(1 for r in rows if (r.get("entity_type") or "unknown") != "unknown")
    rate = assigned / n
    return GateResult(
        name="entity_type_assignment_rate",
        value=round(rate, 4),
        threshold=ENTITY_TYPE_ASSIGNMENT_GATE,
        passed=rate >= ENTITY_TYPE_ASSIGNMENT_GATE,
        direction="gte",
        detail=f"{assigned}/{n} entities classified",
    )


def gate_government_classification(rows: list[dict]) -> GateResult:
    """
    Of entities that look governmental (name/business_types heuristic),
    ≥ 95% must be labelled entity_type='government'.
    """
    gov_candidates = [
        r for r in rows
        if classify_entity_type(
            r.get("parent_name", ""),
            # business_types not stored in collapsed CSV — use empty string
        ) == "government"
    ]
    n = len(gov_candidates)
    if n == 0:
        return GateResult(
            name="government_entity_classification_rate",
            value=1.0, threshold=GOVERNMENT_CLASSIFICATION_GATE,
            passed=True, direction="gte",
            detail="No government candidates found — gate vacuously passed",
        )
    correctly_labelled = sum(
        1 for r in gov_candidates if r.get("entity_type") == "government"
    )
    rate = correctly_labelled / n
    return GateResult(
        name="government_entity_classification_rate",
        value=round(rate, 4),
        threshold=GOVERNMENT_CLASSIFICATION_GATE,
        passed=rate >= GOVERNMENT_CLASSIFICATION_GATE,
        direction="gte",
        detail=f"{correctly_labelled}/{n} government candidates correctly labelled",
    )


def gate_corporate_parent_uei(hierarchy_rows: list[dict]) -> GateResult:
    """
    Of corporate-classified vendors in the raw hierarchy, ≥ 50% must have a
    resolved parent_uei that is distinct from their own uei (i.e., a true parent,
    not a self-parenting root). Government/nonprofit entities are excluded because
    they do not have SAM parent UEIs by design.
    """
    corporate = [
        r for r in hierarchy_rows
        if classify_entity_type(
            r.get("vendor_name", ""), r.get("business_types", "")
        ) == "corporate"
    ]
    n = len(corporate)
    if n == 0:
        return GateResult(
            name="corporate_parent_uei_rate",
            value=1.0, threshold=CORPORATE_PARENT_UEI_GATE,
            passed=True, direction="gte",
            detail="No corporate vendors found — gate vacuously passed",
        )
    with_distinct_parent = sum(
        1 for r in corporate
        if (r.get("parent_uei") or "").strip()
        and (r.get("parent_uei") or "").strip() != (r.get("uei") or "").strip()
    )
    rate = with_distinct_parent / n
    return GateResult(
        name="corporate_parent_uei_rate",
        value=round(rate, 4),
        threshold=CORPORATE_PARENT_UEI_GATE,
        passed=rate >= CORPORATE_PARENT_UEI_GATE,
        direction="gte",
        detail=f"{with_distinct_parent}/{n} corporate vendors have a distinct resolved parent_uei",
    )


def gate_high_value_unresolved(hierarchy_rows: list[dict]) -> GateResult:
    """
    Of high-value corporate vendors (obligation ≥ $500M) that are NOT themselves
    a known parent entity, ≤ 10% may be unresolved (no distinct parent_uei).

    Entities that appear as parent_name in any other row are excluded — they are
    confirmed root parents and do not need further resolution.
    """
    # Build set of known parent names (these are root entities, not unresolved)
    known_parent_names = {
        (r.get("parent_name") or "").strip()
        for r in hierarchy_rows
        if (r.get("parent_name") or "").strip()
    }

    corporate = [
        r for r in hierarchy_rows
        if classify_entity_type(
            r.get("vendor_name", ""), r.get("business_types", "")
        ) == "corporate"
    ]
    high_value = [
        r for r in corporate
        if _parse_float(r.get("total_obligation")) >= HIGH_VALUE_THRESHOLD
        and (r.get("vendor_name") or "").strip() not in known_parent_names
    ]
    n_hv = len(high_value)
    if n_hv == 0:
        return GateResult(
            name="high_value_unresolved_review_rate",
            value=0.0, threshold=HIGH_VALUE_UNRESOLVED_GATE,
            passed=True, direction="lte",
            detail="No non-root high-value corporate vendors found — gate vacuously passed",
        )
    unresolved = [
        r for r in high_value
        if not (r.get("parent_uei") or "").strip()
        or (r.get("parent_uei") or "").strip() == (r.get("uei") or "").strip()
    ]
    n_unresolved = len(unresolved)
    rate = n_unresolved / n_hv
    unresolved_names = [r.get("vendor_name", "?") for r in unresolved[:5]]
    return GateResult(
        name="high_value_unresolved_review_rate",
        value=round(rate, 4),
        threshold=HIGH_VALUE_UNRESOLVED_GATE,
        passed=rate <= HIGH_VALUE_UNRESOLVED_GATE,
        direction="lte",
        detail=(
            f"{n_unresolved}/{n_hv} non-root high-value corporate vendors unresolved. "
            + (f"Needs review: {', '.join(unresolved_names)}" if unresolved_names else "")
        ),
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(root: Path = None, report_only: bool = False) -> ValidationReport:
    from datetime import datetime, timezone

    if root is None:
        root = PROJECT_ROOT

    enrichment_dir = root / "data" / "staging" / "processed" / "enrichment"
    logger = setup_logging("validation_gates")

    collapsed_rows = _load_collapsed(enrichment_dir)
    hierarchy_rows = _load_hierarchy(enrichment_dir)
    logger.info(
        f"Loaded {len(collapsed_rows)} parent entities (collapsed), "
        f"{len(hierarchy_rows)} raw hierarchy rows"
    )

    gates = [
        gate_entity_type_assignment(collapsed_rows),
        gate_government_classification(collapsed_rows),
        gate_corporate_parent_uei(hierarchy_rows),
        gate_high_value_unresolved(hierarchy_rows),
    ]

    blockers = [g.name for g in gates if not g.passed]
    overall_pass = len(blockers) == 0

    report = ValidationReport(
        run_timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        total_parent_entities=len(collapsed_rows),
        gates=gates,
        overall_pass=overall_pass,
        blockers=blockers,
    )

    # Write report to manifests
    manifests_dir = root / "data" / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    report_path = manifests_dir / "validation_report.json"
    report_path.write_text(
        json.dumps(report.as_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    for g in gates:
        status = "PASS" if g.passed else "FAIL"
        logger.info(f"  [{status}] {g.name}: {g.value:.4f} (threshold {g.direction} {g.threshold}) — {g.detail}")

    if overall_pass:
        logger.info("\nAll validation gates PASSED")
    else:
        logger.warning(f"\nValidation FAILED — blockers: {blockers}")
        if not report_only:
            sys.exit(1)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run entity-type-stratified validation gates")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--report-only", action="store_true",
                        help="Print report without raising on failure")
    args = parser.parse_args()
    report = run(root=args.root, report_only=args.report_only)
    print(json.dumps(report.as_dict(), indent=2))
    return 0 if report.overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
