"""Fetch PR grants master from USAspending."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_ROOT))

from contract_sweeper.sources.fetchers.usaspending_contracts import USAspendingFetcher


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch PR grants master from USAspending")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--dry-run", action="store_true", default=True, help="Run in dry-run mode (default)")
    parser.add_argument("--execute", action="store_true", help="Execute real API calls (requires USASPENDING_API_KEY)")
    parser.add_argument("--fiscal-years", type=int, nargs="+", help="Fiscal years to fetch")
    args = parser.parse_args()

    dry_run = not args.execute
    fetcher = USAspendingFetcher(args.root, dry_run=dry_run)
    result = fetcher.fetch_assistance(args.fiscal_years)

    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
