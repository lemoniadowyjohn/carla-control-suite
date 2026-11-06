# V22 PUBLICATION STATUS — V23 CLOSURE REPORT

## Actual Remote Branch
- Branch: `review/v21-consolidation-audit-20261106`
- Intended HEAD: `dc0fc811` (V22 Boolean fixes + V23 RQ1/RQ3 tooling fixes + review package docs)

## Git History Summary
```
a952f377 docs: update V22 publication status and start-here SHA references
89bab27e docs: V22 independent review package - 10 documents for V21 consolidation audit
be908432 fix: strict Boolean ok coercion in production gates (V22)
67c7026e fix: resolve environment-specific test fixture in test_verify_import_authority
19647d48 fix: Git provenance inspection (V15-C)
c57f6e46 fix: artifact sandbox and configuration consistency (V13)
72eb0f59 fix: experiment execution contracts (V12-V14)
457d0cca test: add R1 release receipt test file
d694b518 test: add G2/G3 regression test files
8969fa37 fix: G2 SHA-256 validation + G3 mandatory artifact check
dc0fc811 fix: RQ1 receipt generation and RQ3 manifest validation (V23)
```

## Actual GitHub PR
- **PR Number:** 25
- **URL:** https://github.com/lemoniadowyjohn/carla-control-suite/pull/25
- **State:** Open, Draft
- **Head:** `review/v21-consolidation-audit-20261106`
- **Base:** `integration/post-pr16-final-20261102`
- **Merge Base:** `c69b60d2fe4ac018136ea0fa26e435a09c15dd73`

## Actual Remote CI
- **Workflow:** offline research gates (run #42283304107)
- **Status:** Completed — Failure
  - Offline tests: FAILURE (CARLA not available in CI environment)
  - Offline evidence graph / freshness: SUCCESS
  - Package / wheel smoke: SUCCESS
  - Thesis RQ contract: SUCCESS
  - Research provenance: SUCCESS
  - Governance integrity: SUCCESS
  - Offline release gate: SKIPPED
- **Head SHA at CI time:** `a952f377a36eba9840cdbd7549401cac7d314c97`

## Local CI (on current committed source)
- Contract tests: 141 passed (was 136 before RQ3 manifest fixes; now includes RQ3 verification tests)
- RQ3 verifier unit tests: 5 passed
- All contract tests pass with the newly committed RQ1/RQ3 source fixes

## Review Package Files
All 11 documents confirmed present under `reports/independent_review/V22_FINAL_HANDOFF/`:
00_START_HERE.md through 09_INDEPENDENT_CHATGPT_REVIEW.md + 10_PUBLICATION_STATUS.md

## New OpenCode-Owned Changes
| File | Change | Status |
|------|--------|--------|
| tools/rq1_complete_receipt.py | Fixed: normalized_xodr before assignment, hardcoded run index, hardcoded git identity, placeholder topology/feature metrics, missing output digests | COMMITTED |
| tools/rq3_dataset_manifest_verifier.py | Added: frame/timestamp length mismatch, empty/duplicate frame IDs, missing capture files, quality_evaluation not performed, map identity/sensor transform/class map/route mismatch checks | COMMITTED |

## Outstanding Blockers (unchanged from handoff)
- **B1 T2b**: OPEN_DELEGATED (Codex: E:/wt/prod_68868f76) — Terminal lease authority
- **B2 F15b**: OPEN_DELEGATED (Codex: F:/wt-gap055-base) — Fail-closed artifact certification
- **B3 W-F**: REQUIRES_CHANGES (Claude/Codex: E:/wt/research-gap070-reversed-stubs-20261104) — Geometry review comments needed
- **B4 W-B**: PARTIALLY_COMPLETE (Codex: F:/carla-worktrees/rq5-sightb-20261009) — RQ5 remaining commits
- **B5 W-D**: TEST_SELECTION_UNVERIFIED — 26-test suite definition not recoverable
- **B6 Candidate b**: NOT YET PUBLISHED — AUTH-08 authorization pending
- **B7 RQ1-RQ5**: RQ1/RQ3 IMPLEMENTED & VERIFIED; scientific evidence still needs final classification
