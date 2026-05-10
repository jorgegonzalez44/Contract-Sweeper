"""Fetch federal account backbone from Fiscal Data."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_ROOT))

from contract_sweeper.sources.fetchers.fiscal_data_accounts import FiscalDataFetcher


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch federal account backbone from Fiscal Data")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--dry-run", action="store_true", default=True, help="Run in dry-run mode (default)")
    parser.add_argument("--execute", action="store_true", help="Execute real API calls")
    args = parser.parse_args()

    dry_run = not args.execute
    fetcher = FiscalDataFetcher(args.root, dry_run=dry_run)

    result_accounts = fetcher.fetch_federal_accounts()
    result_appropriations = fetcher.fetch_account_appropriations()

    result = {
        "status": "OK" if result_accounts["status"] == "DRY_RUN" else result_accounts["status"],
        "records": {
            "federal_accounts": result_accounts,
            "account_appropriations": result_appropriations,
        },
    }
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
