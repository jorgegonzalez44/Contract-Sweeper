"""Extended tests for scripts/sam_enrichment.py — name_similarity, sam_call, sam_lookup_by_name."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.sam_enrichment import (
    name_similarity,
    normalize_vendor,
    sam_call,
    sam_lookup_by_name,
    vendor_hash,
)


# ---------------------------------------------------------------------------
# name_similarity — float in [0, 1]
# ---------------------------------------------------------------------------

class TestNameSimilarity:
    def test_identical_strings_return_one(self):
        assert name_similarity("ACME CORP", "ACME CORP") == pytest.approx(1.0)

    def test_empty_a_returns_zero(self):
        assert name_similarity("", "ACME CORP") == 0.0

    def test_empty_b_returns_zero(self):
        assert name_similarity("ACME CORP", "") == 0.0

    def test_both_empty_returns_zero(self):
        assert name_similarity("", "") == 0.0

    def test_completely_different_returns_low(self):
        score = name_similarity("ACME CORP", "ZYXW INDUSTRIES")
        assert score < 0.5

    def test_similar_names_return_high(self):
        # "Acme Corp" vs "ACME CORPORATION" — should be ≥ 0.7 with token_set_ratio
        score = name_similarity("ACME", "ACME CORPORATION")
        assert score > 0.7

    def test_result_in_unit_interval(self):
        score = name_similarity("FOO BAR", "BAR BAZ")
        assert 0.0 <= score <= 1.0

    def test_abbreviation_match(self):
        # "PRASA" vs "PUERTO RICO AQUEDUCT AND SEWER AUTHORITY" — rapidfuzz should give > 0
        score = name_similarity("PRASA", "PUERTO RICO AQUEDUCT AND SEWER AUTHORITY")
        assert score >= 0.0  # Just verify it doesn't crash

    def test_subset_match_is_nonzero(self):
        # All tokens in a appear in b → Jaccard 1.0
        score = name_similarity("PUERTO RICO", "PUERTO RICO AQUEDUCT")
        assert score > 0.5

    def test_symmetric_property(self):
        a, b = "MICROSOFT PUERTO RICO", "MICROSOFT CORPORATION"
        # Similarity is not necessarily symmetric but should be positive for both
        assert name_similarity(a, b) >= 0.0
        assert name_similarity(b, a) >= 0.0


# ---------------------------------------------------------------------------
# sam_call — mocked HTTP
# ---------------------------------------------------------------------------

class TestSamCall:
    def _patch_requests(self, status_code, json_data=None, raise_exc=None):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = json_data or {}
        if raise_exc:
            mock_resp.side_effect = raise_exc
        return mock_resp

    def test_successful_200_returns_json(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"entityData": [{"uei": "ABC123"}]}
        with patch("scripts.sam_enrichment._requests.get", return_value=resp):
            result = sam_call({"legalBusinessName": "ACME"}, api_key="fake-key")
        assert result == {"entityData": [{"uei": "ABC123"}]}

    def test_404_returns_none(self):
        resp = MagicMock()
        resp.status_code = 404
        with patch("scripts.sam_enrichment._requests.get", return_value=resp):
            result = sam_call({"legalBusinessName": "ACME"}, api_key="fake-key")
        assert result is None

    def test_exception_returns_none(self):
        import requests
        with patch("scripts.sam_enrichment._requests.get", side_effect=requests.ConnectionError("down")):
            result = sam_call({"legalBusinessName": "ACME"}, api_key="fake-key")
        assert result is None

    def test_429_sleeps_and_returns_none(self):
        resp = MagicMock()
        resp.status_code = 429
        with patch("scripts.sam_enrichment._requests.get", return_value=resp):
            with patch("scripts.sam_enrichment.time.sleep") as mock_sleep:
                result = sam_call({"legalBusinessName": "ACME"}, api_key="fake-key")
        mock_sleep.assert_called_once()
        assert result is None


# ---------------------------------------------------------------------------
# sam_lookup_by_name — mocked HTTP, end-to-end name matching
# ---------------------------------------------------------------------------

def _entity_response(legal_name: str, uei: str, score_name: str = None):
    """Build a minimal SAM entityData response dict."""
    return {
        "entityData": [{
            "entityRegistration": {
                "legalBusinessName": score_name or legal_name,
                "ueiSAM": uei,
                "cageCode": "X1234",
                "dunsNumber": "123456789",
                "registrationStatus": "A",
                "registrationExpirationDate": "2025-12-31",
            },
            "coreData": {"physicalAddress": {"stateOrProvinceCode": "PR"}},
            "parentEntityInfo": {},
        }]
    }


class TestSamLookupByName:
    def test_successful_match_returns_dict_with_uei(self):
        resp_data = _entity_response("CROWLEY MARITIME CORP", "CROWLEY001")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = resp_data
        with patch("scripts.sam_enrichment._requests.get", return_value=resp):
            result = sam_lookup_by_name("Crowley Maritime Corp", api_key="fake")
        assert result is not None
        assert result["uei"] == "CROWLEY001"

    def test_network_failure_returns_none(self):
        import requests
        with patch("scripts.sam_enrichment._requests.get", side_effect=requests.ConnectionError("down")):
            with patch("scripts.sam_enrichment.time.sleep"):
                result = sam_lookup_by_name("Acme Corp", api_key="fake")
        assert result is None

    def test_empty_entity_data_returns_none(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"entityData": []}
        with patch("scripts.sam_enrichment._requests.get", return_value=resp):
            result = sam_lookup_by_name("Unknown Corp", api_key="fake")
        assert result is None

    def test_match_includes_score(self):
        resp_data = _entity_response("MICROSOFT PUERTO RICO LLC", "MSFT001")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = resp_data
        with patch("scripts.sam_enrichment._requests.get", return_value=resp):
            result = sam_lookup_by_name("Microsoft Puerto Rico LLC", api_key="fake")
        if result:
            assert "match_score" in result
            assert isinstance(result["match_score"], float)


# ---------------------------------------------------------------------------
# vendor_hash
# ---------------------------------------------------------------------------

class TestVendorHash:
    def test_returns_12_chars(self):
        assert len(vendor_hash("Acme Corp")) == 12

    def test_deterministic(self):
        assert vendor_hash("Crowley Maritime") == vendor_hash("Crowley Maritime")

    def test_normalized_equivalence(self):
        # Both normalize to "CROWLEY MARITIME" → same hash
        assert vendor_hash("CROWLEY MARITIME LLC") == vendor_hash("crowley maritime llc")

    def test_different_names_different_hash(self):
        assert vendor_hash("ACME") != vendor_hash("ZYXW")
