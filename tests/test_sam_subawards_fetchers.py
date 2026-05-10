"""Tests for SAM subawards fetchers."""
from pathlib import Path
from tempfile import TemporaryDirectory

from contract_sweeper.sources.fetchers.sam_assistance_listings import SAMFetcher


def test_sam_fetcher_dry_run_assistance_subawards():
    """Test dry-run mode for assistance subawards fetcher."""
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fetcher = SAMFetcher(root, dry_run=True)
        result = fetcher.fetch_assistance_subawards()

        assert result["status"] == "DRY_RUN"
        assert result["record_type"] == "assistance_subawards"
        assert result["rows"] == 0


def test_sam_fetcher_dry_run_acquisition_subawards():
    """Test dry-run mode for acquisition subawards fetcher."""
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fetcher = SAMFetcher(root, dry_run=True)
        result = fetcher.fetch_acquisition_subawards()

        assert result["status"] == "DRY_RUN"
        assert result["record_type"] == "acquisition_subawards"


def test_sam_fetcher_blocked_without_key():
    """Test that real execution is blocked without API key."""
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fetcher = SAMFetcher(root, dry_run=False)
        result = fetcher.fetch_assistance_subawards()

        assert result["status"] == "BLOCKED"
        assert result["blocker"] == "credential_required"
