"""
Parent Entity Collapse — SAM / USASpending Hierarchy Resolution

Reads entity_hierarchy.csv (produced by entity_resolution.py) and
vendor_uei_index.csv (produced by sam_enrichment.py), then:

  1. Collapses child entities under their resolved parent.
  2. Produces parent_collapsed.csv — one row per parent entity with
     aggregated obligation, children list, and resolution stats.
  3. Writes alias_registry.json — maps every observed vendor name
     variant to its canonical (parent) entity name + UEI.

Usage:
  python3 scripts/parent_collapse.py
  python3 scripts/parent_collapse.py --root /path/to/project
"""

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import ENRICHMENT_OUTPUT_DIR, PROJECT_ROOT, setup_logging

# ---------------------------------------------------------------------------
# Entity-type heuristics (mirrors PR2.6 classification logic)
# ---------------------------------------------------------------------------

_GOV_KEYWORDS = re.compile(
    r"\b(MUNICIPIO|MUNICIPALITY|GOVERNMENT|ESTADO|COMMONWEALTH|DEPARTMENT|DEPT|AUTHORITY|"
    r"ADMINISTRATION|ADMINISTRATION|JUNTA|OFICINA|AGENCIA|AGENCY|BOARD|COMMISSION|"
    r"PRASA|PREPA|ACT|AUTORIDAD|PUBLIC|FEDERAL|STATE|COUNTY|CITY|TOWN|SCHOOL|DISTRICT)\b",
    re.IGNORECASE,
)
_NONPROFIT_KEYWORDS = re.compile(
    r"\b(UNIVERSITY|UNIVERSIDAD|COLLEGE|HOSPITAL|HEALTH|FOUNDATION|FUNDACION|"
    r"ASSOCIATION|ASOCIACION|NONPROFIT|NON-PROFIT|CHURCH|IGLESIA|TRUST|FUND)\b",
    re.IGNORECASE,
)


def classify_entity_type(name: str, business_types: str = "") -> str:
    """Return 'government', 'nonprofit', 'corporate', or 'unknown'."""
    combined = f"{name} {business_types}".upper()
    bt_lower = business_types.lower()
    if any(kw in bt_lower for kw in ("government", "tribal", "municipality", "state")):
        return "government"
    if any(kw in bt_lower for kw in ("nonprofit", "non-profit", "educational", "hospital")):
        return "nonprofit"
    if _GOV_KEYWORDS.search(combined):
        return "government"
    if _NONPROFIT_KEYWORDS.search(combined):
        return "nonprofit"
    if any(kw in bt_lower for kw in ("corporation", "limited liability", "partnership", "company")):
        return "corporate"
    return "corporate"  # default for unrecognised commercial entities


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load_hierarchy(enrichment_dir: Path, logger) -> list[dict]:
    p = enrichment_dir / "entity_hierarchy.csv"
    if not p.exists():
        logger.warning(f"  entity_hierarchy.csv not found at {p} — using empty list")
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_uei_index(enrichment_dir: Path, logger) -> dict[str, dict]:
    """Returns vendor_name → row dict from vendor_uei_index.csv."""
    p = enrichment_dir / "vendor_uei_index.csv"
    if not p.exists():
        logger.warning(f"  vendor_uei_index.csv not found at {p} — proceeding without SAM index")
        return {}
    index: dict[str, dict] = {}
    with open(p, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            index[row["vendor_name"]] = row
    return index


# ---------------------------------------------------------------------------
# Collapse logic
# ---------------------------------------------------------------------------

def _parent_key(row: dict) -> tuple[str, str]:
    """Return (parent_uei, parent_name) if resolved, else fall back to self."""
    puei = (row.get("parent_uei") or "").strip()
    pname = (row.get("parent_name") or "").strip()
    if puei and pname:
        return puei, pname
    # No parent resolved — entity is its own root
    uei = (row.get("uei") or "").strip()
    vname = (row.get("vendor_name") or row.get("sam_name") or "").strip()
    return uei, vname


def collapse(hierarchy_rows: list[dict], uei_index: dict[str, dict], logger) -> tuple[list[dict], dict]:
    """
    Returns:
      collapsed_rows: list of parent-level dicts
      alias_registry: {vendor_name_variant: {canonical_name, canonical_uei, entity_type}}
    """
    # Group children under parent key
    parents: dict[tuple, dict] = {}   # (puei, pname) → aggregated data
    alias_registry: dict[str, dict] = {}

    for row in hierarchy_rows:
        pkey = _parent_key(row)
        puei, pname = pkey

        vendor = (row.get("vendor_name") or "").strip()
        obligation = float(row.get("total_obligation") or 0)
        records = int(row.get("record_count") or 0)
        bt = row.get("business_types") or ""
        own_uei = (row.get("uei") or "").strip()

        if pkey not in parents:
            # Seed with SAM index data when available
            sam_row = uei_index.get(pname) or uei_index.get(vendor) or {}
            etype = classify_entity_type(pname or vendor, bt or sam_row.get("status", ""))
            parents[pkey] = {
                "parent_uei": puei,
                "parent_name": pname or vendor,
                "entity_type": etype,
                "total_obligation": 0.0,
                "total_records": 0,
                "child_count": 0,
                "children": [],
                "child_ueis": [],
                "resolution_source": row.get("source", ""),
            }

        entry = parents[pkey]
        entry["total_obligation"] += obligation
        entry["total_records"] += records
        entry["child_count"] += 1
        if vendor and vendor not in entry["children"]:
            entry["children"].append(vendor)
        if own_uei and own_uei not in entry["child_ueis"]:
            entry["child_ueis"].append(own_uei)

        # Register alias
        canonical_name = pname or vendor
        canonical_uei = puei or own_uei
        etype = entry["entity_type"]
        for alias in {vendor, pname} - {""}:
            alias_registry[alias] = {
                "canonical_name": canonical_name,
                "canonical_uei": canonical_uei,
                "entity_type": etype,
            }

    # Sort by obligation descending
    collapsed_rows = sorted(
        parents.values(),
        key=lambda x: x["total_obligation"],
        reverse=True,
    )

    # Flatten children lists for CSV serialisation
    for r in collapsed_rows:
        r["children"] = "; ".join(r["children"])
        r["child_ueis"] = "; ".join(r["child_ueis"])

    return collapsed_rows, alias_registry


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

_COLLAPSED_FIELDS = [
    "parent_uei", "parent_name", "entity_type",
    "total_obligation", "total_records", "child_count",
    "children", "child_ueis", "resolution_source",
]


def write_collapsed(rows: list[dict], output_dir: Path, logger) -> Path:
    out = output_dir / "parent_collapsed.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_COLLAPSED_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    logger.info(f"  parent_collapsed.csv  → {len(rows)} parent entities")
    return out


def write_alias_registry(registry: dict, output_dir: Path, logger) -> Path:
    out = output_dir / "alias_registry.json"
    out.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"  alias_registry.json   → {len(registry)} alias entries")
    return out


