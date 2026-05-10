"""Tests for source registry audit and manifest tracking."""

from pathlib import Path
from tempfile import TemporaryDirectory

from contract_sweeper.governance.source_registry import SourceEntry, SourceRegistry


def test_source_registry_write_and_load():
    with TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        registry = SourceRegistry(root)
        entry = SourceEntry(
            source_id="pr_contracts_master",
            source_name="PR Contracts Master",
            source_family="tier0",
            status="PENDING",
            rows=0,
            sha256="",
            manifest_path="data/raw/pr_contracts_master/manifest.json",
        )
        registry.add_entry(entry)
        registry.write()

        loaded = SourceRegistry(root)
        loaded.load()

        assert "pr_contracts_master" in loaded.entries
        assert loaded.entries["pr_contracts_master"].status == "PENDING"
