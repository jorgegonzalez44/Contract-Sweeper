"""
Simple micro-benchmarks for normalize and dedup functions.
Generates synthetic CSVs/DataFrames and measures execution time.
Writes results to data/bench/benchmark_results.txt
"""
from pathlib import Path
import time
import random
import string
import pandas as pd
import numpy as np

from scripts.config import PROJECT_ROOT, PROCESSED_DIR, setup_logging, get_normalized_filename
from scripts.normalize_expansion_inputs import normalize_file, derive_fiscal_year
from scripts.deduplicate_master import deduplicate

logger = setup_logging("benchmark")

OUT_DIR = PROJECT_ROOT / "data" / "bench"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def random_vendor(n):
    choices = [
        "Acme Corp", "Bajos LLC", "Island Builders", "Construcciones PR", "Servicios Unidos",
        "Universal Contractors", "Marina Holdings", "Tech Solutions", "Global Supply"
    ]
    return np.random.choice(choices, size=n)

def random_dates_str(n):
    # generate dates over 10 years, mix formats
    base = pd.date_range("2010-01-01", periods=3650, freq="D")
    picks = np.random.choice(base, size=n)
    out = []
    for d in picks:
        fmt = random.choice(["%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y"]) 
        dt = pd.Timestamp(d)
        out.append(dt.strftime(fmt))
    return out

def random_amounts_str(n):
    vals = np.random.randint(100, 10_000_000, size=n)
    out = ["${:,}".format(v) for v in vals]
    return out


def bench_normalize(sizes=(1000, 10000, 50000)):
    results = []
    for n in sizes:
        logger.info(f"Benchmark normalize: {n} rows")
        df = pd.DataFrame({
            "contract_number": ["C-" + ''.join(random.choices(string.digits, k=6)) for _ in range(n)],
            "Date Signed": random_dates_str(n),
            "Vendor Name": random_vendor(n),
            "Award Amount": random_amounts_str(n),
        })
        input_path = OUT_DIR / f"bench_norm_{n}.csv"
        df.to_csv(input_path, index=False, encoding="utf-8")
        out_dir = OUT_DIR

        t0 = time.perf_counter()
        res = normalize_file(input_path, out_dir, logger)
        t1 = time.perf_counter()
        elapsed = t1 - t0
        results.append(("normalize_file", n, elapsed, res.get("output_rows", None)))

        # benchmark derive_fiscal_year separately
        # read back normalized output if produced
        norm_path = res.get("output_path")
        if norm_path and norm_path.exists():
            df2 = pd.read_csv(norm_path, dtype=str, low_memory=False)
            # coerce award_date to datetime
            dt = pd.to_datetime(df2.get("award_date"), errors="coerce")
            t0 = time.perf_counter()
            fy = derive_fiscal_year(dt)
            t1 = time.perf_counter()
            results.append(("derive_fiscal_year", n, t1 - t0, None))

    return results


def bench_dedup(sizes=(10000, 50000, 100000)):
    results = []
    for n in sizes:
        logger.info(f"Benchmark deduplicate: {n} rows")
        # create unique rows then duplicate ~30%
        unique = n - int(n * 0.3)
        df_unique = pd.DataFrame({
            "contract_id": ["CID-" + str(i) for i in range(unique)],
            "award_date": pd.date_range("2015-01-01", periods=unique).astype(str),
            "vendor_name": ["Vendor" + str(i % 50) for i in range(unique)],
            "obligated_amount": np.random.randint(100, 10000, size=unique),
            "source_file": ["f1"] * unique,
        })
        # create duplicates by sampling some rows
        dup = df_unique.sample(frac=0.3, replace=True, random_state=1)
        df = pd.concat([df_unique, dup], ignore_index=True)
        # shuffle
        df = df.sample(frac=1, random_state=2).reset_index(drop=True)

        t0 = time.perf_counter()
        out = deduplicate(df.copy(), logger)
        t1 = time.perf_counter()
        elapsed = t1 - t0
        removed = len(df) - len(out)
        results.append(("deduplicate", n, elapsed, removed))
    return results


def run_all():
    norm_res = bench_normalize()
    dedup_res = bench_dedup()

    out_file = OUT_DIR / "benchmark_results.txt"
    with out_file.open("w", encoding="utf-8") as f:
        f.write("Benchmark results:\n")
        for r in norm_res + dedup_res:
            f.write(f"{r}\n")

    # also print to stdout
    for r in norm_res + dedup_res:
        print(r)

if __name__ == "__main__":
    run_all()
