"""
Tests for scripts/ingest_contralor.py

Covers:
- _normalize_name() — vendor/entity name normalization
- _map_col()        — column-name matching (exact and case-insensitive)
- _parse_df()       — column mapping and record filtering
- COL_MAP / CONTRALOR_COLUMNS schema integrity
- run() / _run()    — integration: no-input → empty output; CSV fixture → correct output
"""

import logging
import pandas as pd
import pytest
from pathlib import Path

from scripts.ingest_contralor import (
    CONTRALOR_COLUMNS,
    COL_MAP,
    _normalize_name,
    _map_col,
    _parse_df,
    run,
)

# We also import _run for force-mode tests
from scripts.ingest_contralor import _run

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _silent_logger():
    logger = logging.getLogger("test_contralor")
    logger.setLevel(logging.CRITICAL)
    return logger


def _contralor_dir(root):
    """Return (and create) the expected Contralor raw input folder."""
    folder = root / "data" / "raw" / "Oficina del Contralor"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _out_path(root):
    return root / "data" / "staging" / "processed" / "pr_contralor_audits.csv"


# ---------------------------------------------------------------------------
# 1. CONTRALOR_COLUMNS schema
# ---------------------------------------------------------------------------

def test_contralor_columns_contains_required_keys():
    required = [
        "entity_name", "entity_normalized", "audit_id",
        "audit_type", "audit_year", "audit_date",
        "finding_count", "finding_type", "contract_amount",
        "municipality", "recommendation", "status", "source_file",
    ]
    for col in required:
        assert col in CONTRALOR_COLUMNS, f"Missing column: {col}"


def test_contralor_columns_count():
    assert len(CONTRALOR_COLUMNS) >= 13


# ---------------------------------------------------------------------------
# 2. COL_MAP schema
# ---------------------------------------------------------------------------

def test_col_map_has_spanish_entity():
    assert any("Entidad" in v for v in COL_MAP["entity_name"])


def test_col_map_has_spanish_hallazgos():
    assert any("Hallazgos" in v for v in COL_MAP["finding_count"])


def test_col_map_has_spanish_status():
    assert any("Estado" in v or "Estatus" in v for v in COL_MAP["status"])


def test_col_map_has_english_report_number():
    assert any("Report Number" in v for v in COL_MAP["audit_id"])


def test_col_map_has_monto():
    assert any("Monto" in v for v in COL_MAP["contract_amount"])


# ---------------------------------------------------------------------------
# 3. _normalize_name()
# ---------------------------------------------------------------------------

def test_normalize_name_uppercases():
    result = _normalize_name("municipio de ponce")
    assert result == result.upper()


def test_normalize_name_strips_inc():
    result = _normalize_name("Caribbean Builders Inc")
    assert "INC" not in result.split()
    assert "CARIBBEAN" in result


def test_normalize_name_strips_llc():
    result = _normalize_name("Luma Energy LLC")
    assert "LLC" not in result.split()
    assert "LUMA" in result


def test_normalize_name_strips_corp():
    result = _normalize_name("AECOM Technical Services Corp")
    assert "CORP" not in result.split()
    assert "AECOM" in result


def test_normalize_name_removes_punctuation():
    result = _normalize_name("O'Brien & Associates, LLC")
    # punctuation replaced by spaces; LLC stripped
    assert "BRIEN" in result
    assert "LLC" not in result.split()


def test_normalize_name_empty_string():
    assert _normalize_name("") == ""


def test_normalize_name_none():
    assert _normalize_name(None) == ""


def test_normalize_name_nan():
    import numpy as np
    assert _normalize_name(float("nan")) == ""


def test_normalize_name_collapses_spaces():
    result = _normalize_name("  Municipio   de   Ponce  ")
    assert "  " not in result


def test_normalize_name_keeps_entity_name():
    result = _normalize_name("Departamento de Educación")
    assert "DEPARTAMENTO" in result


# ---------------------------------------------------------------------------
# 4. _map_col()
# ---------------------------------------------------------------------------

def test_map_col_exact_match():
    cols = ["Entidad", "Número de Informe", "Estado"]
    assert _map_col(cols, ["Entidad", "Entity"]) == "Entidad"


