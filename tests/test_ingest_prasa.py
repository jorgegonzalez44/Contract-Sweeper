"""
Tests for scripts/ingest_prasa.py

Covers:
- PRASA_COLUMNS schema
- COL_MAP completeness (Spanish + English variants)
- _normalize_name helper
- _map_col helper
- _parse_df with realistic fixture DataFrames
- run(root=tmp_path) integration: no-input → graceful empty output
- run(root=tmp_path) integration: CSV fixture → correct output
- Output columns and deduplication
"""

import logging
import pandas as pd
import pytest
from pathlib import Path

from scripts.ingest_prasa import (
    PRASA_COLUMNS,
    COL_MAP,
    _normalize_name,
    _map_col,
    _parse_df,
    run,
    _run,
)


# ---------------------------------------------------------------------------
# Silence the logger during tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def silence_logger():
    logger = logging.getLogger("ingest_prasa")
    logger.setLevel(logging.CRITICAL)
    yield


# ---------------------------------------------------------------------------
# Schema / constant tests
# ---------------------------------------------------------------------------

def test_prasa_columns_has_required_fields():
    """All key PRASA output columns must be present."""
    required = [
        "contract_id", "vendor_name", "vendor_normalized",
        "contract_type", "contract_value",
        "award_date", "start_date", "end_date",
        "status", "description", "municipality", "source_file",
    ]
    for col in required:
        assert col in PRASA_COLUMNS, f"Missing column: {col}"


def test_prasa_columns_count():
    """PRASA_COLUMNS must have exactly 12 columns."""
    assert len(PRASA_COLUMNS) == 12


def test_col_map_vendor_has_spanish_variants():
    """COL_MAP vendor_name must include Spanish procurement terms."""
    vals = COL_MAP["vendor_name"]
    spanish_terms = {"Contratista", "Suplidor", "Proveedor"}
    found = spanish_terms & set(vals)
    assert found, f"No Spanish vendor terms found in {vals}"


def test_col_map_contract_value_has_monto():
    """COL_MAP contract_value must include 'Monto' (Spanish for amount)."""
    assert "Monto" in COL_MAP["contract_value"]


def test_col_map_contract_id_has_numero():
    """COL_MAP contract_id must include a Número variant."""
    vals = COL_MAP["contract_id"]
    assert any("mero" in v for v in vals), f"No Número variant in {vals}"


def test_col_map_status_has_estado():
    """COL_MAP status must include 'Estado'."""
    assert "Estado" in COL_MAP["status"]


def test_col_map_municipality_has_municipio():
    """COL_MAP municipality must include 'Municipio'."""
    assert "Municipio" in COL_MAP["municipality"]


# ---------------------------------------------------------------------------
# _normalize_name tests
# ---------------------------------------------------------------------------

def test_normalize_strips_llc():
    result = _normalize_name("Caribbean Builders LLC")
    assert "LLC" not in result
    assert "CARIBBEAN BUILDERS" in result


def test_normalize_strips_inc():
    result = _normalize_name("Cobra Acquisitions Inc")
    assert "INC" not in result
    assert "COBRA ACQUISITIONS" in result


def test_normalize_strips_corp():
    result = _normalize_name("MasTec Puerto Rico Corp")
    assert "CORP" not in result
    assert "MASTEC PUERTO RICO" in result


def test_normalize_strips_csp():
    result = _normalize_name("Constructora Moderna CSP")
    assert "CSP" not in result
    assert "CONSTRUCTORA MODERNA" in result


def test_normalize_uppercases_name():
    result = _normalize_name("fluor enterprises")
    assert result == result.upper()


def test_normalize_empty_string():
    assert _normalize_name("") == ""


def test_normalize_none():
    assert _normalize_name(None) == ""


def test_normalize_strips_punctuation():
    result = _normalize_name("A.C.E. Construction, LLC.")
    assert "." not in result
    assert "," not in result


# ---------------------------------------------------------------------------
# _map_col tests
# ---------------------------------------------------------------------------

def test_map_col_exact_match():
    cols = ["Vendor Name", "Amount", "Contract ID"]
    result = _map_col(cols, ["Vendor Name", "Contratista"])
    assert result == "Vendor Name"


def test_map_col_case_insensitive():
    cols = ["vendor name", "amount", "contract id"]
    result = _map_col(cols, ["Vendor Name"])
    assert result == "vendor name"


def test_map_col_returns_none_if_not_found():
    cols = ["Column A", "Column B"]
    result = _map_col(cols, ["Vendor Name", "Contratista"])
    assert result is None


