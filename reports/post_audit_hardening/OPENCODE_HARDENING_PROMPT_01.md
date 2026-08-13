# OpenCode Hardening Task - Offline Drift-Guard + Test Coverage (C3-R17/G19 follow-up)

Prompt v1 (corrected from draft v0: `sample_vram_mb` contract fixed to the module's documented
`-1`-when-unavailable semantics; length-invariant road-scan coverage added to Task B).

## Context (read-only facts - do not re-litigate)
Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803  (tip fd677d5f, local==origin after pulling)
Interpreter: ./.venv/Scripts/python.exe  (Windows). Always set env UP_DISABLE_CARLA=1.
State: Phase-N certification is PHASE_N_CERTIFIER_REJECTED by design (13 pass / 7 fail), fail-closed
pending a live CARLA run. This is NOT a bug. You will NOT touch any of that.

## HARD BOUNDARIES - do only offline, mechanical hardening
Do NOT, under any circumstance:
- change any certifier / gate logic, the 7 failing gates, run_n_certify.py semantics, or any verdict;
- mutate, move, delete, or regenerate any .xodr / map artifact, or anything in campaigns/ or cities/;
- run or require CARLA; touch P04 / P8 / runtime evidence; change sha256 anchors;
- decide whether any scripts/ probe gets "promoted to production" (that is an architectural decision -
  STOP and leave a note for Claude instead);
- edit files outside those named in the tasks below.
If a task turns out to need a design decision, STOP and report it as ESCALATE_TO_CLAUDE.

## Task A - extend the duplicate-module drift guard to cover the G19 module  [difficulty 1]
File: tests/phase_q/test_duplicate_module_drift.py
- Add "core/opendrive_gen_diagnostic.py" to the CRITICAL_MIRRORED_FILES list (canonical
  ultimate_pipeline/core/... is already byte-identical to submission/infrastructure/ultimate_pipeline/core/...).
- Run the test - it must PASS (proving the mirror is in sync and now guarded).

## Task B - additive unit tests for currently-uncovered diagnostic functions  [difficulty 2]
File: tests/unit/test_opendrive_gen_diagnostic.py  (ADD tests only; do not modify existing tests or the module)
Read ultimate_pipeline/core/opendrive_gen_diagnostic.py and add focused tests for the public functions that
lack direct coverage - at minimum:

- summarize_loads_jsonl(path): write a tiny synthetic .jsonl to tmp_path with 2-3 load records and assert the
  summary fields it returns (attempts / verdict) match the input.
- sample_vram_mb(): assert it returns an int and never raises. IMPORTANT - the module's documented contract
  (docstring on the function) returns -1 when no GPU is available; on this headless workstation -1 is the
  EXPECTED value. Valid assertion: result == -1 or result >= 0. Do NOT assert ">= 0" unconditionally.
- _length_invariant_evidence(candidate_xodr) from run_n_certify.py (importable safely: verified stdlib-only
  imports, no module-level side effects; import run_n_certify directly):
  1. write a tmp XODR whose road has a planView geometry with s + length exceeding the road's declared
     length -> assert violations >= 1 and roads_checked == 1;
  2. write a compliant road (geometry fits within declared length) -> assert violations == 0, roads_checked == 1;
  3. a road with non-positive/missing length -> excluded from violations, still counted in roads_checked.

Keep tests deterministic and offline. Use pytest tmp_path for any files.

## Task C - read-only sha256-anchor consistency test  [difficulty 2]
New file: tests/unit/test_evidence_sha256_anchors.py
- Scan reports/post_audit_hardening/20260813T075853Z_N_CERTIFICATION/*.json.
- Extract every embedded anchor of the form `<name>_sha256=<hex>` from string values (the digests live INSIDE
  evidence strings, e.g. "runtime_sha256=9630d9f6... length=...", not as JSON keys).
- Assert each extracted digest is a well-formed 64-char lowercase hex string.
- For any referenced artifact file that EXISTS locally, verify its sha256 matches the recorded digest;
  SKIP (do not fail) when the artifact is absent - large XODRs (~78-81 MB) are intentionally uncommitted.
- The test must pass on the current evidence with at least one anchor found (fail if zero anchors parsed -
  that would mean the parser is wrong).

## Verification (mandatory, evidence before claims)
1. BEFORE any change: record the baseline - `UP_DISABLE_CARLA=1 ./.venv/Scripts/python.exe -m pytest -q`
   -> note "<N> passed, 0 failed".
2. AFTER changes: re-run the same command. Requirement: 0 failed, and passed count = baseline + (number of
   tests you added). If any pre-existing test changed status, STOP and report - do not "fix" unrelated tests.
3. Also run the two touched suites explicitly:
   `... -m pytest tests/phase_q/test_duplicate_module_drift.py tests/unit/test_opendrive_gen_diagnostic.py tests/unit/test_evidence_sha256_anchors.py -v`

## Git hygiene
- Stage ONLY the files you created/edited (Task A file, Task B file, Task C new file). Never stage: nul,
  vehicle., .idea/, __pycache__/, .pytest_cache/, scripts/, campaigns/, any .xodr, reports/*_PROC_SMOKE/.
- `git diff --cached --name-only` must show exactly those 3 files.
- One commit: `test(hardening): guard G19 mirror drift + cover diagnostic funcs + evidence sha256 anchors`.
- Push the branch; verify `git rev-parse HEAD == git rev-parse @{u}`.

## Report back
- Baseline vs final pass counts (verbatim pytest summary lines).
- Files changed. Commit SHA. local==remote (yes/no).
- Any ESCALATE_TO_CLAUDE items (things that needed a decision).
Verdict: HARDENING_APPLIED_GREEN | PARTIAL | BLOCKED_NEEDS_DECISION.