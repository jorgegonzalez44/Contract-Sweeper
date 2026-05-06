#!/usr/bin/env python3
"""
Automated test harness for all Contract-Sweeper download scripts.

Tests each download script for:
- Successful execution (exit code 0)
- Output file creation
- Basic data validation (non-empty files)

Usage:
  python3 scripts/test_all_downloads.py              # test all scripts
  python3 scripts/test_all_downloads.py --script download_grants.py  # test specific script
  python3 scripts/test_all_downloads.py --parallel 4  # run 4 in parallel
  python3 scripts/test_all_downloads.py --dry-run     # just check script syntax, no execution
"""

import argparse
import asyncio
import glob
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import PROJECT_ROOT, setup_logging

logger = setup_logging(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCRIPT_DIR = PROJECT_ROOT / "scripts"
DOWNLOAD_SCRIPTS = sorted(glob.glob(str(SCRIPT_DIR / "download_*.py")))
TIMEOUT_SECONDS = 300  # 5 minutes per script
MAX_PARALLEL = 4

# Expected output patterns for each script (to be expanded)
EXPECTED_OUTPUTS = {
    "download_grants.py": [
        "data/staging/processed/pr_grants_master.csv",
        "data/staging/raw/grants/grants_pop.csv",
    ],
    "download_contralor.py": [
        "data/staging/processed/pr_contralor_audits.csv",
        "data/staging/processed/pr_contralor_contracts.csv",
    ],
    # Add more as needed
}

# ---------------------------------------------------------------------------
# Test Functions
# ---------------------------------------------------------------------------

async def run_script_async(script_path: str, force: bool = False) -> Tuple[str, int, str, float]:
    """Run a single download script asynchronously."""
    script_name = Path(script_path).name
    cmd = [sys.executable, script_path]
    if force:
        cmd.append("--force")

    start_time = time.time()
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(PROJECT_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=TIMEOUT_SECONDS)
        exit_code = process.returncode
    except asyncio.TimeoutError:
        try:
            process.kill()
        except:
            pass
        return script_name, -1, "TIMEOUT", time.time() - start_time
    except Exception as e:
        return script_name, -2, f"ERROR: {str(e)}", time.time() - start_time

    return script_name, exit_code, stderr.decode() + stdout.decode(), time.time() - start_time

def check_output_files(script_name: str) -> List[str]:
    """Check if expected output files exist and are non-empty."""
    issues = []
    expected = EXPECTED_OUTPUTS.get(script_name, [])

    for output_path in expected:
        full_path = PROJECT_ROOT / output_path
        if not full_path.exists():
            issues.append(f"Missing: {output_path}")
        elif full_path.stat().st_size == 0:
            issues.append(f"Empty: {output_path}")
        else:
            # Basic validation - check if it's a CSV with headers
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    first_line = f.readline().strip()
                    if not first_line or ',' not in first_line:
                        issues.append(f"Invalid format: {output_path}")
            except Exception as e:
                issues.append(f"Read error {output_path}: {str(e)}")

    return issues

def validate_script_syntax(script_path: str) -> bool:
    """Check if script has valid Python syntax."""
    try:
        with open(script_path, 'r') as f:
            compile(f.read(), script_path, 'exec')
        return True
    except SyntaxError as e:
        logger.error(f"Syntax error in {script_path}: {e}")
        return False

# ---------------------------------------------------------------------------
# Main Test Runner
# ---------------------------------------------------------------------------

async def test_scripts(scripts: List[str], parallel: int = 1, force: bool = False, dry_run: bool = False) -> Dict[str, dict]:
    """Test all specified scripts."""
    results = {}

    if dry_run:
        logger.info("Running dry-run syntax check...")
        for script in scripts:
            script_name = Path(script).name
            syntax_ok = validate_script_syntax(script)
            results[script_name] = {
                "status": "SYNTAX_OK" if syntax_ok else "SYNTAX_ERROR",
                "exit_code": 0 if syntax_ok else 1,
                "output": "",
                "duration": 0.0,
                "output_issues": []
            }
        return results

    semaphore = asyncio.Semaphore(parallel)

    async def test_single(script: str) -> None:
        async with semaphore:
            script_name = Path(script).name
            logger.info(f"Testing {script_name}...")

            name, exit_code, output, duration = await run_script_async(script, force)

            output_issues = check_output_files(script_name) if exit_code == 0 else []

            results[script_name] = {
                "status": "PASS" if exit_code == 0 and not output_issues else "FAIL",
                "exit_code": exit_code,
                "output": output[-1000:],  # Last 1000 chars
                "duration": duration,
                "output_issues": output_issues
            }

            status = results[script_name]["status"]
            logger.info(f"{script_name}: {status} ({duration:.1f}s)")

    await asyncio.gather(*[test_single(script) for script in scripts])

    return results

def print_summary(results: Dict[str, dict]) -> None:
    """Print test summary."""
    total = len(results)
    passed = sum(1 for r in results.values() if r["status"] == "PASS")
    failed = total - passed

    print(f"\n{'='*60}")
    print(f"TEST SUMMARY: {passed}/{total} passed ({failed} failed)")
    print(f"{'='*60}")

    if failed > 0:
        print("\nFAILED SCRIPTS:")
        for name, result in results.items():
            if result["status"] != "PASS":
                print(f"  {name}: {result['status']} (exit {result['exit_code']})")
                if result["output_issues"]:
                    for issue in result["output_issues"]:
                        print(f"    - {issue}")
                if "TIMEOUT" in result["output"]:
                    print("    - Timeout")
                elif result["output"]:
                    print(f"    - Error: {result['output'][:200]}...")

    # Performance summary
    durations = [r["duration"] for r in results.values() if r["duration"] > 0]
    if durations:
        avg_time = sum(durations) / len(durations)
        max_time = max(durations)
        print(f"Average time: {avg_time:.1f}s")
        print(f"Max time: {max_time:.1f}s")
# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global TIMEOUT_SECONDS
    parser = argparse.ArgumentParser(description="Test Contract-Sweeper download scripts")
    parser.add_argument("--script", help="Test specific script (filename only)")
    parser.add_argument("--parallel", type=int, default=1, help="Number of parallel tests")
    parser.add_argument("--force", action="store_true", help="Force re-download for scripts")
    parser.add_argument("--dry-run", action="store_true", help="Check syntax only, don't execute")
    parser.add_argument("--timeout", type=int, default=TIMEOUT_SECONDS, help="Timeout per script")

    args = parser.parse_args()

    TIMEOUT_SECONDS = args.timeout

    if args.script:
        scripts = [str(SCRIPT_DIR / args.script)]
        if not Path(scripts[0]).exists():
            logger.error(f"Script not found: {args.script}")
            return 1
    else:
        scripts = DOWNLOAD_SCRIPTS

    logger.info(f"Testing {len(scripts)} scripts with parallel={args.parallel}")

    # Run tests
    results = asyncio.run(test_scripts(scripts, args.parallel, args.force, args.dry_run))

    print_summary(results)

    # Exit with failure if any tests failed
    failed = sum(1 for r in results.values() if r["status"] != "PASS")
    return 1 if failed > 0 else 0

if __name__ == "__main__":
    sys.exit(main())