"""Run production promotion guard and emit status artifacts."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_ROOT))

from contract_sweeper.validation.production_promotion_guard import ProductionPromotionGuard


def main() -> int:
    parser = argparse.ArgumentParser(description="Run production promotion guard")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()

    guard = ProductionPromotionGuard(args.root)
    status = guard.run()
    for k, v in status.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
