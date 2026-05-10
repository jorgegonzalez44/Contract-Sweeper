"""Production status gate for global pipeline validation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run production status gate")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()

    status_file = args.root / "data" / "review_queue" / "production_promotion_status.json"
    if not status_file.exists():
        print("production promotion status artifact missing")
        return 1

    with status_file.open("r", encoding="utf-8") as fh:
        status = json.load(fh)

    required = {
        "production_status": "NON_PRODUCTION_DIAGNOSTIC",
        "downloads_executed": False,
        "rows_ingested": 0,
        "production_inputs_staged": 0,
        "r5_blocked": True,
    }
    mismatches = [k for k, v in required.items() if status.get(k) != v]
    if mismatches:
        print(f"production status gate failed: {mismatches}")
        return 1
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
