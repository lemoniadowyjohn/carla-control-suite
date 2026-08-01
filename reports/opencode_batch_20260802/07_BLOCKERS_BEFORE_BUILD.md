# 07_BLOCKERS_BEFORE_BUILD.md

**Generated:** 2026-08-02
**Coordinator:** Prompt 01 — Campaign Coordinator

## Hard blockers (must be handled before dependent builds)

| # | Blocker | Scope | Resolution in batch |
|---|---|---|---|
| B1 | **SYS-001 unresolved**: `ultimate_pipeline.main_pipeline` does not import; 8 internal module references missing; root package only 84/593 files tracked | P03 | Full resolution in P03; everything downstream depends on it |
| B2 | **Root package uncommitted**: ~509 .py files untracked on the integration branch — release tree cannot be certified until tracked | P03 | P03 commits canonical tree (track root package files) |
| B3 | **Audit manifest stale claim** for `07_BLOCKING_ISSUES.md` (regenerated after manifest written) | P02 | Recorded as finding in `manifest_hash_verification.json`; authoritative file untouched; re-verification hash captured |
| B4 | **Blender absent from PATH** | P10 | Runtime checks BLOCKED; validator tooling + FBX round-trip runner implemented with fixtures; no cook claim |
| B5 | **No CARLA server** (port 2000 refused) | P05-P14 | Offline-only claims; CARLA import smoke allowed (wheel present); runtime/perception verdicts BLOCKED |
| B6 | **Dirty main worktree**: 3 modified tracked files (stage_08 copies, run_full_domain_gap.py) | P03 | Reconcile: stage_08 edits are audit evidence fixpack; run_full_domain_gap.py is the working 7,466-line runner — commit as canonical |
| B7 | **CARLA wheel in `.venv`** (sitecustomize bootstrap) — venv-local, not repo | P03-P14 | Allowed for offline import tests; not a release artifact |

## Watch items (not blockers)

- `carla_osm2odr_version` remains UNKNOWN_UNSOURCED (DSV14) — no new claim will be made
- `verify_final_xodr_report.json` untracked in campaign candidate dir — verify provenance before use
- `reports/C01_carla_runtime_audit.*` and `R01_final_integration_gate.md` untracked — consult for evidence, do not extend silently
- Prior hardening worktree `fix/post-audit-hardening-20260801` holds an uncommitted Phase A/B evidence set — superseded by committed Phase A; will be referenced, not duplicated

## Exit criteria for COORDINATOR_READY

- [x] Every Build prompt has a branch/worktree (main worktree, integration branch)
- [x] Every Build prompt has file scope (05_FILE_OWNERSHIP_MATRIX.csv)
- [x] Every Build prompt has base commit (04_MODEL_TASK_LEDGER.md)
- [x] Every Build prompt has prerequisites + tests + handoff contract (06_EXECUTION_ORDER.md)
- [x] Dependency order confirmed
- [ ] All seven coordinator reports written (00-07) — THIS prompt
