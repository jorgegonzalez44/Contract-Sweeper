#!/usr/bin/env bash
set -euo pipefail

# Require venv to be present; keeps CI and local behavior consistent
if [ ! -f .venv/bin/activate ]; then
  echo "No .venv found. Run: bash scripts/setup_env.sh" >&2
  exit 2
fi

. .venv/bin/activate

pytest -q \
  tests/test_config.py \
  tests/test_setup_directories.py \
  tests/test_validate_downloads.py \
  tests/test_normalize.py \
  tests/test_validate_coverage.py \
  tests/test_deduplicate_master.py \
  tests/test_sam_enrichment.py
