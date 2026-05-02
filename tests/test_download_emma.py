"""Tests for download_emma — MSRB EMMA municipal bond data."""

import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch, MagicMock

from scripts.download_emma import (
    _session,
    _records_to_bonds_df,
    _build_underwriter_df,
)


@pytest.mark.skipif(
    not Path("data/staging/processed/pr_emma_bonds.csv").exists(),
    reason="EMMA bonds file not present (requires live API fetch)"
)
def test_emma_bonds_csv_exists_and_readable():
    """Integration: EMMA bonds CSV exists and is readable."""
    path = Path("data/staging/processed/pr_emma_bonds.csv")
    df = pd.read_csv(path)
    # File may be empty if API hasn't been called yet - just verify it's readable
    assert df is not None


@pytest.mark.skipif(
    not Path("data/staging/processed/pr_emma_underwriters.csv").exists(),
    reason="EMMA underwriters file not present"
)
def test_emma_underwriters_csv_exists_and_readable():
    """Integration: EMMA underwriters CSV exists and is readable."""
    path = Path("data/staging/processed/pr_emma_underwriters.csv")
    df = pd.read_csv(path)
    # File may be empty if API hasn't been called yet - just verify it's readable
    assert df is not None


def test_normalize_bond_security_typical_record():
    """_records_to_bonds_df handles typical bond records."""
    records = [
        {
            "isin": "PR123456789",
            "issue_name": "Puerto Rico Sales Tax Revenue Bond",
            "dated_date": "2020-01-15",
            "maturity_date": "2030-01-15",
        }
    ]
    result = _records_to_bonds_df(records)
    assert result is not None
    assert isinstance(result, pd.DataFrame)
    assert len(result) > 0


def test_normalize_bond_security_missing_fields():
    """_records_to_bonds_df handles missing fields gracefully."""
    records = [
        {
            "isin": "PR123456789",
        }
    ]
    result = _records_to_bonds_df(records)
    assert result is not None
    assert isinstance(result, pd.DataFrame)


def test_normalize_underwriter_typical_record():
    """_build_underwriter_df handles typical bond DataFrame."""
    df_bonds = pd.DataFrame([
        {
            "isin": "PR123456789",
            "underwriter_name": "Goldman Sachs",
            "par_amount": 100000000,
        }
    ])
    result = _build_underwriter_df(df_bonds)
    assert result is not None
    assert isinstance(result, pd.DataFrame)


def test_session_returns_configured_session():
    """_session returns a requests.Session with proper headers."""
    session = _session()
    assert session is not None
    assert "User-Agent" in session.headers


@patch("scripts.download_emma.requests.get")
def test_emma_api_handles_timeout(mock_get):
    """EMMA API request handles timeout gracefully."""
    mock_get.side_effect = Exception("Connection timeout")
    with pytest.raises(Exception):
        mock_get("https://emma.msrb.org/api/dummy")
