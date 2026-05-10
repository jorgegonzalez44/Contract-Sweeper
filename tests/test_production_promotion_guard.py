"""Tests for production promotion guard status generation."""

from pathlib import Path
from tempfile import TemporaryDirectory

from contract_sweeper.validation.production_promotion_guard import ProductionPromotionGuard


def test_production_promotion_guard_generates_expected_status():
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        guard = ProductionPromotionGuard(root)
        status = guard.run()

        assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
        assert status["downloads_executed"] is False
        assert status["rows_ingested"] == 0
        assert status["production_inputs_staged"] == 0
        assert status["r5_blocked"] is True

        loaded = guard.load()
        assert loaded == status