def test_map_col_prefers_first_candidate():
    cols = ["Contratista", "Vendor Name"]
    # "Vendor Name" is first candidate → match it first
    result = _map_col(cols, ["Vendor Name", "Contratista"])
    assert result == "Vendor Name"


# ---------------------------------------------------------------------------
# _parse_df tests
# ---------------------------------------------------------------------------

def test_parse_df_spanish_columns():
    """_parse_df correctly maps Spanish column names."""
    df = pd.DataFrame({
        "Contratista": ["Cobra Acquisitions LLC", "Fluor Corp PR"],
        "Contrato": ["PRASA-001", "PRASA-002"],
        "Monto": ["5000000", "12000000"],
        "Estado": ["Completado", "Activo"],
        "Municipio": ["San Juan", "Ponce"],
    })
    logger = logging.getLogger("test_parse_df_spanish")
    result = _parse_df(df, "prasa_spanish.csv", logger)
    assert len(result) == 2
    assert "COBRA ACQUISITIONS" in result.iloc[0]["vendor_normalized"]
    assert result.iloc[0]["status"] == "Completado"
    assert result.iloc[0]["municipality"] == "San Juan"


def test_parse_df_english_columns():
    """_parse_df correctly maps English column names."""
    df = pd.DataFrame({
        "Vendor Name": ["AECOM Technical Services Inc"],
        "Contract Number": ["PRASA-ENG-001"],
        "Amount": ["7500000"],
        "Status": ["Active"],
        "Municipality": ["Bayamon"],
    })
    logger = logging.getLogger("test_parse_df_english")
    result = _parse_df(df, "prasa_eng.csv", logger)
    assert len(result) == 1
    assert "AECOM" in result.iloc[0]["vendor_normalized"]
    assert result.iloc[0]["contract_value"] == "7500000"
    assert result.iloc[0]["municipality"] == "Bayamon"


def test_parse_df_output_has_all_prasa_columns():
    """_parse_df output must always contain every column in PRASA_COLUMNS."""
    df = pd.DataFrame({
        "Vendor Name": ["Test Vendor"],
        "Amount": ["1000"],
    })
    logger = logging.getLogger("test_parse_df_cols")
    result = _parse_df(df, "test.csv", logger)
    for col in PRASA_COLUMNS:
        assert col in result.columns, f"Missing column in output: {col}"


def test_parse_df_filters_empty_vendor():
    """Rows with empty vendor_name should be excluded."""
    df = pd.DataFrame({
        "Vendor Name": ["Valid Corp", "", "   "],
        "Amount": ["1000", "2000", "3000"],
    })
    logger = logging.getLogger("test_parse_df_filter")
    result = _parse_df(df, "test.csv", logger)
    assert len(result) == 1
    assert result.iloc[0]["vendor_name"] == "Valid Corp"


def test_parse_df_source_file_set():
    """_parse_df must record the source_file name."""
    df = pd.DataFrame({
        "Vendor Name": ["Acme Corp"],
        "Amount": ["999"],
    })
    logger = logging.getLogger("test_parse_df_src")
    result = _parse_df(df, "my_source.csv", logger)
    assert result.iloc[0]["source_file"] == "my_source.csv"


def test_parse_df_empty_dataframe():
    """_parse_df on an empty DataFrame returns empty DataFrame with correct columns."""
    df = pd.DataFrame()
    logger = logging.getLogger("test_parse_df_empty")
    result = _parse_df(df, "empty.csv", logger)
    assert result.empty
    for col in PRASA_COLUMNS:
        assert col in result.columns


# ---------------------------------------------------------------------------
# run() integration tests
# ---------------------------------------------------------------------------

def test_run_no_input_returns_empty_output(tmp_path):
    """run() with no PRASA files returns rows=0 and writes an empty CSV."""
    result = run(root=tmp_path)
    assert result["rows"] == 0
    out_path = tmp_path / "data" / "staging" / "processed" / "pr_prasa_contracts.csv"
    assert out_path.exists()
    df = pd.read_csv(out_path, dtype=str)
    assert len(df) == 0


def test_run_no_input_output_has_correct_columns(tmp_path):
    """Empty output CSV must have exactly the PRASA_COLUMNS header."""
    run(root=tmp_path)
    out_path = tmp_path / "data" / "staging" / "processed" / "pr_prasa_contracts.csv"
    df = pd.read_csv(out_path, dtype=str)
    for col in PRASA_COLUMNS:
        assert col in df.columns, f"Column missing from empty output: {col}"


def test_run_no_input_errors_list(tmp_path):
    """run() with no data files must report an error."""
    result = run(root=tmp_path)
    assert len(result["errors"]) > 0


