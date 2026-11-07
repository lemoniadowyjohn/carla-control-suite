# CARLA V24.1 Final Gate Recovery — Agent Launch Page (2026-11-07)

**Pack:** [00_START_HERE.md](CARLA_V24_1_FINAL_GATE_RECOVERY_20261107_v2/00_START_HERE.md)  
**Repository:** `lemoniadowyjohn/carla-control-suite`  
**Local candidate:** `8fcd8c79` (abbreviated, **not independently resolved in GitHub**).  
**W-B local commit:** `f07efe9765232615b5ebc42ade94b3459bc3d52a`, tree `2078f556ff51832f7c86005b12e9b50acdcd51d0` (**operator-reported local verification**).  
**Separate GitHub baseline:** [draft PR #25](https://github.com/lemoniadowyjohn/carla-control-suite/pull/25), reference SHA `dfa6ffff07c38d0cc09507c52b3328900ef2d900` (not necessarily same as local V24.1 candidate).

## Start OpenCode (independent verifier)
Read [05_OPENCODE_INDEPENDENT_GATE_VERIFIER.md](CARLA_V24_1_FINAL_GATE_RECOVERY_20261107_v2/05_OPENCODE_INDEPENDENT_GATE_VERIFIER.md), [00_START_HERE.md](CARLA_V24_1_FINAL_GATE_RECOVERY_20261107_v2/00_START_HERE.md), [09_INITIAL_GATE_MATRIX.csv](CARLA_V24_1_FINAL_GATE_RECOVERY_20261107_v2/09_INITIAL_GATE_MATRIX.csv), the [receipt schema](CARLA_V24_1_FINAL_GATE_RECOVERY_20261107_v2/08_EVIDENCE_RECEIPT_TEMPLATE.json), and [V27 ownership contract](CARLA_V26_V27_INDEPENDENT_ASSURANCE_20261107/contracts/OWNERSHIP_AND_GATES.md). Verify the 17 existing W-B manifest entries, exact tree/test selection and 100-pass receipt, but do not claim independent approval for the stopped DeepSeek scan. Classify W-B review status PENDING until a different-provider-family reviewer returns an exact-commit verdict. Verify W-F and W-D evidence separately. Create only OpenCode-owned tests/new evidence, never production edits. Report BLOCKED/NOT_EXECUTED precisely.

## Start Codex (integration coordinator, no unconditional source edits)
Read [01_CODEX_INTEGRATION_COORDINATOR.md](CARLA_V24_1_FINAL_GATE_RECOVERY_20261107_v2/01_CODEX_INTEGRATION_COORDINATOR.md), [06_CODEX_DISK_CI_PACKAGING.md](CARLA_V24_1_FINAL_GATE_RECOVERY_20261107_v2/06_CODEX_DISK_CI_PACKAGING.md) and [00_START_HERE.md](CARLA_V24_1_FINAL_GATE_RECOVERY_20261107_v2/00_START_HERE.md). Dispatch independent W-B review [02](CARLA_V24_1_FINAL_GATE_RECOVERY_20261107_v2/02_CLAUDE_WB_DIFFERENT_FAMILY_REVIEW.md), W-F review [03](CARLA_V24_1_FINAL_GATE_RECOVERY_20261107_v2/03_CLAUDE_WF_GEOMETRY_REVIEW.md) and W-D owner recovery [04](CARLA_V24_1_FINAL_GATE_RECOVERY_20261107_v2/04_WD_OWNER_ACCEPTANCE_RECOVERY.md) as separate, non-overlapping responsibilities. Check C:/D: headroom; **do not run heavy suites**, delete evidence or change shared Git metadata without safe resources and exclusive writer ownership. Then, only with verified prerequisites/authorizations, prepare an exact combined candidate and CI plan. Final independent reviewer [07](CARLA_V24_1_FINAL_GATE_RECOVERY_20261107_v2/07_CLAUDE_FINAL_CANDIDATE_REVIEW.md) is required before a release decision.

## Nonnegotiable boundaries
- This is a *documentation/evidence dispatch* publication. Publishing this branch is **not** publication of candidate b and is not AUTH-08 authorization.
- No source implementation is changed here. Never reset/clean the reportedly dirty main checkout, force-push, merge protected branches, patch final XODR cosmetically, relax GAP-026 geometry tolerances, run live CARLA/UE or train models without grants.
- All receipts must bind exact source+tree SHA, test node IDs, commands, exit code, platform, timestamps, logs, hashes, reviewer/provider family and verdict. A partial/incomplete reviewer response is not approval.
- W-B prior test result: operator reported `100 passed, 0 failed, 6 warnings` in 28.05 seconds on clean W-B worktree; five optional settings path warnings plus one `torch_geometric.distributed` deprecation warning. This remains **local evidence** until independently inspected.

## Verify this publication
From the pack folder, run `python verify_pack.py`; its manifest covers 11 files and excludes `SHA256SUMS.txt`. Pack integrity is not executable CARLA or scientific proof. All 12 pack blobs were matched by Git SHA-1 to the checked ZIP contents at publication.

**Required final status until gates close:** `PARTIAL_WITH_EXACT_BLOCKERS`.
