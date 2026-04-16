"""Tests for scripts/download_instructions.py — instruction generation."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import DOWNLOAD_MANIFEST
from scripts.download_instructions import generate_instructions


class TestGenerateInstructions:
    def test_creates_markdown_file(self, tmp_path):
        md_path = generate_instructions(tmp_path)
        assert md_path.exists()
        assert md_path.name == "DOWNLOAD_INSTRUCTIONS.md"

    def test_creates_manifest_json(self, tmp_path):
        md_path = generate_instructions(tmp_path)
        manifest_path = md_path.parent / "manifest.json"
        assert manifest_path.exists()

        data = json.loads(manifest_path.read_text())
        assert len(data) == 13

    def test_markdown_contains_all_filenames(self, tmp_path):
        md_path = generate_instructions(tmp_path)
        content = md_path.read_text()
        for entry in DOWNLOAD_MANIFEST:
            assert entry["filename"] in content, f"Missing: {entry['filename']}"

    def test_markdown_contains_checklist(self, tmp_path):
        md_path = generate_instructions(tmp_path)
        content = md_path.read_text()
        assert "Download Checklist" in content

    def test_manifest_json_entries_have_required_keys(self, tmp_path):
        md_path = generate_instructions(tmp_path)
        manifest_path = md_path.parent / "manifest.json"
        data = json.loads(manifest_path.read_text())
        for entry in data:
            assert "filename" in entry
            assert "source" in entry
            assert "filters" in entry
