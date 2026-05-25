"""Tests for scripts/generate_source_coverage_actuals.py."""

import json
import logging
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.getLogger("generate_source_coverage_actuals").setLevel(logging.CRITICAL)

from scripts.generate_source_coverage_actuals import (
    _count_csv_rows,
    _load_registry,
    compute_actuals,
    run,
)

# ---------------------------------------------------------------------------
# _count_csv_rows
# ---------------------------------------------------------------------------

class TestCountCsvRows:
    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text("")
        assert _count_csv_rows(p) == 0

    def test_header_only(self, tmp_path):
        p = tmp_path / "header.csv"
        p.write_text("col_a,col_b\n")
        assert _count_csv_rows(p) == 0

    def test_two_data_rows(self, tmp_path):
        p = tmp_path / "data.csv"
        p.write_text("col_a,col_b\nval1,val2\nval3,val4\n")
        assert _count_csv_rows(p) == 2

    def test_missing_file_returns_zero(self, tmp_path):
        p = tmp_path / "nonexistent.csv"
        assert _count_csv_rows(p) == 0


# ---------------------------------------------------------------------------
# _load_registry
# ---------------------------------------------------------------------------

class TestLoadRegistry:
    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        p = tmp_path / "missing.yaml"
        result = _load_registry(p)
        assert result == {}

    def test_parses_valid_yaml(self, tmp_path):
        p = tmp_path / "registry.yaml"
        p.write_text("sources:\n  contracts:\n    master: pr_contracts.csv\n")
        result = _load_registry(p)
        assert "sources" in result
        assert result["sources"]["contracts"]["master"] == "pr_contracts.csv"


# ---------------------------------------------------------------------------
# compute_actuals
# ---------------------------------------------------------------------------

class TestComputeActuals:
    def _registry(self):
        return {
            "sources": {
                "contracts": {
                    "label": "FPDS Contracts",
                    "master": "pr_contracts_master.csv",
                    "coverage_target": 0.95,
                },
                "grants": {
                    "label": "USASpending Grants",
                    "master": "pr_grants_master.csv",
                    "coverage_target": 0.90,
                },
            }
        }

    def test_missing_files_give_zero_coverage(self, tmp_path):
        (tmp_path / "processed").mkdir(parents=True)
        result = compute_actuals(tmp_path / "processed", self._registry())
        assert result["contracts"]["coverage_rate"] == 0.0
        assert result["contracts"]["file_present"] is False

    def test_present_file_gives_full_coverage(self, tmp_path):
        processed = tmp_path / "processed"
        processed.mkdir(parents=True)
        f = processed / "pr_contracts_master.csv"
        f.write_text("col_a,col_b\nrow1a,row1b\n")
        result = compute_actuals(processed, self._registry())
        assert result["contracts"]["coverage_rate"] == 1.0
        assert result["contracts"]["file_present"] is True
        assert result["contracts"]["row_count"] == 1

    def test_meets_target_false_when_file_missing(self, tmp_path):
        (tmp_path / "processed").mkdir(parents=True)
        result = compute_actuals(tmp_path / "processed", self._registry())
        assert result["contracts"]["meets_target"] is False

    def test_empty_registry_returns_empty(self, tmp_path):
        (tmp_path / "processed").mkdir(parents=True)
        result = compute_actuals(tmp_path / "processed", {})
        assert result == {}

    def test_all_sources_present_in_output(self, tmp_path):
        (tmp_path / "processed").mkdir(parents=True)
        result = compute_actuals(tmp_path / "processed", self._registry())
        assert set(result.keys()) == {"contracts", "grants"}


# ---------------------------------------------------------------------------
# run() integration
# ---------------------------------------------------------------------------

class TestRun:
    def _make_registry(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        (data_dir / "manifests").mkdir()
        (data_dir / "staging" / "processed").mkdir(parents=True)
        registry = {
            "sources": {
                "contracts": {
                    "label": "FPDS Contracts",
                    "master": "pr_contracts_master.csv",
                    "coverage_target": 0.95,
                },
            }
        }
        reg_path = data_dir / "source_registry.yaml"
        reg_path.write_text(yaml.dump(registry))
        return tmp_path

    def test_writes_json_output(self, tmp_path):
        root = self._make_registry(tmp_path)
        result = run(root=root)
        assert result["status"] == "OK"
        out = root / "data" / "manifests" / "source_coverage_actuals.json"
        assert out.exists()

    def test_output_structure(self, tmp_path):
        root = self._make_registry(tmp_path)
        run(root=root)
        out = root / "data" / "manifests" / "source_coverage_actuals.json"
        data = json.loads(out.read_text())
        assert "generated_at" in data
        assert "sources" in data
        assert "contracts" in data["sources"]

    def test_caching_skips_when_exists(self, tmp_path):
        root = self._make_registry(tmp_path)
        out = root / "data" / "manifests" / "source_coverage_actuals.json"
        # Pre-populate with sentinel data
        out.write_text(json.dumps({"sources": {"sentinel": {}}}))
        result = run(root=root, force=False)
        assert result["status"] == "CACHED"
        # File unchanged
        data = json.loads(out.read_text())
        assert "sentinel" in data["sources"]

    def test_force_overwrites(self, tmp_path):
        root = self._make_registry(tmp_path)
        out = root / "data" / "manifests" / "source_coverage_actuals.json"
        out.write_text(json.dumps({"sources": {"sentinel": {}}}))
        run(root=root, force=True)
        data = json.loads(out.read_text())
        assert "sentinel" not in data["sources"]

    def test_missing_registry_writes_empty_sources(self, tmp_path):
        (tmp_path / "data" / "manifests").mkdir(parents=True)
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        # No source_registry.yaml
        result = run(root=tmp_path)
        assert result["status"] == "OK"
        out = tmp_path / "data" / "manifests" / "source_coverage_actuals.json"
        data = json.loads(out.read_text())
        assert data["sources"] == {}

    def test_creates_manifests_dir_if_missing(self, tmp_path):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "staging" / "processed").mkdir(parents=True)
        # manifests dir does NOT exist
        result = run(root=tmp_path)
        assert result["status"] in ("OK", "CACHED")
        assert (tmp_path / "data" / "manifests").exists()
