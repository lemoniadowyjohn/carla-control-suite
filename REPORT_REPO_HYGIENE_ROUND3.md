# Repo Hygiene Round 3 - 2026-09-17

## Branch Cleanup

Deleted 4 remote branches fully merged into `integration/session-batch1-20260912`
that were clearly superseded/dead:

- `integration/session-batch1-20260912-final-20260916` -- "final" suffix, superseded by main branch
- `integration/session-batch1-20260912-integrate` -- integration helper, superseded
- `review/claude-independent-audit-20260906` -- old review pass, superseded
- `stabilize/research-release-20260905` -- old research release, superseded

**Left intact** (not confident they are safe to delete):
- 80 merged feature/fix/test branches with descriptive names that may still
  be referenced for provenance or contain important commit history.
- `ci-verify-throwaway`, `codex-clean`, `chore/production-engineering-shell-v2-20260915`
  (not merged, possibly still in use).

## Reports Clutter

- `reports/production_readiness/*_TILE_BASED_FBX_GENERATION_PROBE/`
  (8 timestamped directories): **Untracked** local noise, not in git.
  No commit or archival action needed.
- `reports/production_readiness/20260915T180446Z_FULL_GRID_TILE_FBX_COOK/`,
  `20260915T203000Z_COMPREHENSIVE_GAP_AUDIT/`,
  `20260915T203000Z_GEOMETRY_CRS_DEM_HARDENING/`: Also **untracked**.
- Tracked reports (`20260915T220000Z_GRID_RCA_V3/`,
  `20260915T220000Z_UE4_PRODUCTION_AUDIT_V3/`): Important audit artifacts,
  not redundant; left in place.
- `docs/archive/`: Does not exist. `docs/deprecated/` is the archival
  convention but no tracked reports needed archiving.

## Test Suite

Full `pytest tests/unit/` passes: **50 passed, 1 skipped** (pinned source
file absent). No new failures introduced.

## Notes

- Root-level untracked files (`.agent_locks/`, `.claude/`, `.codex/`,
  `.github/`, `audit_output/`, `campaigns/`, `carla_governed/`, etc.)
  are pre-existing local noise; not touched.
- Pre-existing deleted tracked files (`.env`, various pipeline scripts)
  are not part of this hygiene scope.
