#!/usr/bin/env bash
set -euo pipefail

# Create and activate a lightweight venv, then install runtime deps
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

echo "Virtualenv ready. Activate with: source .venv/bin/activate"