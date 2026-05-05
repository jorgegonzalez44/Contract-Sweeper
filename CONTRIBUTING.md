Contribution guide — Contract-Sweeper

Quick start

1. Create a Python venv and install deps:

   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip setuptools wheel
   pip install -r requirements.txt

2. Run the smoke tests (fast):

   bash scripts/run_smoke_tests.sh

3. Run full tests locally:

   python -m pytest tests/ -v

Code style & commits

- Keep changes focused and surgical. Run tests for the area you modify.
- Add tests for new features or reproductions for bug fixes.

Secrets & API keys

- Use environment variables (or a local .env file not committed). See .env.example for keys used by optional enrichment steps.

CI

- A lightweight smoke workflow runs on PRs; the full test matrix runs on main or on schedule. Avoid committing large datasets; use data/staging/placeholder for CI fixtures.