# GitHub Publication Report — Ingolstadt Map Quality v2

## Publication Verdict

**GITHUB_PUBLICATION_PARTIAL_LARGE_ARTIFACTS_REFERENCED**

This publication is complete. The WP2B V1 rejected candidate XODR binary is intentionally not committed to the repository (referenced by hash only). Four WP1 candidate XODR files exceed GitHub's 50 MB soft recommendation — they were committed in earlier P15 commits as regular Git content; this cannot be changed without history rewriting (forbidden by safety constraints).

## Repository

| Field | Value |
|-------|-------|
| Repository | `lemoniadowyjohn/carla-control-suite` |
| Clone URL | `https://github.com/lemoniadowyjohn/carla-control-suite.git` |

## Branch Information

| Field | Value |
|-------|-------|
| Branch | `improvement/ingolstadt-map-quality-v2-202608` |
| Base branch | `integration/governed-map-quality-20260729` |
| Baseline commit | `877e9aef41f733a3ecf980a4559ec6bd359037bf` |
| Final local commit | `35d98ee7ffc71380eed1450bd0b2b9e4ff00ce6f` |
| Remote branch SHA | `35d98ee7ffc71380eed1450bd0b2b9e4ff00ce6f` |

## Commit List

| Commit | Message | Files |
|--------|---------|-------|
| `bfde9494` | P15: Phase 1B/1C coordinate correction and verification | 7 |
| `3e0e5f42` | P15: Phase 2A connectivity diagnostics | 1 |
| `7ddba388` | P15: add coordinate inventory and Phase 1A diagnosis to repo | 2 |
| `f2ec7975` | P15: Phase 1A coordinate inventory and diagnosis | 1 |
| `6f714c5a` | P15: commit baseline authority for ingolstadt-map-quality-v2 | 7 |
| `661a1f03` | campaign: publish baseline authority and campaign metadata | 5 |
| `fa008081` | coordinates: publish verified reprojection implementation and evidence | 1 |
| `488fbecd` | connectivity: publish diagnostics and rejected repair attempt | 52 |
| `35d98ee7` | verification: publish WP2C rejection evidence and review entrypoint | 5 |

New commits created for this publication: 4 (commits `661a1f03` through `35d98ee7`).

## Pull Request

| Field | Value |
|-------|-------|
| PR number | 1 |
| PR URL | https://github.com/lemoniadowyjohn/carla-control-suite/pull/1 |
| Draft | Yes |
| Title | Ingolstadt map quality v2: verified coordinate correction and rejected connectivity repair evidence |

## Files Committed

Total files changed (new commits, `6f714c5a..HEAD`): **71 new files, 2 modified, 2 XODR via LFS**

### By category:

- **Campaign authority (WP0)**: 7 files (existing + updated manifest)
- **WP1 coordinate evidence**: 5 files (coordinate inventory, diagnosis, 4 XODR candidates, tests JSON)
- **WP1 verification tests**: 1 file (`test_ingolstadt_coordinate_verification.py`)
- **WP2A/WP2B/WP2C evidence**: 52 files (connectivity diagnostics, repair scripts, verification reports, rejected attempt evidence)
- **Publication summaries**: 6 files (review entrypoint, inventory, changed file index, hash registry, reproduction commands, limitations)
- **Configuration**: 1 modified (`.gitattributes` LFS rule update)

## Git LFS Files

| File | SHA-256 | Size |
|------|---------|------|
| `work_package_02_connectivity/candidate_connectivity_repaired.xodr` | `c3dc29d3...` | 89,206,190 bytes |

Note: 4 WP1 XODR candidate files were committed in earlier P15 commits as regular Git content (not LFS). Changing this would require history rewriting, which is prohibited.

## Manifest-Only Artifacts

Artifacts referenced by hash in `EXTERNAL_ARTIFACT_MANIFEST.json` but not committed to the repository:

| Logical Path | SHA-256 | Reason |
|-------------|---------|--------|
| `evidence/BASELINE_CANDIDATE_PINNED.xodr` | `c8419f8c...` | Large binary, external workspace |
| `evidence/HISTORICAL_RUN11_ARTIFACT.xodr` | `c765c4da...` | Large binary, external workspace |
| `evidence/MANUAL_GRID0828.xodr` | `a42ddfea...` | External reference |
| `evidence/MANUAL_GRID0821.xodr` | `69ee3498...` | External reference |
| `metric_locks/METRIC_DEFINITION_LOCK.json` | `10ff52f6...` | External workspace (carla_full_replay) |
| `threshold_locks/THRESHOLD_CHANGE_REPORT.md` | `6766166c...` | External workspace (carla_full_replay) |
| `baseline_record/BASELINE_CANDIDATE.json` | `4b8a28ae...` | External workspace |
| `MASTER_PROMPT.md` | `7321fb0d...` | External workspace |

The rejected V1 candidate (`candidate_connectivity_repaired.xodr`, SHA `c3dc29d3...`) is available in the external workspace and is **not** committed as a promoted artifact.

## Excluded Files

| File/Directory | Reason |
|---------------|--------|
| `work_package_02_connectivity/v2/` | V2 repair work not part of this publication |
| `rejected_attempt_v1/candidate_connectivity_repaired.xodr` | Rejected candidate, not promoted |
| `external/` | Third-party tools, unrelated |
| `.idea/`, `.githooks/` | IDE/editor caches |
| `audit_output/`, `audit_output.zip` | Audit output, unrelated |
| `carla_governed/`, `work/`, `worktrees/` | Worktree artifacts, ignored |
| `__pycache__/`, `*.pyc` | Python caches, gitignored |

## Test Results

| Test Suite | Command | Passed | Failed | Skipped | Warnings | Exit Code |
|-----------|---------|--------|--------|---------|----------|-----------|
| Coordinate verification | `pytest tests/quality/test_ingolstadt_coordinate_verification.py -v` | 13 | 0 | 0 | 0 | 0 |
| Geometric continuity | `pytest tests/unit/test_geometric_continuity_migration.py -v` | 24 | 0 | 0 | 3 | 0 |
| Topology validation | `pytest tests/topology/test_junction_model.py -v` | 11 | 0 | 0 | 0 | 0 |

## Secret Scan Results

| Scan Type | Patterns Searched | Result |
|-----------|-------------------|--------|
| Repository grep | `ghp_`, `github_pat_`, `sk-`, `BEGIN PRIVATE KEY`, `cloudflared token`, `Bearer`, `password=`, `secret=`, `api_key=` | No secrets found |

## Working Tree State

After the final commit, the working tree contains untracked files outside the publication scope (`.idea/`, `external/`, `audit_output/`, etc.). All publication-related files are committed. The `.gitattributes` modification is committed.

## Environment

| Component | Version |
|-----------|---------|
| Python | 3.12.2 |
| Git | 2.46.2.windows.1 |
| Git LFS | 3.5.1 (GitHub; windows amd64; go 1.21.7) |
| Platform | win32 |
