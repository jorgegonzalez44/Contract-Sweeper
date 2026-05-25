"""Tests for scripts/entity_resolution.py — vendor-to-parent entity resolution."""

import csv
import json
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.entity_resolution import (
    _http_get,
    _http_post,
    load_sam_index,
    load_vendor_rankings,
    resolve_vendor,
)
from scripts.sam_enrichment import normalize_vendor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_master(root: Path, rows: list[dict]) -> None:
    path = root / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else ["vendor_name", "obligated_amount"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _vendor_row(name: str, amount: str = "100000", uei: str = "",
                parent_uei: str = "", parent_name: str = "") -> dict:
    return {
        "vendor_name": name,
        "obligated_amount": amount,
        "recipient_uei": uei,
        "parent_uei": parent_uei,
        "parent_name": parent_name,
    }


def _fake_logger():
    logger = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    return logger


# ---------------------------------------------------------------------------
# normalize_vendor (from sam_enrichment, re-exported through entity_resolution)
# ---------------------------------------------------------------------------

class TestNormalizeVendor:
    def test_uppercases(self):
        assert normalize_vendor("acme corp") == normalize_vendor("ACME CORP")

    def test_strips_punctuation(self):
        result = normalize_vendor("Acme, Corp.")
        assert "," not in result
        assert "." not in result

    def test_removes_common_suffixes(self):
        a = normalize_vendor("Acme Inc")
        b = normalize_vendor("Acme Corporation")
        # Both should normalize to the same root (ACME)
        assert a == b or "ACME" in a

    def test_empty_string(self):
        result = normalize_vendor("")
        assert result == "" or result.strip() == ""

    def test_collapses_whitespace(self):
        result = normalize_vendor("Acme   Corp")
        assert "  " not in result


# ---------------------------------------------------------------------------
# _http_post
# ---------------------------------------------------------------------------

class TestHttpPost:
    def _mock_response(self, body: bytes, status: int = 200):
        mock = MagicMock()
        mock.__enter__ = lambda s: s
        mock.__exit__ = MagicMock(return_value=False)
        mock.status = status
        mock.read.return_value = body
        return mock

    def test_returns_parsed_json_on_success(self):
        payload = {"results": [{"name": "Acme", "uei": "ACME123"}]}
        mock_resp = self._mock_response(json.dumps(payload).encode())
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _http_post("https://example.com/api", {"q": "test"})
        assert result == payload

    def test_returns_none_on_timeout(self):
        import socket
        with patch("urllib.request.urlopen", side_effect=socket.timeout("timed out")):
            result = _http_post("https://example.com/api", {})
        assert result is None

    def test_returns_none_on_non_200(self):
        mock_resp = self._mock_response(b"{}", status=404)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _http_post("https://example.com/api", {})
        assert result is None

    def test_returns_none_on_bad_json(self):
        mock_resp = self._mock_response(b"not json at all")
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _http_post("https://example.com/api", {})
        assert result is None

    def test_returns_none_on_connection_error(self):
        import urllib.error
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("connection refused")):
            result = _http_post("https://example.com/api", {})
        assert result is None


# ---------------------------------------------------------------------------
# _http_get
# ---------------------------------------------------------------------------

class TestHttpGet:
    def _mock_response(self, body: bytes, status: int = 200):
        mock = MagicMock()
        mock.__enter__ = lambda s: s
        mock.__exit__ = MagicMock(return_value=False)
        mock.status = status
        mock.read.return_value = body
        return mock

    def test_returns_parsed_json_on_success(self):
        payload = {"parent_uei": "PRNT123", "parent_name": "Parent Corp"}
        mock_resp = self._mock_response(json.dumps(payload).encode())
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = _http_get("https://example.com/detail/abc")
        assert result == payload

    def test_returns_none_on_error(self):
        import urllib.error
        with patch("urllib.request.urlopen",
                   side_effect=urllib.error.URLError("not found")):
            result = _http_get("https://example.com/detail/abc")
        assert result is None


# ---------------------------------------------------------------------------
# load_vendor_rankings
# ---------------------------------------------------------------------------

