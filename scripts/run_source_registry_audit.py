"""Run source registry audit and report missing tier0 sources."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_ROOT))

from contract_sweeper.governance.source_registry import SourceRegistry


def main() -> int:
    parser = argparse.ArgumentParser(description="Run source registry audit")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()

    registry = SourceRegistry(args.root)
    registry.load()
    missing = [s for s in registry.entries.values() if s.status != "VALIDATED"]
    report = {
        "source_count": len(registry.entries),
        "missing_or_blocked_count": len(missing),
        "missing_sources": [s.source_id for s in missing],
    }
    print(json.dumps(report, indent=2))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