# ---------------------------------------------------------------------------
# Stats helper (used by report generator)
# ---------------------------------------------------------------------------

def compute_stats(collapsed_rows: list[dict], hierarchy_rows: list[dict]) -> dict:
    total = len(hierarchy_rows)
    with_parent = sum(
        1 for r in hierarchy_rows
        if (r.get("parent_uei") or "").strip() and (r.get("parent_name") or "").strip()
    )
    gov = sum(1 for r in collapsed_rows if r.get("entity_type") == "government")
    nonprofit = sum(1 for r in collapsed_rows if r.get("entity_type") == "nonprofit")
    corporate = sum(1 for r in collapsed_rows if r.get("entity_type") == "corporate")
    unknown = sum(1 for r in collapsed_rows if r.get("entity_type") == "unknown")
    return {
        "total_vendors": total,
        "total_parent_entities": len(collapsed_rows),
        "vendors_with_parent_uei": with_parent,
        "parent_uei_rate": round(with_parent / max(total, 1), 4),
        "entity_type_counts": {
            "government": gov,
            "nonprofit": nonprofit,
            "corporate": corporate,
            "unknown": unknown,
        },
        "entity_type_assignment_rate": round(
            (gov + nonprofit + corporate) / max(len(collapsed_rows), 1), 4
        ),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(root: Path = None) -> dict:
    if root is None:
        root = PROJECT_ROOT

    enrichment_dir = root / "data" / "staging" / "processed" / "enrichment"
    enrichment_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("parent_collapse")
    logger.info("Parent collapse — loading inputs")

    hierarchy_rows = _load_hierarchy(enrichment_dir, logger)
    uei_index = _load_uei_index(enrichment_dir, logger)

    logger.info(f"  {len(hierarchy_rows)} hierarchy rows, {len(uei_index)} SAM index entries")

    collapsed, alias_registry = collapse(hierarchy_rows, uei_index, logger)

    write_collapsed(collapsed, enrichment_dir, logger)
    write_alias_registry(alias_registry, enrichment_dir, logger)

    stats = compute_stats(collapsed, hierarchy_rows)
    stats_path = enrichment_dir / "parent_collapse_stats.json"
    stats_path.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    logger.info(
        f"\nCollapse complete — {stats['total_parent_entities']} parent entities, "
        f"parent_uei_rate={stats['parent_uei_rate']:.1%}"
    )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Collapse child entities under parent UEI hierarchy")
    parser.add_argument("--root", type=Path, default=None, help="Project root override")
    args = parser.parse_args()
    run(root=args.root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
