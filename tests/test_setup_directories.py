"""Tests for scripts/setup_directories.py — directory creation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scripts.config as config
import scripts.setup_directories as setup_mod
from scripts.setup_directories import main as setup_dirs


def _patch_all_dirs(monkeypatch, root):
    """Monkeypatch ALL_DIRS in both config and setup_directories modules."""
    patched = [
        root / "data",
        root / "data" / "staging",
        root / "data" / "staging" / "expansion",
        root / "data" / "staging" / "processed",
        root / "data" / "raw",
        root / "data" / "logs",
    ]
    monkeypatch.setattr(config, "ALL_DIRS", patched)
    monkeypatch.setattr(setup_mod, "ALL_DIRS", patched)


class TestSetupDirectories:
    def test_creates_all_dirs(self, tmp_path, monkeypatch):
        _patch_all_dirs(monkeypatch, tmp_path)
        setup_dirs(tmp_path)
        expected = [
            tmp_path / "data" / "staging" / "expansion",
            tmp_path / "data" / "staging" / "processed",
            tmp_path / "data" / "raw",
            tmp_path / "data" / "logs",
        ]
        for d in expected:
            assert d.is_dir(), f"Missing directory: {d}"

    def test_creates_gitkeep_files(self, tmp_path, monkeypatch):
        _patch_all_dirs(monkeypatch, tmp_path)
        setup_dirs(tmp_path)
        gitkeep_dirs = [
            tmp_path / "data" / "staging" / "expansion",
            tmp_path / "data" / "staging" / "processed",
            tmp_path / "data" / "raw",
            tmp_path / "data" / "logs",
        ]
        for d in gitkeep_dirs:
            assert (d / ".gitkeep").exists(), f"Missing .gitkeep in {d}"

    def test_idempotent(self, tmp_path, monkeypatch):
        """Running setup twice should not raise or break anything."""
        _patch_all_dirs(monkeypatch, tmp_path)
        setup_dirs(tmp_path)
        setup_dirs(tmp_path)
        assert (tmp_path / "data" / "staging" / "expansion").is_dir()
