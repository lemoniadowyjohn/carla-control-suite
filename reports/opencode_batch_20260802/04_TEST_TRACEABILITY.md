# 04_TEST_TRACEABILITY.md

**Task:** TEST-TRACE-001 (Plan mode — reports only)
**Generated:** 2026-08-02
**Base:** 2961c624 (post SYS-001)

## 1. REQUIREMENT_TEST_MATRIX.csv (218 rows)

Every tracked formal requirement mapped from the audit's authoritative
`tests` evidence (`audit_output/04_REQUIREMENT_RESULTS.jsonl`) with:
requirement_id, subsystem, verification_state, implementation_state,
evidence_level, required_evidence_level, evidence_met, tests_required,
tests_executed, passed/failed/skipped, test_references, note.

Also produced: `05B_TEST_COLLECTION_INVENTORY.json` — 83 test files scanned.

## 2. Collection inventory

- 452 tests collected, 0 collection errors (`python -m pytest --collect-only -q`)
- 83 test files under `ultimate_pipeline/tests`, donor tests excluded from
  canonical collection by SYS-001 decision
- CARLA server tests exist but are marked `@pytest.mark.carla` / guarded by
  connectivity probes; skipped when no server (expected, not hidden)

## 3. Weak assertions (06B_WEAK_ASSERTIONS.json — 2607 candidates, pre-triage)

| Pattern | Meaning | Count |
|---|---|---|
| unconditional-return | `return True/PASS/OK/None/[]` on success path | sampled |
| bare-pass | `pass` outside class/def in same window | sampled |

Triage notes (plan):
- The scan is intentionally over-broad; most `return None` are legitimate
  void functions and `pass` live in `except` clauses.
- Actionable categories to review in P11 static sweep:
  - validators returning success by default (BLD-005 class)
  - `except Exception: return 0.0/None` swallowing evidence (run_perception_safe ECE)
  - docstring-only stubs (ELV-009 seam fixer class)

## 4. NEGATIVE_CONTROL_GAPS.md (from audit results)

| Pattern | Count | Notes |
|---|---|---|
| PASS with evidence_met=false | 11 | all downgraded by A2 logic (P02) |
| PASS with mandatory negative control not executed | 16 | downgraded |
| PASS with unresolved contradictions | 12 | downgraded |
| PASS records missing `negative_control` key entirely | 0 | all records carry the key |

No PASS remains in `corrected_status` without full evidence: verified by
`assert_no_invalid_pass` (P02 tests) — 6 PASS sustained.

## 5. TEST_FILE_OWNERSHIP.csv

Ownership reserved for later build agents (see 05_FILE_OWNERSHIP_MATRIX.csv
from P01); the traceability scan touched no test files.

## Verdict

**TRACEABILITY_READY** (matrix + inventory + gap analysis produced;
remaining "weak" candidates are triage inputs for P11, not blockers).
