"""Pipeline integration smoke tests (Task 95).

Verifies:
- All scripts in scripts/ are importable (no syntax errors)
- config.py constants are self-consistent
- validation_gates.run() completes without exception on empty inputs
- generate_report.run() completes without exception on empty inputs
"""
import importlib
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.getLogger("validation_gates").setLevel(logging.CRITICAL)
logging.getLogger("generate_report").setLevel(logging.CRITICAL)
logging.getLogger("download_research").setLevel(logging.CRITICAL)

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

# Scripts that require interactive runtime deps (pdfplumber, selenium, etc.)
# or that monkey-patch sys.argv in __main__ — skip import-only smoke check.
_IMPORT_SKIP = {
    # None currently; update if a script fails due to unavailable C extension
}


def _importable_scripts():
    return sorted(
        p.stem for p in SCRIPTS_DIR.glob("*.py") if p.stem not in _IMPORT_SKIP
    )


class TestAllScriptsImportable:
    @pytest.mark.parametrize("module_stem", _importable_scripts())
    def test_import(self, module_stem):
        spec = importlib.util.spec_from_file_location(
            module_stem, SCRIPTS_DIR / f"{module_stem}.py"
        )
        mod = importlib.util.module_from_spec(spec)
        # Load without executing __main__ block
        spec.loader.exec_module(mod)
        assert mod is not None


class TestConfigConstants:
    def test_project_root_is_absolute(self):
        from scripts.config import PROJECT_ROOT
        assert PROJECT_ROOT.is_absolute()

    def test_processed_dir_under_project_root(self):
        from scripts.config import PROJECT_ROOT, PROCESSED_DIR
        assert str(PROCESSED_DIR).startswith(str(PROJECT_ROOT))

    def test_staging_dir_under_project_root(self):
        from scripts.config import PROJECT_ROOT, STAGING_DIR
        assert str(STAGING_DIR).startswith(str(PROJECT_ROOT))


class TestValidationGatesSmoke:
    def test_run_with_empty_enrichment_dir(self, tmp_path):
        """validation_gates.run() should not raise when enrichment dir is empty."""
        from scripts.validation_gates import run
        enrichment_dir = tmp_path / "data" / "staging" / "processed" / "enrichment"
        enrichment_dir.mkdir(parents=True)
        # report_only=True so no writes attempted
        report = run(root=tmp_path, report_only=True)
        assert report is not None

    def test_run_returns_object_with_gates(self, tmp_path):
        """ValidationReport should have a gates attribute."""
        from scripts.validation_gates import run
        (tmp_path / "data" / "staging" / "processed" / "enrichment").mkdir(parents=True)
        report = run(root=tmp_path, report_only=True)
        assert hasattr(report, "gates")


class TestGenerateReportSmoke:
    def test_run_with_no_inputs(self, tmp_path):
        """generate_report.run() should not raise when all inputs are missing."""
        from scripts.generate_report import run
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        result = run(root=tmp_path)
        assert isinstance(result, dict)

    def test_run_writes_output_files(self, tmp_path):
        """generate_report.run() should write output files even with empty inputs."""
        from scripts.generate_report import run
        (tmp_path / "data" / "staging" / "processed").mkdir(parents=True)
        run(root=tmp_path)
        report_dir = tmp_path / "data" / "reports"
        # At least one output file created under data/
        outputs = list((tmp_path / "data").rglob("*.md")) + list(
            (tmp_path / "data").rglob("*.json")
        )
        assert len(outputs) >= 1
