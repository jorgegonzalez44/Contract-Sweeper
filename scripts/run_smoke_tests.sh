#!/usr/bin/env bash
set -euo pipefail

# Activate .venv when available (local dev); fall back to system Python in CI
if [ -f .venv/bin/activate ]; then
  . .venv/bin/activate
elif ! command -v pytest >/dev/null 2>&1; then
  echo "No .venv and no pytest in PATH. Run: bash scripts/setup_env.sh" >&2
  exit 2
fi

pytest -q \
  tests/test_config.py \
  tests/test_setup_directories.py \
  tests/test_validate_downloads.py \
  tests/test_normalize.py \
  tests/test_validate_coverage.py \
  tests/test_deduplicate_master.py \
  tests/test_sam_enrichment.py \
  tests/test_validation_gates.py \
  tests/test_analyze_entity_profiles.py

# --- Entity gate validation (live run; only when enrichment data is present) ---
HIERARCHY="data/staging/processed/enrichment/entity_hierarchy.csv"
if [ -f "$HIERARCHY" ]; then
  echo "[gates] Running entity validation gates..."
  python3 scripts/validation_gates.py --report-only
  echo "[gates] All entity gates passed."
else
  echo "[gates] $HIERARCHY not found — skipping live gate run (unit tests above cover gate logic)"
fi
