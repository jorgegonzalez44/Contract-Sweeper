"""Production promotion guard and gate evaluation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


class ProductionPromotionGuard:
    def __init__(self, root: Path):
        self.root = root
        self.artifact_path = root / "docs" / "production_promotion_guard.yaml"
        self.status_path = root / "data" / "review_queue" / "production_promotion_status.json"

    def load(self) -> Dict[str, str]:
        if self.status_path.exists():
            with self.status_path.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        return {}

    def run(self) -> Dict[str, str]:
        status = {
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
            "downloads_executed": False,
            "rows_ingested": 0,
            "production_inputs_staged": 0,
            "r5_blocked": True,
            "tier0_missing_count": 0,
            "blocked_required_source_count": 0,
        }
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        with self.status_path.open("w", encoding="utf-8") as fh:
            json.dump(status, fh, indent=2)
        return status
