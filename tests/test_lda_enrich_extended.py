"""Extended tests for scripts/lda_enrich.py — API query logic and result aggregation."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lda_enrich import (
    _flatten,
    _get,
    _normalize,
    _token_overlap,
    run,
)


# ---------------------------------------------------------------------------
# _get — HTTP helper with retry logic
# ---------------------------------------------------------------------------

def _make_logger():
    import logging
    logger = logging.getLogger("test_lda_enrich_extended")
    logger.setLevel(logging.CRITICAL)  # suppress output in tests
    return logger


def _mock_session(status_code=200, json_data=None, raise_exc=None):
    """Build a MagicMock session whose .get() returns a configured response."""
    session = MagicMock(spec=requests.Session)
    if raise_exc:
        session.get.side_effect = raise_exc
        return session
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = ""
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code}")
    else:
        resp.raise_for_status.return_value = None
    session.get.return_value = resp
    return session


class TestGet:
    def test_successful_response_returns_json(self):
        session = _mock_session(200, {"results": [], "next": None})
        with patch("scripts.lda_enrich.time.sleep"):
            result = _get(session, "http://example.com/", {}, _make_logger())
        assert result == {"results": [], "next": None}

    def test_404_returns_none(self):
        session = _mock_session(404)
        result = _get(session, "http://example.com/", {}, _make_logger())
        assert result is None

    def test_400_returns_none(self):
        session = _mock_session(400)
        result = _get(session, "http://example.com/", {}, _make_logger())
        assert result is None

    def test_network_error_returns_none_after_retries(self):
        session = _mock_session(raise_exc=requests.ConnectionError("refused"))
        with patch("scripts.lda_enrich.time.sleep"):
            result = _get(session, "http://example.com/", {}, _make_logger())
        assert result is None

    def test_timeout_returns_none_after_retries(self):
        session = _mock_session(raise_exc=requests.Timeout("timeout"))
        with patch("scripts.lda_enrich.time.sleep"):
            result = _get(session, "http://example.com/", {}, _make_logger())
        assert result is None

    def test_network_error_retries_max_retries_times(self):
        session = _mock_session(raise_exc=requests.ConnectionError("down"))
        with patch("scripts.lda_enrich.time.sleep") as mock_sleep:
            _get(session, "http://example.com/", {}, _make_logger())
        # Should have attempted MAX_RETRIES=3 times; sleep called between retries (2 sleeps)
        assert mock_sleep.call_count >= 2

    def test_429_does_not_raise_but_returns_none_after_retry(self):
        # 429 loops back and retries; after MAX_RETRIES attempts all return 429 → None
        resp = MagicMock()
        resp.status_code = 429
        resp.text = "rate limited"
        resp.raise_for_status.side_effect = requests.HTTPError("429")
        session = MagicMock(spec=requests.Session)
        session.get.return_value = resp
        with patch("scripts.lda_enrich.time.sleep"):
            result = _get(session, "http://example.com/", {}, _make_logger())
        assert result is None


# ---------------------------------------------------------------------------
# _flatten — pure filing record flattening
# ---------------------------------------------------------------------------

def _filing(filing_uuid="UUID-1", filing_year=2022, income="100000.00",
            registrant_name="Lobby Firm A", client_name="PRASA",
            issues=None, lobbyists=None):
    """Build a minimal LDA filing dict."""
    activities = []
    if issues:
        for code, desc in issues:
            act = {"general_issue_code_display": code, "description": desc, "lobbyists": []}
            if lobbyists:
                act["lobbyists"] = [{"lobbyist": {"name": n}} for n in lobbyists]
            activities.append(act)
    return {
        "filing_uuid": filing_uuid,
        "filing_year": filing_year,
        "filing_type": "Q2",
        "period_of_report": "2022-06-30",
        "income": income,
        "expenses": "0.00",
        "registrant": {"name": registrant_name, "state": "DC"},
        "client": {"name": client_name, "state": "PR"},
        "lobbying_activities": activities,
    }


class TestFlatten:
    def test_returns_dict(self):
        result = _flatten(_filing())
        assert isinstance(result, dict)

    def test_extracts_uuid_and_year(self):
        result = _flatten(_filing(filing_uuid="TEST-123", filing_year=2021))
        assert result["filing_uuid"] == "TEST-123"
        assert result["filing_year"] == 2021

    def test_extracts_registrant_and_client(self):
        result = _flatten(_filing(registrant_name="Firm A", client_name="Corp B"))
        assert result["registrant_name"] == "Firm A"
        assert result["client_name"] == "Corp B"

    def test_extracts_issue_codes(self):
        result = _flatten(_filing(issues=[("ENV", "Environmental policy"), ("TAX", "Tax reform")]))
        codes = result["general_issue_codes"].split("|")
        assert "ENV" in codes
        assert "TAX" in codes

    def test_extracts_lobbyist_names(self):
        result = _flatten(_filing(
            issues=[("ENV", "desc")],
            lobbyists=["Alice Smith", "Bob Jones"],
        ))
        names = result["lobbyist_names"].split("|")
        assert "Alice Smith" in names
        assert "Bob Jones" in names

    def test_empty_activities(self):
        result = _flatten(_filing(issues=None))
        assert result["general_issue_codes"] == ""
        assert result["lobbyist_names"] == ""

    def test_income_preserved(self):
        result = _flatten(_filing(income="250000.00"))
        assert result["income"] == "250000.00"

    def test_missing_registrant_key(self):
        rec = {"filing_uuid": "X", "filing_year": 2022, "lobbying_activities": []}
        result = _flatten(rec)
        assert result["registrant_name"] == ""
        assert result["client_name"] == ""


# ---------------------------------------------------------------------------
# run() — integration with tmp_path and mocked HTTP
# ---------------------------------------------------------------------------

def _write_entity_master(processed_dir: Path, rows: list[dict]) -> None:
    processed_dir.mkdir(parents=True, exist_ok=True)
    defaults = {
        "entity_key": "ENTITY001",
        "canonical_name": "Test Corp",
        "total_obligated": "500000",
        "award_count": "10",
    }
    df = pd.DataFrame([{**defaults, **r} for r in rows])
    df.to_csv(processed_dir / "entity_master.csv", index=False)


class TestRun:
    def test_no_entity_master_returns_no_input_status(self, tmp_path):
        result = run(root=tmp_path, api_key="fake", top_n=5)
        assert result["status"] == "NO_INPUT"
        assert result["entities_queried"] == 0

    def test_writes_enriched_and_crossref_csvs(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        _write_entity_master(processed, [{"entity_key": "ENT1", "canonical_name": "Acme PR", "total_obligated": "1000000"}])

        # Pre-populate empty cache so no HTTP calls are made
        cache_dir = tmp_path / "data" / "staging" / "raw" / "lda" / "entity_queries"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "ENT1.json").write_text("[]")

        result = run(root=tmp_path, api_key=None, top_n=5, force=False)
        assert result["status"] == "OK"
        assert (processed / "entity_lda_enriched.csv").exists()
        assert (processed / "pr_lda_entity_crossref.csv").exists()

    def test_entity_with_no_filings_has_lda_flag_zero(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        _write_entity_master(processed, [{"entity_key": "ENT2", "canonical_name": "Small Corp", "total_obligated": "100000"}])

        cache_dir = tmp_path / "data" / "staging" / "raw" / "lda" / "entity_queries"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "ENT2.json").write_text("[]")

        run(root=tmp_path, api_key=None, top_n=5, force=False)
        df = pd.read_csv(processed / "entity_lda_enriched.csv")
        assert df["lda_flag"].iloc[0] == 0

    def test_entity_with_filings_has_lda_flag_one(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        _write_entity_master(processed, [
            {"entity_key": "ENT3", "canonical_name": "PRASA", "total_obligated": "2000000"},
        ])

        cache_dir = tmp_path / "data" / "staging" / "raw" / "lda" / "entity_queries"
        cache_dir.mkdir(parents=True, exist_ok=True)
        filing = _filing(filing_uuid="F-001", income="50000.00", registrant_name="Firm X",
                         issues=[("ENV", "environment")])
        (cache_dir / "ENT3.json").write_text(json.dumps([filing]))

        run(root=tmp_path, api_key=None, top_n=5, force=False)
        df = pd.read_csv(processed / "entity_lda_enriched.csv")
        assert df["lda_flag"].iloc[0] == 1
        assert df["lda_total_spend"].iloc[0] == pytest.approx(50000.0)

    def test_crossref_has_correct_columns(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        _write_entity_master(processed, [
            {"entity_key": "ENT4", "canonical_name": "Corp D", "total_obligated": "100000"},
        ])

        cache_dir = tmp_path / "data" / "staging" / "raw" / "lda" / "entity_queries"
        cache_dir.mkdir(parents=True, exist_ok=True)
        filing = _filing(filing_uuid="F-002", income="25000.00")
        (cache_dir / "ENT4.json").write_text(json.dumps([filing]))

        run(root=tmp_path, api_key=None, top_n=5, force=False)
        df = pd.read_csv(processed / "pr_lda_entity_crossref.csv")
        assert "entity_key" in df.columns
        assert "canonical_name" in df.columns
        assert "filing_uuid" in df.columns

    def test_returns_dict_with_expected_keys(self, tmp_path):
        processed = tmp_path / "data" / "staging" / "processed"
        _write_entity_master(processed, [{"entity_key": "ENT5", "canonical_name": "Corp E", "total_obligated": "500"}])
        cache_dir = tmp_path / "data" / "staging" / "raw" / "lda" / "entity_queries"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "ENT5.json").write_text("[]")

        result = run(root=tmp_path, api_key=None, top_n=5, force=False)
        assert "entities_queried" in result
        assert "entities_matched" in result
        assert "total_spend" in result
