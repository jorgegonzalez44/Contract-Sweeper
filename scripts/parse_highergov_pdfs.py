"""Extract tables from HigherGov PDFs into CSV for normalization.

Tries pdfplumber (preferred), then falls back to simple text parsing.
Writes CSVs to data/staging/expansion/ with names expected by normalization.
"""
from pathlib import Path
import re
import sys

try:
    import pdfplumber
except Exception:
    pdfplumber = None

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw" / "HigherGov"
OUT_DIR = PROJECT_ROOT / "data" / "staging" / "expansion"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Mapping from pdf basename patterns to desired CSV filenames
FILENAME_MAP = {
    "HigherGov PR Data (Municipal Awards)": "highergov_municipal_awards.csv",
    "HigherGov PR Data (IDV Awards)": "highergov_idv_awards.csv",
    "HigherGov PR Data (Prime Awards)": "highergov_prime_awards.csv",
    "HigherGov PR Data (Sub Awards)": "highergov_sub_awards.csv",
}


def parse_with_pdfplumber(path: Path) -> pd.DataFrame | None:
    if pdfplumber is None:
        return None
    rows = []
    columns = None
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                # Try extracting tables
                try:
                    tables = page.extract_tables()
                except Exception:
                    tables = None
                if tables:
                    for table in tables:
                        if not table:
                            continue
                        # treat first non-empty row as header if it has strings
                        header = None
                        if all(isinstance(c, str) for c in table[0] if c is not None):
                            header = [ (h or '').strip() for h in table[0] ]
                            data_rows = table[1:]
                        else:
                            data_rows = table
                        for r in data_rows:
                            rows.append([ (c or '').strip() for c in r ])
                        if header is not None and not columns:
                            columns = header
                else:
                    # fallback: extract text and try to parse lines
                    text = page.extract_text() or ""
                    for line in text.splitlines():
                        # heuristic: split on 2+ spaces
                        parts = re.split(r"\s{2,}", line.strip())
                        if len(parts) > 2:
                            if columns is None:
                                # create generic columns
                                columns = [f"col{i+1}" for i in range(len(parts))]
                            rows.append(parts)
        if rows:
            df = pd.DataFrame(rows)
            if columns and len(columns) == df.shape[1]:
                df.columns = columns
            return df
    except Exception as e:
        print(f"pdfplumber parsing failed for {path}: {e}")
        return None
    return None


def parse_text_fallback(path: Path) -> pd.DataFrame | None:
    # Use pdftotext via subprocess if available, else attempt very simple parse
    try:
        import subprocess
        res = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=True)
        text = res.stdout
    except Exception:
        try:
            # last resort: read as binary and use ascii fallback
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None
    rows = []
    columns = None
    for line in text.splitlines():
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) <= 1:
            continue
        if columns is None:
            columns = [f"col{i+1}" for i in range(len(parts))]
        rows.append(parts)
    if rows:
        df = pd.DataFrame(rows)
        if columns and len(columns) == df.shape[1]:
            df.columns = columns
        return df
    return None


def main():
    pdfs = sorted(RAW_DIR.glob("*.pdf"))
    if not pdfs:
        print("No HigherGov PDFs found in", RAW_DIR)
        return 1
    for p in pdfs:
        stem = p.stem
        out_name = FILENAME_MAP.get(stem, None)
        if out_name is None:
            # create a safe name
            out_name = re.sub(r"\W+", "_", stem).lower() + ".csv"
        out_path = OUT_DIR / out_name
        print(f"Processing {p.name} -> {out_name}")
        df = parse_with_pdfplumber(p)
        if df is None or df.empty:
            df = parse_text_fallback(p)
        if df is None or df.empty:
            print(f"  No table parsed for {p.name}; creating empty CSV with source_file column")
            import pandas as pd
            df = pd.DataFrame(columns=["source_file"])  # empty fallback
        # add provenance
        df["source_file"] = p.name
        try:
            df.to_csv(out_path, index=False, encoding="utf-8")
            print(f"  Wrote {out_path} ({len(df)} rows)")
        except Exception as e:
            print(f"  Failed to write {out_path}: {e}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
