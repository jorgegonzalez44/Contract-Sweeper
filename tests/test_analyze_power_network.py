"""Tests for scripts/analyze_power_network.py — composite influence score."""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_power_network import WEIGHTS, _minmax, _normalize, build_power_network


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_awards(root: Path, rows: list[dict]) -> None:
    path = root / "data" / "staging" / "processed" / "pr_all_awards_master.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["recipient_name", "obligated_amount", "award_id", "source_dataset", "fiscal_year"]
    pd.DataFrame([{k: r.get(k, "") for k in fields} for r in rows]).to_csv(path, index=False)


def _award(name: str, amount: str = "100000", award_id: str = "AWD001",
           dataset: str = "usaspending", fy: str = "2022") -> dict:
    return {"recipient_name": name, "obligated_amount": amount,
            "award_id": award_id, "source_dataset": dataset, "fiscal_year": fy}


# ---------------------------------------------------------------------------
# WEIGHTS
# ---------------------------------------------------------------------------

class TestWeights:
    def test_weights_sum_to_one(self):
        assert sum(WEIGHTS.values()) == pytest.approx(1.0, abs=1e-9)

    def test_expected_keys_present(self):
        expected = {"awards", "fec", "lobbying", "nonprofit", "medicare", "presence"}
        assert set(WEIGHTS.keys()) == expected

    def test_awards_has_highest_weight(self):
        assert WEIGHTS["awards"] == max(WEIGHTS.values())

    def test_all_weights_positive(self):
        assert all(w > 0 for w in WEIGHTS.values())


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_uppercases(self):
        assert _normalize("acme inc") == "ACME"

    def test_strips_inc(self):
        assert _normalize("Acme Inc") == "ACME"

    def test_strips_sa_srl(self):
        # SA and SRL are in the power-network suffix set (not in FEC set)
        assert _normalize("Empresa SA") == "EMPRESA"
        assert _normalize("Empresa SRL") == "EMPRESA"

    def test_empty_returns_empty(self):
        assert _normalize("") == ""

    def test_nan_returns_empty(self):
        assert _normalize(float("nan")) == ""


# ---------------------------------------------------------------------------
# _minmax
# ---------------------------------------------------------------------------

class TestMinmax:
    def test_all_zeros_returns_zeros(self):
        s = pd.Series([0.0, 0.0, 0.0])
        result = _minmax(s)
        assert all(result == 0.0)

    def test_uniform_positive_returns_50(self):
        # All values equal and positive → min-max is degenerate (hi==lo); should return 50
        s = pd.Series([5.0, 5.0, 5.0])
        result = _minmax(s)
        assert result.tolist() == pytest.approx([50.0, 50.0, 50.0], abs=0.1)

    def test_zero_to_100_range(self):
        s = pd.Series([0.0, 50.0, 100.0])
        result = _minmax(s)
        assert result.min() == pytest.approx(0.0, abs=0.1)
        assert result.max() == pytest.approx(100.0, abs=0.1)
        assert result.iloc[1] == pytest.approx(50.0, abs=0.1)

    def test_distinct_values_span_0_to_100(self):
        s = pd.Series([10.0, 20.0, 30.0, 40.0])
        result = _minmax(s)
        assert result.min() == pytest.approx(0.0, abs=0.1)
        assert result.max() == pytest.approx(100.0, abs=0.1)

    def test_output_length_matches_input(self):
        s = pd.Series([1.0, 5.0, 10.0, 50.0])
        assert len(_minmax(s)) == len(s)

    def test_output_values_in_0_100(self):
        s = pd.Series([0.0, 25.0, 75.0, 100.0, 1000.0])
        result = _minmax(s)
        assert result.min() >= 0.0
        assert result.max() <= 100.0


# ---------------------------------------------------------------------------
# build_power_network
# ---------------------------------------------------------------------------

class TestBuildPowerNetwork:
    def test_missing_awards_returns_status(self, tmp_path):
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        result = build_power_network(root=tmp_path)
        assert result["status"] == "MISSING_AWARDS"

    def test_basic_run_returns_ok(self, tmp_path):
        _write_awards(tmp_path, [_award("Corp A"), _award("Corp B", amount="200000")])
        result = build_power_network(root=tmp_path)
        assert result["status"] == "OK"

    def test_output_csv_written(self, tmp_path):
        _write_awards(tmp_path, [_award("Corp A")])
        build_power_network(root=tmp_path)
        assert (tmp_path / "data" / "staging" / "processed" / "pr_power_network.csv").exists()

    def test_summary_json_written(self, tmp_path):
        _write_awards(tmp_path, [_award("Corp A")])
        build_power_network(root=tmp_path)
        assert (tmp_path / "data" / "staging" / "processed" / "pr_power_network_summary.json").exists()

    def test_output_csv_has_rank_and_influence_score(self, tmp_path):
        _write_awards(tmp_path, [_award("Corp A"), _award("Corp B", amount="500000")])
        build_power_network(root=tmp_path)
        df = pd.read_csv(tmp_path / "data" / "staging" / "processed" / "pr_power_network.csv")
        assert "rank" in df.columns
        assert "influence_score" in df.columns

    def test_scores_in_0_100_range(self, tmp_path):
        _write_awards(tmp_path, [
            _award("Corp A", amount="100000"),
            _award("Corp B", amount="500000"),
            _award("Corp C", amount="1000000"),
        ])
        build_power_network(root=tmp_path)
        df = pd.read_csv(tmp_path / "data" / "staging" / "processed" / "pr_power_network.csv")
        assert df["influence_score"].min() >= 0.0
        assert df["influence_score"].max() <= 100.0

    def test_sorted_descending_by_influence_score(self, tmp_path):
        _write_awards(tmp_path, [
            _award("Corp A", amount="100000"),
            _award("Corp B", amount="1000000"),
        ])
        build_power_network(root=tmp_path)
        df = pd.read_csv(tmp_path / "data" / "staging" / "processed" / "pr_power_network.csv")
        scores = df["influence_score"].tolist()
        assert scores == sorted(scores, reverse=True)

    def test_higher_award_amount_yields_higher_score(self, tmp_path):
        _write_awards(tmp_path, [
            _award("Big Corp", amount="5000000", award_id="AWD001"),
            _award("Small Corp", amount="10000", award_id="AWD002"),
        ])
        build_power_network(root=tmp_path)
        df = pd.read_csv(tmp_path / "data" / "staging" / "processed" / "pr_power_network.csv")
        big_score  = df[df["canonical_name"] == "Big Corp"]["influence_score"].iloc[0]
        small_score = df[df["canonical_name"] == "Small Corp"]["influence_score"].iloc[0]
        assert big_score > small_score

    def test_summary_json_structure(self, tmp_path):
        _write_awards(tmp_path, [_award("Corp A")])
        build_power_network(root=tmp_path)
        data = json.loads(
            (tmp_path / "data" / "staging" / "processed" / "pr_power_network_summary.json").read_text()
        )
        assert "total_entities" in data
        assert "score_weights" in data
        assert "top_entities" in data
        assert "sources_included" in data

    def test_row_count_matches_unique_entities(self, tmp_path):
        _write_awards(tmp_path, [
            _award("Corp A", award_id="AWD001"),
            _award("Corp A", award_id="AWD002"),  # same entity, two awards
            _award("Corp B", award_id="AWD003"),
        ])
        result = build_power_network(root=tmp_path)
        assert result["rows"] == 2