def test_run_with_csv_fixture(tmp_path):
    """run() with a CSV fixture produces non-empty output with correct columns."""
    # Set up the PRASA raw directory
    prasa_dir = tmp_path / "data" / "raw" / "PRASA"
    prasa_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "logs").mkdir(parents=True, exist_ok=True)

    fixture_data = pd.DataFrame({
        "Vendor Name": ["Cobra Acquisitions LLC", "AECOM Technical Services Inc", "Fluor Corp PR"],
        "Contract ID": ["PRASA-001", "PRASA-002", "PRASA-003"],
        "Amount": ["5000000", "7500000", "12000000"],
        "Status": ["Completed", "Active", "Active"],
        "Award Date": ["2018-01-15", "2019-03-20", "2020-06-01"],
        "Municipality": ["San Juan", "Ponce", "Mayaguez"],
    })
    fixture_data.to_csv(prasa_dir / "prasa_contracts.csv", index=False)

    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 3

    out_path = Path(result["path"])
    assert out_path.exists()
    df = pd.read_csv(out_path, dtype=str)
    assert len(df) == 3
    for col in PRASA_COLUMNS:
        assert col in df.columns, f"Column missing: {col}"


def test_run_with_csv_fixture_vendor_normalized(tmp_path):
    """run() correctly normalizes vendor names (strips suffix, uppercases)."""
    prasa_dir = tmp_path / "data" / "raw" / "PRASA"
    prasa_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "logs").mkdir(parents=True, exist_ok=True)

    fixture_data = pd.DataFrame({
        "Vendor Name": ["MasTec Puerto Rico LLC"],
        "Contract ID": ["PRASA-999"],
        "Amount": ["3000000"],
    })
    fixture_data.to_csv(prasa_dir / "prasa_mastec.csv", index=False)

    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 1

    df = pd.read_csv(Path(result["path"]), dtype=str)
    normalized = df.iloc[0]["vendor_normalized"]
    assert "LLC" not in normalized
    assert "MASTEC" in normalized


def test_run_deduplicates_on_vendor_and_contract_id(tmp_path):
    """Duplicate rows (same vendor_normalized + contract_id) are deduplicated."""
    prasa_dir = tmp_path / "data" / "raw" / "PRASA"
    prasa_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "logs").mkdir(parents=True, exist_ok=True)

    # Three rows: two identical, one unique
    fixture_data = pd.DataFrame({
        "Vendor Name": ["ABC Corp LLC", "ABC Corp LLC", "XYZ Inc"],
        "Contract ID": ["PRASA-DUP", "PRASA-DUP", "PRASA-UNIQUE"],
        "Amount": ["1000000", "1000000", "2000000"],
    })
    fixture_data.to_csv(prasa_dir / "prasa_dupes.csv", index=False)

    result = _run(root=tmp_path, force=True)
    # Duplicate row should be dropped → 2 unique records
    assert result["rows"] == 2


def test_run_skip_existing_output(tmp_path):
    """run() (non-forced) skips processing if output file already has data."""
    prasa_dir = tmp_path / "data" / "raw" / "PRASA"
    prasa_dir.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "logs").mkdir(parents=True, exist_ok=True)

    # Pre-populate the output file with 5 fake rows
    existing = pd.DataFrame({col: ["x"] * 5 for col in PRASA_COLUMNS})
    out_path = out_dir / "pr_prasa_contracts.csv"
    existing.to_csv(out_path, index=False)

    result = run(root=tmp_path)
    assert result["rows"] == 5  # returns cached count, not reprocessed


def test_run_returns_path_key(tmp_path):
    """run() result dict always contains a 'path' key pointing to the output CSV."""
    result = run(root=tmp_path)
    assert "path" in result
    assert result["path"].endswith("pr_prasa_contracts.csv")


def test_run_with_spanish_csv(tmp_path):
    """run() handles CSV with Spanish column headers correctly."""
    prasa_dir = tmp_path / "data" / "raw" / "PRASA"
    prasa_dir.mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "logs").mkdir(parents=True, exist_ok=True)

    fixture_data = pd.DataFrame({
        "Contratista": ["Empresa Constructora SE", "Grupo Fortaleza LLC"],
        "Número de Contrato": ["PRASA-ES-001", "PRASA-ES-002"],
        "Monto": ["8000000", "4500000"],
        "Estado": ["Activo", "Completado"],
        "Municipio": ["Caguas", "Humacao"],
    })
    fixture_data.to_csv(prasa_dir / "prasa_spanish.csv", index=False)

    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 2

    df = pd.read_csv(Path(result["path"]), dtype=str)
    assert df.iloc[0]["municipality"] == "Caguas"
    assert "EMPRESA CONSTRUCTORA" in df.iloc[0]["vendor_normalized"]