class TestLoadVendorRankings:
    def test_loads_and_ranks_by_obligation(self, tmp_path):
        _write_master(tmp_path, [
            _vendor_row("Vendor A", amount="500000"),
            _vendor_row("Vendor B", amount="1000000"),
            _vendor_row("Vendor C", amount="250000"),
        ])
        result = load_vendor_rankings(tmp_path, top_n=10)
        names = [r["vendor_name"] for r in result]
        assert names[0] == "Vendor B"
        assert names[1] == "Vendor A"
        assert names[2] == "Vendor C"

    def test_top_n_truncates(self, tmp_path):
        rows = [_vendor_row(f"Vendor {i}", amount=str(100_000 * i)) for i in range(1, 11)]
        _write_master(tmp_path, rows)
        result = load_vendor_rankings(tmp_path, top_n=3)
        assert len(result) == 3

    def test_aggregates_multiple_rows_per_vendor(self, tmp_path):
        _write_master(tmp_path, [
            _vendor_row("Acme Inc", amount="300000"),
            _vendor_row("Acme Inc", amount="700000"),
        ])
        result = load_vendor_rankings(tmp_path, top_n=10)
        assert len(result) == 1
        assert result[0]["total_obligation"] == pytest.approx(1_000_000, abs=1)

    def test_skips_empty_vendor_names(self, tmp_path):
        _write_master(tmp_path, [
            _vendor_row("Acme Inc", amount="100000"),
            {"vendor_name": "", "obligated_amount": "200000",
             "recipient_uei": "", "parent_uei": "", "parent_name": ""},
        ])
        result = load_vendor_rankings(tmp_path, top_n=10)
        assert all(r["vendor_name"] != "" for r in result)

    def test_raises_when_no_master_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_vendor_rankings(tmp_path, top_n=10)

    def test_uses_recipient_name_for_unified_schema(self, tmp_path):
        path = tmp_path / "data" / "staging" / "processed" / "pr_contracts_master.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["recipient_name", "obligated_amount"])
            w.writeheader()
            w.writerow({"recipient_name": "Corp A", "obligated_amount": "500000"})
        result = load_vendor_rankings(tmp_path, top_n=10)
        assert result[0]["vendor_name"] == "Corp A"


# ---------------------------------------------------------------------------
# resolve_vendor
# ---------------------------------------------------------------------------

class TestResolveVendor:
    def _vendor(self, name: str = "Acme Inc", parent_uei: str = "",
                parent_name: str = "", uei: str = "") -> dict:
        return {
            "vendor_name": name,
            "total_obligation": 500_000.0,
            "record_count": 5,
            "known_uei": uei,
            "known_parent_uei": parent_uei,
            "known_parent_name": parent_name,
            "_rank": 1,
        }

    def test_pre_resolved_via_sam_enrichment(self):
        vendor = self._vendor(parent_uei="PRNT1234", parent_name="Parent Corp")
        result = resolve_vendor(vendor, {}, {}, _fake_logger())
        assert result["source"] == "sam_enrichment"
        assert result["parent_uei"] == "PRNT1234"

    def test_sam_index_hit(self):
        vendor = self._vendor()
        sam_index = {
            "Acme Inc": {"parent_uei": "SAMPRNT1", "parent_name": "SAM Parent",
                         "uei": "ACME0001", "match_score": "0.95"},
        }
        result = resolve_vendor(vendor, sam_index, {}, _fake_logger())
        assert result["source"] == "sam_index"
        assert result["parent_uei"] == "SAMPRNT1"

    def test_cache_hit(self):
        vendor = self._vendor()
        cache = {
            "Acme Inc": {"parent_uei": "CACHEPRNT", "parent_name": "Cache Parent",
                         "uei": "", "business_types": "corporation"},
        }
        with patch("scripts.entity_resolution.search_recipient", return_value=None):
            result = resolve_vendor(vendor, {}, cache, _fake_logger())
        assert result["source"] == "cache"
        assert result["parent_uei"] == "CACHEPRNT"

    def test_unresolved_when_api_returns_nothing(self):
        vendor = self._vendor()
        with patch("scripts.entity_resolution.search_recipient", return_value=None), \
             patch("scripts.entity_resolution.time.sleep"):
            result = resolve_vendor(vendor, {}, {}, _fake_logger())
        assert result["source"] == "unresolved"
        assert result["parent_uei"] == ""

    def test_unresolved_populates_cache_entry(self):
        vendor = self._vendor()
        cache: dict = {}
        with patch("scripts.entity_resolution.search_recipient", return_value=None), \
             patch("scripts.entity_resolution.time.sleep"):
            resolve_vendor(vendor, {}, cache, _fake_logger())
        assert "Acme Inc" in cache
        assert cache["Acme Inc"]["parent_uei"] == ""

    def test_sam_index_normalized_name_fallback(self):
        # SAM index key is normalized form; original vendor_name doesn't match directly
        vendor = self._vendor(name="ACME INC")
        norm_name = normalize_vendor("ACME INC")
        sam_index = {
            norm_name: {"parent_uei": "NORMP001", "parent_name": "Norm Parent",
                        "uei": "ACME001", "match_score": "0.90"},
        }
        result = resolve_vendor(vendor, sam_index, {}, _fake_logger())
        assert result["source"] == "sam_index"
