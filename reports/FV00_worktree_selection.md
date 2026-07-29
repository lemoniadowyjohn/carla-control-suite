# FV00 Worktree Selection

Generated UTC: 2026-07-29T21:03:53.120531+00:00

## Selection

AUTHORITATIVE WORKTREE: C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main
BRANCH: verification/map-quality-hardening-20260729
BASE SHA: ff00099dae404f49a83d7dd909a3c35259040ebb
REMOTE SHA: 0578e45bfe79452879372a9ab095e660e8a94e63
ROLLBACK REF: backup/fv-baseline-20260729-ff00099 (ff00099dae404f49a83d7dd909a3c35259040ebb)

## Selection Reason

- Only discovered worktree with committed root opendrive_geometry model/primitives/evaluator package.
- Contains committed Line/Arc test scaffold and canonical geometry integration history.
- Contains newer governed-map-quality integration branch with RoadRunner and junction-snap commits plus cross-comparison hardening.
- carla_main_governed is heavily dirty and lacks the root canonical geometry package.

## High-Risk Findings

- Selected worktree has active-looking untracked subsystem modules and tests; these must be reviewed and committed or rejected before ready status.
- Selected worktree is one commit ahead of origin/integration/governed-map-quality-20260729.
- Several stashes contain relevant pipeline/quality files, but no root canonical opendrive_geometry package was found in stash filenames.

## Worktree Matrix

| path | branch | head | class | dirty | staged | unstaged | untracked | active untracked modules |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main | verification/map-quality-hardening-20260729 | ff00099dae40 | AUTHORITATIVE_CANDIDATE | 15 | 0 | 0 | 15 | tests/carla_tools/, tests/domain_gap/, tests/topology/, ultimate_pipeline/artifacts/, ultimate_pipeline/carla_tools/, ultimate_pipeline/domain_gap/, ultimate_pipeline/topology/ |
| C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_main_audit | audit/gemini31pro-audit | d202ad2227f2 | REPORT_ONLY | 0 | 0 | 0 | 0 |  |
| C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_main_governed | fix/deepseek-observability-integration-verification | f0024b5eb258 | PARTIAL_IMPLEMENTATION_DIRTY | 142 | 11 | 9 | 124 |  |
| C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_main_governed\work\claude-grid0828-review | (detached) | b1b6e010cbd4 | PARTIAL_IMPLEMENTATION_DIRTY | 4 | 0 | 2 | 2 |  |
| C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_main_governed\work\codex-full-pipeline-rerun-20260427 | work/codex-full-pipeline-rerun-20260427 | 6b2506210a23 | PARTIAL_IMPLEMENTATION_DIRTY | 5 | 0 | 2 | 3 |  |
| C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_main_governed\work\codex-grid0828-patch | work/codex-grid0828-batch-sync-001 | fe7daad8f222 | PARTIAL_IMPLEMENTATION_DIRTY | 4 | 0 | 2 | 2 |  |
| C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_main_governed\work\gemini-governance-normalize | work/gemini-governance-normalize-20260315 | 68ab0caf8659 | PARTIAL_IMPLEMENTATION_DIRTY | 4 | 0 | 2 | 2 |  |
| C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_main_governed\work\gemini-grid0828-runtime | (detached) | 21e8e23a016c | PARTIAL_IMPLEMENTATION_DIRTY | 4 | 0 | 2 | 2 |  |
| C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_main_governed_worktrees\codex-jsnap-20260428 | work/codex-jsnap-20260428 | 2b1a3d11cdda | UNKNOWN | 0 | 0 | 0 | 0 |  |
| C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_rr_recovery | recovery/roadrunner-capability-integration | 25917b1878fa | PARTIAL_IMPLEMENTATION | 10 | 0 | 1 | 9 |  |

## Donor Imports

- C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_main_governed_worktrees/codex-jsnap-20260428 commit 2b1a3d11cdda2c019f52fac86fdd194e74852b4e imported as 0578e45bfe79452879372a9ab095e660e8a94e63: junction connector snap tool only; large BEST artifact not imported
- C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_rr_recovery commit 25917b1878fab530d86b2c6164d6e37148c5c427 imported as 8bf23117, b4b169ef, 24bac0d6: RoadRunner capability contracts, semantic comparison, mesh manifest/alignment

## Required Next Gate

Do not claim ready status until untracked subsystem modules/tests are either committed after review or explicitly rejected and removed from the active test/import path.
