"""Fetch PR subawards master from SAM.gov."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_ROOT))

from contract_sweeper.sources.fetchers.sam_assistance_listings import SAMFetcher


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch PR subawards master from SAM.gov")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--dry-run", action="store_true", default=True, help="Run in dry-run mode (default)")
    parser.add_argument("--execute", action="store_true", help="Execute real API calls (requires SAM_API_KEY)")
    args = parser.parse_args()

    dry_run = not args.execute
    fetcher = SAMFetcher(args.root, dry_run=dry_run)
    
    # Fetch both assistance and acquisition subawards
    result_assistance = fetcher.fetch_assistance_subawards()
    result_acquisition = fetcher.fetch_acquisition_subawards()

    result = {
        "status": "OK" if result_assistance["status"] == "DRY_RUN" else result_assistance["status"],
        "records": {
            "assistance_subawards": result_assistance,
            "acquisition_subawards": result_acquisition,
        },
    }
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
