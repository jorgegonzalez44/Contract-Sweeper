"""Tests for scripts/download_msrb_trades.py."""
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.getLogger("download_msrb_trades").setLevel(logging.CRITICAL)

from scripts.download_msrb_trades import OUTPUT_COLUMNS, _normalize_trade, run


class TestNormalizeTrade:
    def _record(self, **kwargs):
        base = {"cusip": "PRW12345", "tradeDate": "2022-01-15", "parTraded": "1000000", "price": "100.5", "tradeType": "C"}
        base.update(kwargs)
        return base

    def test_par_traded_numeric(self):
        out = _normalize_trade(self._record(parTraded="$2,500,000"))
        assert out["par_traded"] == pytest.approx(2500000.0)

    def test_customer_trade_type(self):
        out = _normalize_trade(self._record(tradeType="C"))
        assert out["market_side"] == "customer"

    def test_interdealer_trade_type(self):
        out = _normalize_trade(self._record(tradeType="D"))
        assert out["market_side"] == "interdealer"

    def test_missing_fields_default_empty(self):
        out = _normalize_trade({})
        assert out["cusip"] == ""
        assert out["par_traded"] == 0.0

    def test_price_numeric(self):
        out = _normalize_trade(self._record(price="98.5"))
        assert out["price"] == pytest.approx(98.5)


class TestOutputColumns:
    def test_has_cusip(self):
        assert "cusip" in OUTPUT_COLUMNS

    def test_has_par_traded(self):
        assert "par_traded" in OUTPUT_COLUMNS


class TestRunCaching:
    def test_existing_output_returns_cached(self, tmp_path):
        proc = tmp_path / "data" / "staging" / "processed"
        proc.mkdir(parents=True)
        out = proc / "pr_msrb_trades.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path, force=False)
        assert result.get("status") == "CACHED"

    def test_result_has_required_keys(self, tmp_path):
        proc = tmp_path / "data" / "staging" / "processed"
        proc.mkdir(parents=True)
        out = proc / "pr_msrb_trades.csv"
        out.write_text("col\nrow\n")
        result = run(root=tmp_path, force=False)
        assert "rows" in result
        assert "status" in result
