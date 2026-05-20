# Task Branch Integration Audit

**Generated:** 2026-05-20  
**Audited against:** `main` @ `04646dc`  
**Total remote `claude/` branches:** 61

---

## Summary

| Metric | Count |
|--------|-------|
| Total `claude/` branches | 61 |
| Merged / at main HEAD | 8 |
| Open (ahead of main) | 53 |
| Missing (T46) | 1 |
| Blocked — awaiting approval | 1 (T92) |
| Blocked — network policy | 1 (T93 live SAM lookup) |
| Superseded | 1 (T94 by T100) |
| INT-0 hotfix (ready to merge) | 1 (`fix-subawards-raw-rows-key`) |

---

## Merged / At Main HEAD (Empty — safe to delete)

These branches point to the same SHA as `main` and carry no pending changes.

| Branch | Status |
|--------|--------|
| `claude/task30-test-ingest-cabilderos` | merged |
| `claude/task34-test-validate-fema-pa` | merged |
| `claude/task38-extend-validate-downloads` | merged |
| `claude/task40-test-benchmark-perf` | merged |
| `claude/task42-test-link-hud-drgr-assets` | merged |
| `claude/task44-extend-web-fetch` | merged |
| `claude/task45-conftest-http-fixtures` | merged |
| `claude/task53-test-download-sba` | merged |

---

## INT-0 Hotfix — Ready to Merge

### `claude/fix-subawards-raw-rows-key`

**Priority:** Immediate — fixes a silent data bug causing `raw_rows` to always be 0.

| Attribute | Value |
|-----------|-------|
| Commits ahead of main | 5 |
| Files changed | 4 |
| Merge conflicts vs main | 0 |
| CI gate | passes (62/62 tests) |

**Files changed:**
- `scripts/download_subawards.py` — core bug fix (key name `grant_rows` → `grants_rows`)
- `data/manifests/validation_report.json` — T93 documentation
- `.github/workflows/tests.yml` — T100 CI threshold (40%)
- `requirements.txt` — T48 pytest-xdist

**Root cause:** `download_window()` initialised stats with keys `"grant_rows"` / `"contract_rows"` (singular) but the loop body wrote `f"{type_group}_rows"` = `"grants_rows"` / `"contracts_rows"` (plural). The accumulator in `_run()` read the singular keys, always getting 0.

**Note:** This branch accumulated commits from Tasks 48, 93, 94, 100 before the fix was added. Those changes are all non-conflicting and additive.

---

## Missing Branch — T046R1 Recommendation

### `claude/task46-conftest-parquet-fixture` — NEVER CREATED

Task 46 (add shared `pq_factory` fixture to `tests/conftest.py`) was planned but no branch was ever pushed. The current `conftest.py` has no `pq_factory` fixture.

**Impact:** Tasks 34–36, 41–43 each implement their own parquet write setup instead of sharing a fixture. Not a functional gap, but a maintenance debt.

**Recommendation (T046R1):** Create branch `claude/task46r1-conftest-parquet-fixture` and add:
```python
@pytest.fixture
def pq_factory(tmp_path):
    def _write(df, rel_path):
        from scripts.parquet_utils import pq_write
        full = tmp_path / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        return pq_write(df, full)
    return _write
```

---

## Blocked Tasks

### T92 — PR3 Dedup Implementation
**Status:** BLOCKED — awaiting explicit scope approval from user  
**Branch:** not yet created  
**Dependency:** Scope defined in `data/source_registry.yaml` (T91, `claude/task91-pr3-dedup-scope`) — gate `alias_dedup_reduction_rate` added with threshold 0.30, status `APPROVED_SCOPE_PENDING_IMPL`  
**Action required:** User must confirm: "T92 approved — proceed with PR3 dedup implementation"

### T93 — V-COMS Inc SAM Resolution (live lookup)
**Status:** BLOCKED — container network policy blocks all outbound HTTP  
**Branch:** `claude/task93-vcoms-resolution` (documentation committed)  
**UEI:** `VCOMS5L8Q2V7`  
**Gate impact:** `high_value_unresolved_review_rate` currently 0.0909 (1/11) — gate passes at ≤ 0.10  
**Action required:** Run locally with `SAM_API_KEY` set:
```bash
python3 scripts/sam_enrichment.py --top 1
python3 scripts/parent_collapse.py
python3 scripts/validation_gates.py --report-only
```

---

## Superseded Branches

### T94 — `claude/task94-ci-coverage-30`
**Superseded by:** `claude/task100-ci-coverage-40` (40% threshold is a superset of 30%)  
Both modify `.github/workflows/tests.yml`. T100 includes the artifact upload step T94 lacks.  
**Recommendation:** Merge T100 only; do not merge T94 separately.

---

