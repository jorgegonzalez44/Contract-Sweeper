"""Tests for USAspending fetchers."""
from pathlib import Path
from tempfile import TemporaryDirectory

from contract_sweeper.sources.fetchers.usaspending_contracts import USAspendingFetcher


def test_usaspending_fetcher_dry_run_contracts():
    """Test dry-run mode for contracts fetcher."""
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fetcher = USAspendingFetcher(root, dry_run=True)
        result = fetcher.fetch_contracts()

        assert result["status"] == "DRY_RUN"
        assert result["record_type"] == "contracts"
        assert result["rows"] == 0


def test_usaspending_fetcher_dry_run_assistance():
    """Test dry-run mode for assistance fetcher."""
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fetcher = USAspendingFetcher(root, dry_run=True)
        result = fetcher.fetch_assistance()

        assert result["status"] == "DRY_RUN"
        assert result["record_type"] == "assistance"
        assert result["rows"] == 0


def test_usaspending_fetcher_dry_run_award_accounts():
    """Test dry-run mode for award accounts fetcher."""
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fetcher = USAspendingFetcher(root, dry_run=True)
        result = fetcher.fetch_award_accounts()

        assert result["status"] == "DRY_RUN"
        assert result["record_type"] == "award_accounts"


def test_usaspending_fetcher_blocked_without_key():
    """Test that real execution is blocked without API key."""
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fetcher = USAspendingFetcher(root, dry_run=False)
        result = fetcher.fetch_contracts()

        assert result["status"] == "BLOCKED"
        assert "API_KEY" in result["reason"] or "not set" in result["reason"]
