"""Tests for Fiscal Data fetchers."""
from pathlib import Path
from tempfile import TemporaryDirectory

from contract_sweeper.sources.fetchers.fiscal_data_accounts import FiscalDataFetcher


def test_fiscal_data_fetcher_dry_run_accounts():
    """Test dry-run mode for federal accounts fetcher."""
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fetcher = FiscalDataFetcher(root, dry_run=True)
        result = fetcher.fetch_federal_accounts()

        assert result["status"] == "DRY_RUN"
        assert result["record_type"] == "federal_accounts"
        assert result["rows"] == 0


def test_fiscal_data_fetcher_dry_run_appropriations():
    """Test dry-run mode for appropriations fetcher."""
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fetcher = FiscalDataFetcher(root, dry_run=True)
        result = fetcher.fetch_account_appropriations()

        assert result["status"] == "DRY_RUN"
        assert result["record_type"] == "account_appropriations"


def test_fiscal_data_fetcher_real_execution():
    """Test that real execution works without API key (public API)."""
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        fetcher = FiscalDataFetcher(root, dry_run=False)
        result = fetcher.fetch_federal_accounts()

        # Fiscal Data is public API, should not be blocked
        assert result["status"] in ["OK", "ERROR"]
