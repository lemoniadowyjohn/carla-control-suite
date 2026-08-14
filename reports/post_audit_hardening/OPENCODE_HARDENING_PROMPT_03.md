# OpenCode Hardening — Batch 3 (offline live-run de-risking)

Repo: `C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main`
Branch: `fix/post-audit-phase-e-junctions-roundabouts-20260803` (start @ `183d6085`, local==origin)
Interpreter: `./.venv/Scripts/python.exe` · ALWAYS `export UP_DISABLE_CARLA=1`

**Why this batch:** the offline *hardening* backlog is exhausted; the remaining blocker is a live CARLA run
to re-collect P04 evidence on the signed candidate. This batch builds the **offline pre-run gate** that stops a
runtime pass being wasted on the wrong candidate — the exact `80ebb00`-vs-`6bac3570` trap. No CARLA is run here.

## The concrete trap (verified facts)
`campaigns/ingolstadt_cooked_perception_v1/candidate/` holds 8+ `.xodr` files. Two are decision-critical:
- **SIGNED target** `ingolstadt_perception_final_repaired.xodr`
  sha256 `6bac3570ce8f4230836ace27ec26155bbed58171567a6e0afd47e710c86dcb02` (UNTRACKED, ~80 MB, gitignored).
- **SUPERSEDED** `ingolstadt_fixed_final.xodr`
  sha256 `80ebb0054afd73ffdd51960b48679ff4689c72ed0abe75af5b2ae10a51395699` (TRACKED) — this is what P04 currently
  pins, causing G2 `WRONG_CANDIDATE_HASH`.
- Also present: `ingolstadt_perception_final_repaired_v2.xodr` (`1f2b5ff0…`) and others. **Do NOT guess which is
  authoritative** — the expected digest is always an INPUT you are given, never something you decide.

## GLOBAL BOUNDARIES (violation = stop + report ESCALATE_TO_CLAUDE)
- Offline only. Do NOT run/require CARLA. Do NOT mutate/move/delete any `.xodr` or anything under `campaigns/`.
- Do NOT change `run_n_certify.py` or any certifier/gate logic (T2 is a NEW standalone utility, not a certifier edit).
- Do NOT decide which candidate is "signed"/authoritative (Claude's call; you receive the digest as an arg).
- Edit only files named below.

## T1 — candidate digest inventory (read-only)  [difficulty 1]
New: `reports/post_audit_hardening/CANDIDATE_DIGEST_INVENTORY.md` (+ `.json`).
For every `*.xodr` in `campaigns/ingolstadt_cooked_perception_v1/candidate/`: filename, full sha256, byte size,
tracked-or-untracked (`git ls-files --error-unmatch`). Facts only; add a "ROLE LABELS NEEDED (Claude)" section
listing the files — do NOT assign roles.

## T2 — reusable pre-run candidate-identity gate + test  [difficulty 2]
New standalone util `tools/verify_candidate_digest.py` (does NOT import or modify run_n_certify):
- CLI: `--xodr <path> --expected <full-sha256>`; compute the file's sha256; print `GO` + digest on match,
  `NO-GO` + both digests on mismatch, `NO-GO MISSING` if the file is absent; exit `0` on match else `1`.
- Provide a `verify(path, expected) -> bool` function for import.
New test `tests/unit/test_verify_candidate_digest.py` (use the real files, skip-if-absent):
- match: `ingolstadt_perception_final_repaired.xodr` vs expected `6bac3570ce8f4230836ace27ec26155bbed58171567a6e0afd47e710c86dcb02` → `verify()` True / exit 0;
- mismatch: `ingolstadt_fixed_final.xodr` vs the same expected → False / exit 1;
- missing path → False / exit 1;
- a synthetic tmp file with a known digest → True (so the test never fully skips).

## T3 — operator runbook  [difficulty 1]
New: `reports/post_audit_hardening/LIVE_RUN_RUNBOOK.md`. Steps for the human runtime operator:
0. Confirm CARLA server reachable on the pinned build (server pin `10033a16`).
1. **Gate:** `python tools/verify_candidate_digest.py --xodr campaigns/.../ingolstadt_perception_final_repaired.xodr
   --expected 6bac3570ce8f4230836ace27ec26155bbed58171567a6e0afd47e710c86dcb02` → MUST print `GO` before proceeding.
   (Leave the expected digest exactly as above; Claude has confirmed it is the signed target.)
2. Re-collect P04 / Phase-L runtime evidence on that candidate; then
   `python run_n_certify.py --profile perception --candidate-xodr campaigns/.../ingolstadt_perception_final_repaired.xodr`.
3. Expected: G2/G5/G6/G7/G14/G15/G18 flip stale→PASS → **20/20**; else certification stays REJECTED.
Cross-reference `SUMMARY_R17_G19.md` and `MIRROR_DRIFT_ADJUDICATION.md`.

## Verification (evidence before claims)
```
export UP_DISABLE_CARLA=1
./.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -1     # BASELINE: 632 passed, 0 failed
# ... apply T1-T3 ...
./.venv/Scripts/python.exe -m pytest tests/unit/test_verify_candidate_digest.py -v   # all pass
./.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -1     # 0 failed; passed == 632 + (tests added)
```

## Git hygiene + report
- Stage ONLY: `tools/verify_candidate_digest.py`, `tests/unit/test_verify_candidate_digest.py`,
  `reports/post_audit_hardening/CANDIDATE_DIGEST_INVENTORY.md`(+`.json`), `reports/post_audit_hardening/LIVE_RUN_RUNBOOK.md`.
  Never stage any `.xodr`, `campaigns/`, `scripts/`, `__pycache__`.
- Commits (two): `feat(preflight): candidate-identity gate + test` and
  `docs(runbook): live-run digest gate + candidate digest inventory`.
- Push; `git rev-parse HEAD == git rev-parse @{u}`.
- Report: baseline vs final pytest lines (verbatim); files changed + commit SHAs; local==remote; digest-inventory
  counts (tracked vs untracked candidates); `ESCALATE_TO_CLAUDE` list. Verdict:
  `PREFLIGHT_READY_GREEN` | `PARTIAL` | `BLOCKED_NEEDS_DECISION`.

## Out of scope (Claude / runtime — do not attempt)
- Running CARLA, the P04 re-collection, flipping the 7 gates (that IS the live run).
- Deciding whether `6bac3570` or `_repaired_v2` (`1f2b5ff0`) is the authoritative candidate (Claude confirmed `6bac3570`).
- Any certifier/gate logic change; reconciling the mirror drift (adjudicated: leave).