## Open Task Branches (Priority Order)

### Batch Branches (contain multiple tasks each)

| Branch | Tasks | Test Files | Notes |
|--------|-------|-----------|-------|
| `claude/tasks51-77-download-tests-batch` | 51–68 (partial) | 16 | includes fixed `test_download_subawards.py` |
| `claude/tasks69-77-download-tests-batch` | 69–77 (partial) | 9 | — |
| `claude/tasks78-90-download-tests-batch` | 78–90 | 12 | includes fixed slfrf + research tests |
| `claude/tasks96-99-download-tests` | 95–100 (partial) | 10 + CI + requirements | includes `test_pipeline_smoke.py` |

### Individual Task Branches

| Branch | Files | Notes |
|--------|-------|-------|
| `claude/task1-test-parent-collapse` | 1 | — |
| `claude/task2-test-parquet-utils` | 1 | — |
| `claude/task3-test-dominance-analysis` | 2 | — |
| `claude/task4-test-fec-crossref` | 1 | — |
| `claude/task5-test-prime-sub` | 1 | — |
| `claude/task8-test-entity-resolution` | 1 | — |
| `claude/task9-test-normalize-hud-drgr` | 1 | — |
| `claude/task10-test-financial-flows` | 2 | — |
| `claude/task11-test-power-network` | 1 | — |
| `claude/task12-source-coverage-gate` | 3 | — |
| `claude/task14-test-lobbying-crossref` | 1 | — |
| `claude/task15-ci-coverage-threshold` | 2 | superseded by T100 for threshold, but adds linting |
| `claude/task16-test-parent-collapse` | 1 | — |
| `claude/task17-test-parquet-utils` | 1 | — |
| `claude/task18-test-ingest-report-builder` | 2 | — |
| `claude/task19-test-normalize-expansion` | 1 | — |
| `claude/task20-test-generate-report` | 1 | — |
| `claude/task21-extend-build-unified-master` | 1 | — |
| `claude/task22-test-auto-download-helpers` | 1 | — |
| `claude/task23-test-lda-enrich-extended` | 1 | — |
| `claude/task24-test-config-extended` | 1 | — |
| `claude/task25-test-sam-enrichment-extended` | 1 | — |
| `claude/task26-test-ingest-fema-pa` | 1 | — |
| `claude/task27-test-ingest-hud-drgr-exports` | 2 | — |
| `claude/task28-test-ingest-contralor` | 2 | — |
| `claude/task29-test-ingest-prasa` | 1 | — |
| `claude/task31-test-ingest-active-contractors` | 1 | — |
| `claude/task32-test-parse-highergov-pdfs` | 1 | — |
| `claude/task33-test-fetch-highergov-api` | 1 | — |
| `claude/task35-test-validate-hud-drgr-amounts` | 1 | — |
| `claude/task36-test-validate-hud-drgr-coverage` | 2 | — |
| `claude/task37-test-validate-expansion` | 3 | — |
| `claude/task39-extend-validate-coverage` | 1 | — |
| `claude/task41-test-link-fema-pa` | 4 | — |
| `claude/task43-test-link-hud-drgr-contracts` | 2 | — |
| `claude/task47-ci-coverage-20` | 3 | superseded by T100 for threshold |
| `claude/task48-ci-parallel-tests` | 2 | included in fix-subawards branch |
| `claude/task49-source-coverage-actuals` | 2 | — |
| `claude/task50-pre-commit-config` | 2 | — |
| `claude/task52-test-download-fema` | 1 | — |
| `claude/task91-pr3-dedup-scope` | 13 | scope YAML + test files |
| `claude/task93-vcoms-resolution` | 3 | V-COMS docs, network-blocked |
| `claude/task94-ci-coverage-30` | 2 | superseded by T100 |
| `claude/task95-pipeline-smoke` | 3 | 115-test smoke suite |

---

## Next Integration PR Recommendation

**Recommended merge order** (to minimize conflicts on CI-touching files):

1. `claude/fix-subawards-raw-rows-key` — INT-0, merge immediately
2. `claude/tasks51-77-download-tests-batch` — 16 test files, no script changes
3. `claude/tasks69-77-download-tests-batch` — 9 test files, no script changes  
4. `claude/tasks78-90-download-tests-batch` — 12 test files, no script changes
5. `claude/tasks96-99-download-tests` — includes CI + requirements changes; merge last among test batches
6. Individual task branches 1–50 (by number, resolving any CI file conflicts)
7. `claude/task91-pr3-dedup-scope` — data/source_registry.yaml change
8. `claude/task93-vcoms-resolution` — manifest documentation
9. `claude/task95-pipeline-smoke` — 115 smoke tests
10. T92 — only after explicit approval

**Do NOT merge T94 separately** — T100 supersedes it.