def test_map_col_case_insensitive():
    cols = ["entidad", "numero de informe"]
    result = _map_col(cols, ["Entidad"])
    assert result == "entidad"


def test_map_col_returns_none_when_missing():
    cols = ["ColumnA", "ColumnB"]
    assert _map_col(cols, ["Entidad", "Entity", "Nombre"]) is None


def test_map_col_first_candidate_wins():
    cols = ["Entity", "Nombre", "Entidad"]
    result = _map_col(cols, ["Nombre", "Entidad"])
    assert result == "Nombre"


# ---------------------------------------------------------------------------
# 5. _parse_df() — column mapping & record filtering
# ---------------------------------------------------------------------------

def test_parse_df_spanish_columns_produces_records():
    df = pd.DataFrame({
        "Entidad": ["Municipio de Ponce", "Departamento de Educación"],
        "Número de Informe": ["A-23-001", "A-23-002"],
        "Tipo de Informe": ["Operacional", "Fiscal"],
        "Hallazgos": ["3", "1"],
        "Estado": ["Abierto", "Cerrado"],
    })
    result = _parse_df(df, "contralor.csv", _silent_logger())
    assert len(result) == 2
    assert list(result.columns) == CONTRALOR_COLUMNS


def test_parse_df_normalizes_entity():
    df = pd.DataFrame({
        "Entidad": ["Municipio de Ponce Corp"],
        "Estado": ["Abierto"],
    })
    result = _parse_df(df, "test.csv", _silent_logger())
    assert "MUNICIPIO" in result.iloc[0]["entity_normalized"]
    assert "CORP" not in result.iloc[0]["entity_normalized"].split()


def test_parse_df_english_columns():
    df = pd.DataFrame({
        "Entity": ["PREPA", "PRASA"],
        "Report Number": ["RPT-001", "RPT-002"],
        "Report Type": ["Operational", "Financial"],
        "Findings": ["5", "2"],
        "Status": ["Open", "Closed"],
    })
    result = _parse_df(df, "english.csv", _silent_logger())
    assert len(result) == 2
    assert result.iloc[0]["entity_name"] == "PREPA"


def test_parse_df_source_file_column():
    df = pd.DataFrame({
        "Entidad": ["Municipio de Bayamón"],
        "Estado": ["Cerrado"],
    })
    result = _parse_df(df, "my_source.csv", _silent_logger())
    assert (result["source_file"] == "my_source.csv").all()


def test_parse_df_filters_empty_entity():
    df = pd.DataFrame({
        "Entidad": ["Valid Entity", "   ", ""],
        "Estado": ["Open", "Open", "Open"],
    })
    result = _parse_df(df, "test.csv", _silent_logger())
    assert len(result) == 1
    assert result.iloc[0]["entity_name"] == "Valid Entity"


def test_parse_df_empty_df_returns_empty():
    df = pd.DataFrame()
    result = _parse_df(df, "empty.csv", _silent_logger())
    assert result.empty
    assert list(result.columns) == CONTRALOR_COLUMNS


def test_parse_df_all_contralor_columns_present():
    df = pd.DataFrame({
        "Entidad": ["Test Entity"],
        "Número de Informe": ["X-001"],
    })
    result = _parse_df(df, "test.csv", _silent_logger())
    for col in CONTRALOR_COLUMNS:
        assert col in result.columns, f"Missing output column: {col}"


# ---------------------------------------------------------------------------
# 6. run() / _run() — integration tests
# ---------------------------------------------------------------------------

def test_run_no_input_folder_returns_zero(tmp_path):
    """No Contralor input folder → rows=0, errors populated."""
    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 0
    assert len(result["errors"]) > 0


def test_run_no_input_creates_empty_csv(tmp_path):
    """Even with no data, the output CSV is created with correct headers."""
    _run(root=tmp_path, force=True)
    out = _out_path(tmp_path)
    assert out.exists()
    df = pd.read_csv(out, dtype=str)
    assert list(df.columns) == CONTRALOR_COLUMNS


