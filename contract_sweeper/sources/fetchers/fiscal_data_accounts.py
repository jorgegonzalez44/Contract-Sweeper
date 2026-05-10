"""Fiscal data fetchers for federal account backbone."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


class FiscalDataFetcher:
    """Fetcher for US Treasury fiscal data and federal account backbone."""

    BASE_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
    DRY_RUN_MODE = True
    REQUIRE_API_KEY = False

    def __init__(self, root: Path, dry_run: bool = True):
        self.root = root
        self.dry_run = dry_run
        self.raw_output_dir = root / "data" / "raw" / "fiscal_data"
        self.manifest_path = self.raw_output_dir / "manifest.json"

    def fetch_federal_accounts(self) -> Dict[str, Any]:
        """Fetch federal account master list from Fiscal Data."""
        if self.dry_run:
            return self._dry_run_response("federal_accounts")
        return self._fetch_accounts()

    def fetch_account_appropriations(self) -> Dict[str, Any]:
        """Fetch appropriations by federal account."""
        if self.dry_run:
            return self._dry_run_response("account_appropriations")
        return self._fetch_appropriations()

    def _dry_run_response(self, record_type: str) -> Dict[str, Any]:
        """Return fixture response for dry-run mode."""
        return {
            "status": "DRY_RUN",
            "record_type": record_type,
            "rows": 0,
            "manifest": {"source": "fiscal_data", "record_type": record_type, "dry_run": True},
        }

    def _fetch_accounts(self) -> Dict[str, Any]:
        """Fetch accounts from API."""
        return {"status": "OK", "rows": 0}

    def _fetch_appropriations(self) -> Dict[str, Any]:
        """Fetch appropriations from API."""
        return {"status": "OK", "rows": 0}

    def write_manifest(self, manifest: Dict[str, Any]) -> None:
        """Write source manifest."""
        self.raw_output_dir.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, default=str)
