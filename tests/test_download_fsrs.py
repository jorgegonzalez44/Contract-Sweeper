"""Tests for download_fsrs — FSRS subcontract data fetching."""

import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile
import os

from scripts.download_fsrs import (
    fetch_fsrs_pr_subcontracts,
    download_fsrs_subcontracts,
)


@patch("scripts.download_fsrs.requests.Session")
def test_fetch_fsrs_successful_csv_response(mock_session_class):
    """fetch_fsrs_pr_subcontracts saves CSV on successful form submission."""
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.headers = {"Content-Type": "text/csv"}
    mock_response.text = "piid,contractor_name,award_amount\nP001,Contractor A,10000\nP002,Contractor B,20000\n"
    mock_response.raise_for_status.return_value = None
    mock_session.post.return_value = mock_response
    
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        temp_path = Path(f.name)
    
    try:
        success, row_count = fetch_fsrs_pr_subcontracts(temp_path, session=mock_session)
        assert success is True
        assert row_count == 2
        assert temp_path.exists()
    finally:
        temp_path.unlink(missing_ok=True)


@patch("scripts.download_fsrs.requests.Session")
def test_fetch_fsrs_handles_api_failure(mock_session_class):
    """fetch_fsrs_pr_subcontracts returns False on API error."""
    mock_session = MagicMock()
    mock_session.post.side_effect = Exception("Connection timeout")
    
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        temp_path = Path(f.name)
    
    try:
        success, row_count = fetch_fsrs_pr_subcontracts(temp_path, session=mock_session)
        assert success is False
        assert row_count == 0
    finally:
        temp_path.unlink(missing_ok=True)


@patch("scripts.download_fsrs.fetch_fsrs_pr_subcontracts")
def test_download_fsrs_subcontracts_success(mock_fetch):
    """download_fsrs_subcontracts returns success dict on fetch success."""
    mock_fetch.return_value = (True, 150)
    result = download_fsrs_subcontracts()
    assert result["status"] == "OK"
    assert result["rows"] == 150


@patch("scripts.download_fsrs.fetch_fsrs_pr_subcontracts")
def test_download_fsrs_subcontracts_fallback_to_manual(mock_fetch):
    """download_fsrs_subcontracts falls back to manual on fetch failure."""
    mock_fetch.return_value = (False, 0)
    result = download_fsrs_subcontracts()
    assert result["status"] == "MANUAL"
    assert result["rows"] == 0
