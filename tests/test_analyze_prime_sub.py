"""Tests for scripts/analyze_prime_sub.py — prime-to-subcontractor relationship analysis."""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_prime_sub import _yr_range, build_prime_sub


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_subawards(root: Path, rows: list[dict]) -> None:
    path = root / "data" / "staging" / "processed" / "pr_subawards_master.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "prime_recipient_name", "recipient_name", "obligated_amount",
        "award_id", "prime_award_id", "awarding_agency", "fiscal_year",
    ]
    pd.DataFrame([{k: r.get(k, "") for k in fields} for r in rows]).to_csv(path, index=False)


def _row(prime: str, sub: str, amount: str = "100000", fy: str = "2022",
         award_id: str = "AWD001", prime_award: str = "PAWD001",
         agency: str = "Agency X") -> dict:
    return {
        "prime_recipient_name": prime,
        "recipient_name": sub,
        "obligated_amount": amount,
        "award_id": award_id,
        "prime_award_id": prime_award,
        "awarding_agency": agency,
        "fiscal_year": fy,
    }


# ---------------------------------------------------------------------------
# _yr_range
# ---------------------------------------------------------------------------

class TestYrRange:
    def test_single_year(self):
        s = pd.Series(["2022", "2022", "2022"])
        assert _yr_range(s) == "2022"

    def test_multi_year_range(self):
        s = pd.Series(["2020", "2021", "2022"])
        assert _yr_range(s) == "2020-2022"

    def test_two_year_range(self):
        s = pd.Series(["2020", "2022"])
        assert _yr_range(s) == "2020-2022"

    def test_empty_series_returns_empty(self):
        assert _yr_range(pd.Series([], dtype=str)) == ""

    def test_all_nan_returns_empty(self):
        assert _yr_range(pd.Series([float("nan"), float("nan")])) == ""

    def test_non_numeric_ignored(self):
        s = pd.Series(["2020", "N/A", "2022"])
        assert _yr_range(s) == "2020-2022"

    def test_float_years_accepted(self):
        s = pd.Series(["2021.0", "2023.0"])
        assert _yr_range(s) == "2021-2023"


# ---------------------------------------------------------------------------
# build_prime_sub
# ---------------------------------------------------------------------------

class TestBuildPrimeSub:
    def test_missing_subawards_returns_status(self, tmp_path):
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        result = build_prime_sub(root=tmp_path)
        assert result["rows"] == 0
        assert result["status"] == "MISSING_SUBAWARDS"

    def test_basic_run_returns_ok(self, tmp_path):
        _write_subawards(tmp_path, [_row("Prime A", "Sub X")])
        result = build_prime_sub(root=tmp_path)
        assert result["status"] == "OK"
        assert result["rows"] == 1

    def test_relationships_csv_written(self, tmp_path):
        _write_subawards(tmp_path, [_row("Prime A", "Sub X")])
        build_prime_sub(root=tmp_path)
        out = tmp_path / "data" / "staging" / "processed" / "pr_prime_sub_relationships.csv"
        assert out.exists()

    def test_summary_json_written_with_top_primes(self, tmp_path):
        _write_subawards(tmp_path, [
            _row("Prime A", "Sub X", amount="200000"),
            _row("Prime A", "Sub Y", amount="100000"),
        ])
        build_prime_sub(root=tmp_path)
        summary_path = tmp_path / "data" / "staging" / "processed" / "pr_prime_sub_summary.json"
        assert summary_path.exists()
        data = json.loads(summary_path.read_text())
        assert "top_primes" in data
        assert len(data["top_primes"]) >= 1

    def test_aggregates_flow_per_pair(self, tmp_path):
        # Same (prime, sub) pair across two rows → flows should be summed
        _write_subawards(tmp_path, [
            _row("Prime A", "Sub X", amount="150000", award_id="AWD001"),
            _row("Prime A", "Sub X", amount="250000", award_id="AWD002"),
        ])
        result = build_prime_sub(root=tmp_path)
        assert result["rows"] == 1  # single unique pair
        assert result["total_flow"] == pytest.approx(400_000, abs=1)

    def test_multiple_pairs_count(self, tmp_path):
        _write_subawards(tmp_path, [
            _row("Prime A", "Sub X"),
            _row("Prime A", "Sub Y"),
            _row("Prime B", "Sub X"),
        ])
        result = build_prime_sub(root=tmp_path)
        assert result["rows"] == 3

    def test_prime_count_and_sub_count(self, tmp_path):
        _write_subawards(tmp_path, [
            _row("Prime A", "Sub X"),
            _row("Prime A", "Sub Y"),
            _row("Prime B", "Sub Z"),
        ])
        result = build_prime_sub(root=tmp_path)
        assert result["prime_count"] == 2
        assert result["sub_count"] == 3

    def test_sub_only_entities_identified(self, tmp_path):
        # Sub X is never a prime; Prime A is only a prime
        _write_subawards(tmp_path, [
            _row("Prime A", "Sub X"),
        ])
        result = build_prime_sub(root=tmp_path)
        assert result["sub_only"] >= 1

    def test_rows_with_empty_prime_name_excluded(self, tmp_path):
        _write_subawards(tmp_path, [
            _row("Prime A", "Sub X"),
            _row("", "Sub Y"),  # empty prime name — should be excluded
        ])
        result = build_prime_sub(root=tmp_path)
        assert result["rows"] == 1

    def test_rows_with_empty_sub_name_excluded(self, tmp_path):
        _write_subawards(tmp_path, [
            _row("Prime A", "Sub X"),
            _row("Prime B", ""),  # empty sub name — should be excluded
        ])
        result = build_prime_sub(root=tmp_path)
        assert result["rows"] == 1

    def test_fiscal_year_range_in_output(self, tmp_path):
        _write_subawards(tmp_path, [
            _row("Prime A", "Sub X", fy="2020", award_id="AWD001"),
            _row("Prime A", "Sub X", fy="2022", award_id="AWD002"),
        ])
        build_prime_sub(root=tmp_path)
        out = tmp_path / "data" / "staging" / "processed" / "pr_prime_sub_relationships.csv"
        df = pd.read_csv(out)
        assert "fiscal_year_range" in df.columns
        assert df.iloc[0]["fiscal_year_range"] == "2020-2022"

    def test_summary_total_flow_matches_return(self, tmp_path):
        _write_subawards(tmp_path, [
            _row("Prime A", "Sub X", amount="500000"),
            _row("Prime B", "Sub Y", amount="300000"),
        ])
        result = build_prime_sub(root=tmp_path)
        assert result["total_flow"] == pytest.approx(800_000, abs=1)
