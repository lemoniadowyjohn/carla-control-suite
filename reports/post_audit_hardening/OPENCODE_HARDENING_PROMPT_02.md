# OpenCode Hardening Task - Batch 2 (offline hygiene + drift inventory)
# Parent: 57b5216e (batch 1). Same repo/branch/interpreter/boundaries as batch 1.

Prompt v2. Fact corrections vs draft: preliminary drift scan counts 33 drifted / 498 identical of 531 pairs
(.py, excluding test_* and __pycache__, byte-compare) - NOT 27/486; the exact inventory is Task D's
authoritative output, so no magic number is asserted here. Root junk files nul + vehicle. verified present,
0 bytes, untracked (via `\\?\` literal paths; PowerShell/cmd normalize these names and may claim absence).

## Context (read-only facts)
Repo: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main
Branch: fix/post-audit-phase-e-junctions-roundabouts-20260803  (local==origin after pulling)
Interpreter: ./.venv/Scripts/python.exe ; always UP_DISABLE_CARLA=1.
Certification is PHASE_N_CERTIFIER_REJECTED by design (fail-closed, live-CARLA blocker). You touch NONE of that.
Offline test health: 623 tests collected, 0 errors (verified 2026-08-13).

## HARD BOUNDARIES (unchanged from batch 1) - offline, mechanical only
Do NOT: change certifier/gate logic or any of the 7 failing gates; mutate any .xodr/map/campaigns/cities artifact;
run or require CARLA; touch P04/P8/runtime evidence or sha256 anchors; edit files outside those named below.
**Do NOT reconcile, sync, or "fix" the drifted mirror files** (see Task D) - that is a Claude decision.
If any task needs a design decision, STOP and report ESCALATE_TO_CLAUDE.

## Task D - mirror-drift INVENTORY (read-only report; do NOT modify any mirrored file)  [difficulty 2]
There are ~33 files that differ between `ultimate_pipeline/` and `submission/infrastructure/ultimate_pipeline/`
(~498 identical). Produce an inventory so Claude can decide which drifts are bugs vs intentional.
- New file: reports/post_audit_hardening/MIRROR_DRIFT_INVENTORY.md  (+ .json)
- For every .py present in BOTH trees (exclude __pycache__ and test_*), record: relative path, identical|DRIFT,
  and for DRIFT rows the byte sizes of each side + whether it's on the drift-guard list
  (tests/phase_q/test_duplicate_module_drift.py CRITICAL_MIRRORED_FILES).
- Summary counts (identical / drifted / guarded / unguarded-drifted).
- Write a short "DECISION NEEDED (Claude)" section listing the drifted paths, grouped by top dir - NO
  recommendation, just the facts. You MUST NOT edit any of the drifted source files.

## Task E - governance conventions doc  [difficulty 1]
New file: reports/post_audit_hardening/GOVERNANCE_CONVENTIONS.md documenting the project's non-obvious
conventions (read them from existing evidence/ledger; do not invent policy):
- Large XODR artifacts (~78-81 MB) are intentionally UNCOMMITTED, anchored by sha256 inside evidence JSON strings
  (form `<name>_sha256=<hex>`); how a verifier refetches + checks a local copy against its recorded digest.
- `scripts/` and probe/*_PROC_SMOKE logs are scratch/untracked by convention; promotion to production requires
  mirroring + drift-guard registration (Claude decision).
- Canonical `ultimate_pipeline/` vs `submission/infrastructure/` mirror policy; drift guard only protects the
  load-path-critical set; full drift status lives in MIRROR_DRIFT_INVENTORY.md.
Keep it factual and short; cross-reference SUMMARY_R17_G19.md.

## Task F - stray junk hygiene (guarded)  [difficulty 1]
Two 0-byte untracked junk files exist at repo root: `nul` and `vehicle.` (Windows redirect accidents).
- FIRST verify each is (a) 0 bytes AND (b) untracked (`git ls-files --error-unmatch <f>` must FAIL). If either
  check fails for a file, DO NOT touch it - report it instead.
- NOTE: PowerShell/cmd resolve `nul` to the NUL device and normalize `vehicle.`'s trailing dot; use the
  `\\?\` literal prefix (e.g. os.stat(r"\\?\C:\<abs-path>\nul")) or `Get-Item -LiteralPath '\\?\...'` for checks
  and removal. Verification is done (0 bytes, untracked) - but re-verify before touching.
- Add `nul` and `vehicle.` to .gitignore (defensive, non-destructive) - this is the required part.
- Best-effort removal of the two verified 0-byte junk files; if Windows blocks the reserved name `nul`,
  leave it and note "manual removal needed" - do not force.
Do NOT delete anything else.

## Verification (evidence before claims)
1. BEFORE: `UP_DISABLE_CARLA=1 ./.venv/Scripts/python.exe -m pytest -q` -> record "<N> passed, 0 failed"
   (batch-1 baseline; 623 collected, 0 errors).
2. AFTER: re-run -> 0 failed, passed count unchanged (this batch adds no tests). If any test changed status, STOP.
3. `git check-ignore nul vehicle.` -> both ignored.

## Git hygiene
- Stage ONLY: reports/post_audit_hardening/MIRROR_DRIFT_INVENTORY.md(+.json),
  reports/post_audit_hardening/GOVERNANCE_CONVENTIONS.md, .gitignore.
- Never stage: any .xodr, campaigns/, scripts/, __pycache__, *_PROC_SMOKE/, the drifted mirror files.
- `git diff --cached --name-only` must show exactly those 3-4 files (+ deletions of nul/vehicle. if removed).
- One commit: `chore(hardening): mirror-drift inventory + governance conventions + junk hygiene`.
- Push; verify `git rev-parse HEAD == git rev-parse @{u}`.

## Report back (reference this prompt's commit SHA)
- Baseline vs final pytest summary lines (verbatim).
- Drift inventory counts (identical / drifted / unguarded-drifted).
- Files changed; nul/vehicle. removed? (yes/blocked); commit SHA; local==remote.
- ESCALATE_TO_CLAUDE list.
Verdict: HARDENING_APPLIED_GREEN | PARTIAL | BLOCKED_NEEDS_DECISION.

## NOT delegated (Claude decisions; opencode MUST NOT act on these)
- Reconciling the drifted mirror pairs (Task D inventory is input to that decision).
- The 7-gate flip / live P04 re-collection on 6bac3570.
- Probe promotion (scripts/ -> production + hash-register).
- Trailing-refresh freeze-commit protocol.