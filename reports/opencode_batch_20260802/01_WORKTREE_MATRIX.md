# 01_WORKTREE_MATRIX.md

**Generated:** 2026-08-02
**Coordinator:** Prompt 01 — Campaign Coordinator

| Worktree | Branch | HEAD | Class | Use |
|---|---|---|---|---|
| `carla_-main` (main) | `integration/governed-map-quality-20260729` | e9ff5986 | **BUILD** | Canonical production integration point; Phase A committed here; carries uncommitted root package work |
| `carla_-main/work/post-audit-hardening-20260801` | `fix/post-audit-production-hardening-20260801` | b07e2db7 | **reference/reuse** | Prior hardening session artifacts (Phase A/B reports at 20260801T231300Z, phase_b_implement.py); consult, do not duplicate |
| `carla_-main/worktrees/post-audit-hardening-20260730` | `fix/post-audit-hardening-20260730` | dac6930a | **reference-only** | Earlier hardening attempt; unmerged |
| `carla_main_audit` | `audit/gemini31pro-audit` | d202ad22 | **reference-only** | Gemini 3.1 Pro full audit branch |
| `carla_main_governed` | `fix/deepseek-observability-integration-verification` | deb261bf | **reference-only** | Governance/observability work |
| `carla_main_governed/work/claude-grid0828-review` | detached | b1b6e010 | retain | Review evidence |
| `carla_main_governed/work/codex-full-pipeline-rerun-20260427` | `work/codex-full-pipeline-rerun-20260427` | 6b250621 | retain | Pipeline rerun evidence |
| `carla_main_governed/work/codex-grid0828-patch` | `work/codex-grid0828-batch-sync-001` | fe7daad8 | retain | Patch evidence |
| `carla_main_governed/work/gemini-governance-normalize` | `work/gemini-governance-normalize-20260315` | 68ab0caf | retain | Governance normalize evidence |
| `carla_main_governed/work/gemini-grid0828-runtime` | detached | 21e8e23a | retain | Runtime probe evidence |
| `carla_main_governed_worktrees/codex-jsnap-20260428` | `work/codex-jsnap-20260428` | 2b1a3d11 | retain | jsnap evidence |
| `carla_rr_recovery` | `recovery/roadrunner-capability-integration` | 25917b18 | reference-only | RoadRunner capability recovery |

## Classification rules applied

- **reuse**: contains artifacts usable by this batch (prior hardening reports)
- **reference-only**: consult for provenance/evidence, never build on
- **retain**: historical evidence, do not remove
- **blocked/later-archive**: none require archiving in this batch

## Policy notes

- No worktree is removed or force-reset. No `git push --force`, no `git clean -fd/x`, no destructive restore.
- All new builds land on `integration/governed-map-quality-20260729` with atomic commits, or on task worktrees if risk isolation is required (none chosen this batch: fixes are additive/validators).
