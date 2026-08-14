# OpenCode Execution Plan — Post-Audit Hardening (batches 1+2)

Repo: `C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main`
Branch: `fix/post-audit-phase-e-junctions-roundabouts-20260803`  (start @ `9447ebbd`, local==origin)
Interpreter: `./.venv/Scripts/python.exe`  ·  ALWAYS `export UP_DISABLE_CARLA=1`

**Audit (2026-08-13, by Claude Opus 4.8):** both task specs
(`OPENCODE_HARDENING_PROMPT_01.md` @ `57b5216e`, `OPENCODE_HARDENING_PROMPT_02.md` @ `9447ebbd`) are
committed but **UNEXECUTED** — all 6 tasks undone. Confirmed: drift-guard omits `opendrive_gen_diagnostic`;
no `test_evidence_sha256_anchors.py`; no length-invariant tests; no `MIRROR_DRIFT_INVENTORY`; no
`GOVERNANCE_CONVENTIONS.md`; `nul`/`vehicle.` still present; mirror drift ~30 drifted / ~508 identical.
This plan executes both batches.

## GLOBAL BOUNDARIES (violation = stop + report)
- Offline only. Do NOT run/require CARLA; do NOT touch the 7 failing gates, certifier logic,
  `run_n_certify.py` semantics, P04/P8/runtime evidence, or any sha256 anchor value.
- Do NOT mutate/move/delete any `.xodr` or anything under `campaigns/` or `cities/`.
- Do NOT reconcile/sync/"fix" the ~30 drifted mirror files — **INVENTORY only (Step 5)**. Reconciliation is Claude's.
- Edit only files named in the steps. If a step needs a design decision → STOP, mark `ESCALATE_TO_CLAUDE`.

## STEP 0 — baseline (record, do not skip)
```
export UP_DISABLE_CARLA=1
git rev-parse HEAD                                    # expect 9447ebbd (or later)
./.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -1   # record "<N> passed, 0 failed"  → BASELINE_N
```
Full task specs: `reports/post_audit_hardening/OPENCODE_HARDENING_PROMPT_01.md` and `_02.md`.

## ===== BATCH 1 (code + tests) — execute PROMPT_01 =====
**STEP 1 — drift-guard:** in `tests/phase_q/test_duplicate_module_drift.py` add
`"core/opendrive_gen_diagnostic.py"` to `CRITICAL_MIRRORED_FILES` (mirror is byte-identical; test must PASS).

**STEP 2 — coverage:** in `tests/unit/test_opendrive_gen_diagnostic.py` ADD tests (do not modify existing) for:
- `summarize_loads_jsonl(path)` via a synthetic `tmp_path` `.jsonl`;
- `sample_vram_mb()` → assert `== -1` OR `>= 0` (returns **-1 on headless** per docstring, `opendrive_gen_diagnostic.py:87`);
- the length-invariant path (`violations=0` / `roads_checked` scan). `run_n_certify` import is side-effect-free.

**STEP 3 — new `tests/unit/test_evidence_sha256_anchors.py` (read-only):**
parse `reports/post_audit_hardening/20260813T075853Z_N_CERTIFICATION/*.json`; extract embedded
`<name>_sha256=<hex>` from **string values** (not JSON keys); assert each is 64-char lowercase hex; for any
referenced artifact present locally verify sha256 matches, SKIP if absent (large XODRs uncommitted);
fail if zero anchors parsed.

**STEP 4 — verify + commit batch 1:**
```
./.venv/Scripts/python.exe -m pytest tests/phase_q/test_duplicate_module_drift.py tests/unit/test_opendrive_gen_diagnostic.py tests/unit/test_evidence_sha256_anchors.py -v   # all pass
./.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -1    # 0 failed; passed == BASELINE_N + (tests added)
git add <the 3 files>; git diff --cached --name-only       # exactly those 3
git commit -m "test(hardening): guard G19 mirror drift + diagnostic coverage + evidence sha256 anchors"
```

## ===== BATCH 2 (inventory + docs + hygiene) — execute PROMPT_02 =====
**STEP 5 — MIRROR_DRIFT_INVENTORY (read-only; DO NOT edit any drifted source):**
enumerate every `.py` present in BOTH `ultimate_pipeline/` and `submission/infrastructure/ultimate_pipeline/`
(excl `__pycache__`/`test_*`). Write `reports/post_audit_hardening/MIRROR_DRIFT_INVENTORY.md` (+`.json`):
per-file `identical|DRIFT`, byte sizes for DRIFT rows, whether guarded; summary counts; a
"DECISION NEEDED (Claude)" section listing drifted paths grouped by top dir — facts only, no fix.

**STEP 6 — `reports/post_audit_hardening/GOVERNANCE_CONVENTIONS.md`** (from existing evidence, don't invent):
large-XODR-uncommitted-anchored-by-sha256 refetch/verify; `scripts/` + `*_PROC_SMOKE` = scratch/untracked;
canonical vs submission mirror policy + drift-guard scope; cross-ref `SUMMARY_R17_G19.md`.

**STEP 7 — junk hygiene (guarded):** for `nul` and `vehicle.` verify each is 0-byte AND untracked
(`git ls-files --error-unmatch <f>` must FAIL); add both to `.gitignore` (required); best-effort
`rm -f -- ./nul "./vehicle."` (if Windows blocks reserved name `nul`, leave + note "manual removal needed").

**STEP 8 — verify + commit batch 2:**
```
./.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -1     # unchanged pass count, 0 failed (adds no tests)
git check-ignore nul vehicle.                              # both ignored
git add MIRROR_DRIFT_INVENTORY.md(+.json) GOVERNANCE_CONVENTIONS.md .gitignore (+ nul/vehicle. deletions)
git commit -m "chore(hardening): mirror-drift inventory + governance conventions + junk hygiene"
```

## STEP 9 — push + final report
```
git push origin fix/post-audit-phase-e-junctions-roundabouts-20260803
git rev-parse HEAD; git rev-parse @{u}                     # must be equal
```
Report (cite this plan + prompt SHAs `57b5216e`/`9447ebbd`):
- BASELINE_N vs final pytest summary lines (verbatim);
- files changed per commit + the 2 commit SHAs; local==remote (yes/no);
- drift inventory counts; `nul`/`vehicle.` removed or blocked;
- `ESCALATE_TO_CLAUDE` list.
- Verdict: `HARDENING_APPLIED_GREEN` | `PARTIAL` | `BLOCKED_NEEDS_DECISION`.

## SEQUENCING NOTES
- Batch 1 and Batch 2 are independent; complete Batch 1 (incl. its commit) before Batch 2 so a failure is
  isolated to one commit. Two commits total, one push.
- If STEP 4's full-suite count != BASELINE_N + added, STOP — do not "fix" unrelated tests.

## OUT OF SCOPE (Claude-only — do not attempt)
- Reconciling the ~30 drifted mirror pairs (bug vs intentional frozen-submission divergence).
- Live-CARLA P04 re-collection on candidate `6bac3570` → flipping the 7 stale gates.
- P4 architecture gate (only B4 cook-toolchain open) / C55V01b structural freeze / probe promotion /
  trailing-refresh freeze protocol.