def test_run_with_csv_fixture_produces_output(tmp_path):
    """CSV in the Contralor folder → output CSV with correct columns and rows."""
    folder = _contralor_dir(tmp_path)
    fixture_df = pd.DataFrame({
        "Entidad": ["Municipio de San Juan", "PREPA"],
        "Número de Informe": ["A-24-001", "A-24-002"],
        "Tipo de Informe": ["Operacional", "Fiscal"],
        "Hallazgos": ["2", "4"],
        "Estado": ["Abierto", "Cerrado"],
        "Año": ["2024", "2024"],
    })
    fixture_df.to_csv(folder / "contralor_test.csv", index=False)

    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 2
    assert result["errors"] == []

    out = _out_path(tmp_path)
    assert out.exists()
    df_out = pd.read_csv(out, dtype=str)
    assert list(df_out.columns) == CONTRALOR_COLUMNS
    assert len(df_out) == 2


def test_run_with_csv_fixture_entity_names(tmp_path):
    """Entity names are preserved correctly in the output."""
    folder = _contralor_dir(tmp_path)
    pd.DataFrame({
        "Entidad": ["Departamento de Salud", "Autoridad de Carreteras"],
        "Estado": ["Abierto", "Cerrado"],
    }).to_csv(folder / "audit_data.csv", index=False)

    _run(root=tmp_path, force=True)
    df_out = pd.read_csv(_out_path(tmp_path), dtype=str)
    entities = df_out["entity_name"].tolist()
    assert "Departamento de Salud" in entities
    assert "Autoridad de Carreteras" in entities


def test_run_with_csv_fixture_normalization(tmp_path):
    """entity_normalized is uppercase with suffixes stripped."""
    folder = _contralor_dir(tmp_path)
    pd.DataFrame({
        "Entidad": ["Caribbean Consulting Corp"],
        "Estado": ["Abierto"],
    }).to_csv(folder / "audit.csv", index=False)

    _run(root=tmp_path, force=True)
    df_out = pd.read_csv(_out_path(tmp_path), dtype=str)
    norm = df_out.iloc[0]["entity_normalized"]
    assert "CARIBBEAN" in norm
    assert "CORP" not in norm.split()


def test_run_skips_when_output_exists(tmp_path):
    """run() (not _run) skips if output already has data."""
    out = _out_path(tmp_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Pre-populate output
    pd.DataFrame([{col: "x" for col in CONTRALOR_COLUMNS}]).to_csv(out, index=False)

    result = run(root=tmp_path)
    # Should return existing row count without re-processing
    assert result["rows"] >= 1


def test_run_force_overwrites_existing(tmp_path):
    """_run(force=True) re-processes even if output exists."""
    out = _out_path(tmp_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Pre-populate with stale data
    pd.DataFrame([{col: "stale" for col in CONTRALOR_COLUMNS}]).to_csv(out, index=False)

    # Now run with force — no input folder → 0 rows
    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 0
    df_out = pd.read_csv(out, dtype=str)
    assert len(df_out) == 0


def test_run_multiple_csv_files(tmp_path):
    """Multiple CSV files are concatenated."""
    folder = _contralor_dir(tmp_path)
    pd.DataFrame({
        "Entidad": ["PREPA", "PRASA"],
        "Estado": ["Abierto", "Abierto"],
    }).to_csv(folder / "file1.csv", index=False)
    pd.DataFrame({
        "Entidad": ["Municipio de Ponce"],
        "Estado": ["Cerrado"],
    }).to_csv(folder / "file2.csv", index=False)

    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 3


def test_run_returns_path_in_result(tmp_path):
    """Result dict includes 'path' key pointing to the output file."""
    result = _run(root=tmp_path, force=True)
    assert "path" in result
    assert result["path"].endswith("pr_contralor_audits.csv")


def test_run_english_columns_csv(tmp_path):
    """CSV with English column names is ingested correctly."""
    folder = _contralor_dir(tmp_path)
    pd.DataFrame({
        "Entity": ["FEMA Puerto Rico", "Army Corps of Engineers"],
        "Report Number": ["RPT-001", "RPT-002"],
        "Status": ["Open", "Closed"],
    }).to_csv(folder / "english_audit.csv", index=False)

    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 2
    df_out = pd.read_csv(_out_path(tmp_path), dtype=str)
    assert "FEMA" in df_out.iloc[0]["entity_name"]
