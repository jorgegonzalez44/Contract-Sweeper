"""Tests for scripts/auto_download.py — pure helper functions."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.auto_download import (
    _build_fpds_query,
    _build_usaspending_payload,
    _file_exists_with_data,
    _parse_fpds_entry,
    RETRY_BACKOFF,
    USASPENDING_MIN_YEAR,
)


# ---------------------------------------------------------------------------
# _build_fpds_query
# ---------------------------------------------------------------------------

class TestBuildFpdsQuery:
    def _entry(self, filter_type="direct", year_start=2020, year_end=2023) -> dict:
        return {"filter_type": filter_type, "year_start": year_start, "year_end": year_end,
                "filters": {}}

    def test_direct_includes_pop_state_filter(self):
        result = _build_fpds_query(self._entry(filter_type="direct"))
        assert "PRINCIPAL_PLACE_OF_PERFORMANCE_STATE_CODE" in result
        assert '"PR"' in result

    def test_vendor_includes_vendor_state_filter(self):
        result = _build_fpds_query(self._entry(filter_type="vendor"))
        assert "VENDOR_ADDRESS_STATE_CODE" in result
        assert '"PR"' in result

    def test_date_range_uses_fiscal_year_boundaries(self):
        result = _build_fpds_query(self._entry(year_start=2020, year_end=2023))
        # FY start = prior year Oct 1
        assert "2019/10/01" in result
        assert "2023/09/30" in result

    def test_returns_string(self):
        assert isinstance(_build_fpds_query(self._entry()), str)


# ---------------------------------------------------------------------------
# _build_usaspending_payload
# ---------------------------------------------------------------------------

class TestBuildUsaspendingPayload:
    def _entry(self, filter_type="direct", year_start=2018, year_end=2023) -> dict:
        return {
            "filter_type": filter_type,
            "year_start": year_start,
            "year_end": year_end,
            "filters": {},
        }

    def test_returns_tuple_of_payload_and_effective_start(self):
        payload, start = _build_usaspending_payload(self._entry())
        assert isinstance(payload, dict)
        assert isinstance(start, int)

    def test_effective_start_clamped_to_min_year(self):
        _, start = _build_usaspending_payload(self._entry(year_start=2000))
        assert start == USASPENDING_MIN_YEAR

    def test_effective_start_not_clamped_when_above_min(self):
        _, start = _build_usaspending_payload(self._entry(year_start=2018))
        assert start == 2018

    def test_payload_has_filters_and_fields(self):
        payload, _ = _build_usaspending_payload(self._entry())
        assert "filters" in payload
        assert "fields" in payload

    def test_direct_filter_includes_pop_state(self):
        payload, _ = _build_usaspending_payload(self._entry(filter_type="direct"))
        filters = payload["filters"]
        assert "place_of_performance_locations" in filters
        assert filters["place_of_performance_locations"][0]["state"] == "PR"

    def test_vendor_filter_includes_recipient_locations(self):
        payload, _ = _build_usaspending_payload(self._entry(filter_type="vendor"))
        assert "recipient_locations" in payload["filters"]

    def test_dod_filter_includes_dod_agency(self):
        entry = self._entry(filter_type="dod")
        entry["filters"] = {"Keywords": ["Puerto Rico"]}
        payload, _ = _build_usaspending_payload(entry)
        agencies = payload["filters"].get("agencies", [])
        agency_names = [a["name"] for a in agencies]
        assert any("Defense" in n for n in agency_names)

    def test_time_period_uses_fy_boundaries(self):
        payload, _ = _build_usaspending_payload(self._entry(year_start=2018, year_end=2022))
        tp = payload["filters"]["time_period"][0]
        assert tp["start_date"].endswith("-10-01")
        assert tp["end_date"].endswith("-09-30")


# ---------------------------------------------------------------------------
# _parse_fpds_entry
# ---------------------------------------------------------------------------

class TestParseFpdsEntry:
    def _elem(self, tag: str, text: str, attribs: dict | None = None):
        from lxml import etree
        el = etree.Element(tag)
        if text:
            el.text = text
        if attribs:
            for k, v in attribs.items():
                el.set(k, v)
        return el

    def _entry_element(self, fields: dict):
        """Build a minimal FPDS Atom entry element."""
        from lxml import etree
        entry = etree.Element("entry")
        for tag, text in fields.items():
            child = etree.SubElement(entry, tag)
            child.text = text
        return entry

    def test_extracts_text_fields(self):
        entry = self._entry_element({
            "vendorName": "Acme Corp PR",
            "obligatedAmount": "500000",
            "signedDate": "2022-01-15",
        })
        result = _parse_fpds_entry(entry)
        assert result["vendorName"] == "Acme Corp PR"
        assert result["obligatedAmount"] == "500000"

    def test_skips_atom_boilerplate_keys(self):
        entry = self._entry_element({
            "title": "should be removed",
            "vendorName": "Corp",
            "id": "should be removed",
        })
        result = _parse_fpds_entry(entry)
        assert "title" not in result
        assert "id" not in result
        assert "vendorName" in result

    def test_returns_dict(self):
        entry = self._entry_element({"vendorName": "Corp A"})
        assert isinstance(_parse_fpds_entry(entry), dict)

    def test_empty_element_returns_empty_dict(self):
        from lxml import etree
        entry = etree.Element("entry")
        result = _parse_fpds_entry(entry)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# _file_exists_with_data
# ---------------------------------------------------------------------------

class TestFileExistsWithData:
    def test_missing_file_returns_zero(self, tmp_path):
        assert _file_exists_with_data(tmp_path / "nonexistent.csv") == 0

    def test_file_with_rows_returns_positive(self, tmp_path):
        import pandas as pd
        p = tmp_path / "data.csv"
        pd.DataFrame({"a": [1, 2, 3]}).to_csv(p, index=False)
        assert _file_exists_with_data(p) > 0

    def test_file_with_only_header_returns_zero(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("col_a,col_b\n")
        assert _file_exists_with_data(p) == 0


# ---------------------------------------------------------------------------
# RETRY_BACKOFF constant
# ---------------------------------------------------------------------------

class TestRetryBackoff:
    def test_backoff_is_increasing(self):
        for i in range(len(RETRY_BACKOFF) - 1):
            assert RETRY_BACKOFF[i] <= RETRY_BACKOFF[i + 1]

    def test_backoff_values_positive(self):
        assert all(v > 0 for v in RETRY_BACKOFF)
