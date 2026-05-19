"""
Generate source_coverage_actuals.json from data/staging/processed/ CSVs.

Reads data/source_registry.yaml for source definitions, then checks each
source's master CSV for existence and row count.  Writes a JSON manifest
used by validation_gates.py gate_source_coverage.

Outputs:
  data/manifests/source_coverage_actuals.json

Usage:
  python3 scripts/generate_source_coverage_actuals.py
  python3 scripts/generate_source_coverage_actuals.py --force
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from scripts.config import PROJECT_ROOT, setup_logging

PROCESSED_DIR  = PROJECT_ROOT / "data" / "staging" / "processed"
MANIFESTS_DIR  = PROJECT_ROOT / "data" / "manifests"
REGISTRY_PATH  = PROJECT_ROOT / "data" / "source_registry.yaml"
OUTPUT_PATH    = MANIFESTS_DIR / "source_coverage_actuals.json"


def _count_csv_rows(path):
    """Return number of data rows (excluding header) in a CSV, or 0 if unreadable."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            total = sum(1 for _ in f)
        return max(0, total - 1)
    except OSError:
        return 0


def _load_registry(path):
    """Load source_registry.yaml; return empty dict on failure."""
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def compute_actuals(processed_dir, registry):
    """
    For each source in registry['sources'], check its master CSV and compute
    coverage_rate = 1.0 if row_count > 0 else 0.0.

    Returns a dict keyed by source name.
    """
    sources_cfg = registry.get("sources", {})
    actuals = {}
    for name, cfg in sources_cfg.items():
        master = cfg.get("master", "")
        path = processed_dir / master if master else None
        if path and path.exists():
            row_count = _count_csv_rows(path)
            file_present = True
        else:
            row_count = 0
            file_present = False
        coverage_rate = 1.0 if row_count > 0 else 0.0
        actuals[name] = {
            "label": cfg.get("label", name),
            "master": master,
            "file_present": file_present,
            "row_count": row_count,
            "coverage_rate": coverage_rate,
            "coverage_target": cfg.get("coverage_target", 1.0),
            "meets_target": coverage_rate >= cfg.get("coverage_target", 1.0),
        }
    return actuals


def run(root=None, force=False):
    root = Path(root or PROJECT_ROOT)
    processed_dir = root / "data" / "staging" / "processed"
    manifests_dir = root / "data" / "manifests"
    registry_path = root / "data" / "source_registry.yaml"
    output_path   = manifests_dir / "source_coverage_actuals.json"

    logger = setup_logging("generate_source_coverage_actuals")
    manifests_dir.mkdir(parents=True, exist_ok=True)

    if output_path.exists() and not force:
        logger.info(f"  source_coverage_actuals.json exists — skipping (use --force).")
        with open(output_path, encoding="utf-8") as f:
            data = json.load(f)
        return {"sources": len(data.get("sources", {})), "status": "CACHED"}

    registry = _load_registry(registry_path)
    if not registry:
        logger.warning(f"  Could not load {registry_path.name} — writing empty actuals.")

    actuals = compute_actuals(processed_dir, registry)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": actuals,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    present = sum(1 for v in actuals.values() if v["file_present"])
    total   = len(actuals)
    logger.info(f"  Source coverage: {present}/{total} sources present → {output_path.name}")
    return {"sources": total, "present": present, "status": "OK"}


def main():
    parser = argparse.ArgumentParser(description="Generate source coverage actuals manifest")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nSource coverage actuals: {result.get('present', 0)}/{result.get('sources', 0)} sources present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
