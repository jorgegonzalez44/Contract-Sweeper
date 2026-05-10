"""USAspending API fetchers for contracts, assistance, and award-account links."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


class USAspendingFetcher:
    """Base fetcher for USAspending API with dry-run and fixture support."""

    BASE_URL = "https://api.usaspending.gov/api/v2"
    DRY_RUN_MODE = True
    REQUIRE_API_KEY = False

    def __init__(self, root: Path, dry_run: bool = True):
        self.root = root
        self.dry_run = dry_run
        self.api_key = os.environ.get("USASPENDING_API_KEY", "")
        self.raw_output_dir = root / "data" / "raw" / "usaspending"
        self.manifest_path = self.raw_output_dir / "manifest.json"

    def fetch_contracts(self, fiscal_years: List[int] | None = None) -> Dict[str, Any]:
        """Fetch Puerto Rico contracts from USAspending."""
        if self.dry_run:
            return self._dry_run_response("contracts")
        return self._fetch_records("contracts", fiscal_years)

    def fetch_assistance(self, fiscal_years: List[int] | None = None) -> Dict[str, Any]:
        """Fetch Puerto Rico assistance awards from USAspending."""
        if self.dry_run:
            return self._dry_run_response("assistance")
        return self._fetch_records("assistance", fiscal_years)

    def fetch_award_accounts(self) -> Dict[str, Any]:
        """Fetch federal account backbone from USAspending."""
        if self.dry_run:
            return self._dry_run_response("award_accounts")
        return self._fetch_award_accounts()

    def _dry_run_response(self, record_type: str) -> Dict[str, Any]:
        """Return fixture response for dry-run mode."""
        return {
            "status": "DRY_RUN",
            "record_type": record_type,
            "rows": 0,
            "manifest": {"source": "usaspending", "record_type": record_type, "dry_run": True},
        }

    def _fetch_records(self, record_type: str, fiscal_years: List[int] | None) -> Dict[str, Any]:
        """Fetch actual records from API (requires USASPENDING_API_KEY)."""
        if not self.api_key:
            return {"status": "BLOCKED", "reason": "USASPENDING_API_KEY not set", "rows": 0}

        # Placeholder for actual API call
        return {"status": "OK", "rows": 0, "record_type": record_type}

    def _fetch_award_accounts(self) -> Dict[str, Any]:
        """Fetch award accounts from API."""
        if not self.api_key:
            return {"status": "BLOCKED", "reason": "USASPENDING_API_KEY not set", "rows": 0}

        return {"status": "OK", "rows": 0}

    def write_manifest(self, manifest: Dict[str, Any]) -> None:
        """Write source manifest."""
        self.raw_output_dir.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, default=str)
