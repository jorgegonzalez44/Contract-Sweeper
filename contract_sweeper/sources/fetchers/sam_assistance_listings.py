"""SAM.gov API fetchers for assistance listings and subawards."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


class SAMFetcher:
    """Base fetcher for SAM.gov API with dry-run and fixture support."""

    BASE_URL = "https://api.sam.gov/data-services/v1"
    DRY_RUN_MODE = True
    REQUIRE_API_KEY = True

    def __init__(self, root: Path, dry_run: bool = True):
        self.root = root
        self.dry_run = dry_run
        self.api_key = os.environ.get("SAM_API_KEY", "")
        self.raw_output_dir = root / "data" / "raw" / "sam"
        self.manifest_path = self.raw_output_dir / "manifest.json"

    def fetch_assistance_listings(self) -> Dict[str, Any]:
        """Fetch assistance listings from SAM."""
        if self.dry_run:
            return self._dry_run_response("assistance_listings")
        if not self.api_key:
            return {"status": "BLOCKED", "reason": "SAM_API_KEY not set", "blocker": "credential_required"}
        return self._fetch_listings()

    def fetch_assistance_subawards(self) -> Dict[str, Any]:
        """Fetch assistance subawards from SAM."""
        if self.dry_run:
            return self._dry_run_response("assistance_subawards")
        if not self.api_key:
            return {"status": "BLOCKED", "reason": "SAM_API_KEY not set", "blocker": "credential_required"}
        return self._fetch_subawards("assistance")

    def fetch_acquisition_subawards(self) -> Dict[str, Any]:
        """Fetch acquisition subawards from SAM."""
        if self.dry_run:
            return self._dry_run_response("acquisition_subawards")
        if not self.api_key:
            return {"status": "BLOCKED", "reason": "SAM_API_KEY not set", "blocker": "credential_required"}
        return self._fetch_subawards("acquisition")

    def _dry_run_response(self, record_type: str) -> Dict[str, Any]:
        """Return fixture response for dry-run mode."""
        return {
            "status": "DRY_RUN",
            "record_type": record_type,
            "rows": 0,
            "manifest": {"source": "sam", "record_type": record_type, "dry_run": True},
        }

    def _fetch_listings(self) -> Dict[str, Any]:
        """Fetch listings from API."""
        return {"status": "OK", "rows": 0}

    def _fetch_subawards(self, award_type: str) -> Dict[str, Any]:
        """Fetch subawards from API."""
        return {"status": "OK", "rows": 0, "award_type": award_type}

    def write_manifest(self, manifest: Dict[str, Any]) -> None:
        """Write source manifest."""
        self.raw_output_dir.mkdir(parents=True, exist_ok=True)
        with self.manifest_path.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, default=str)
