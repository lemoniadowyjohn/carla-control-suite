# V132 candidate — independent review handoff

## Candidate

- Branch: `integration/v132-pre-claude-source-candidate-20261119`
- Production base: `225ed15d0da6444cc257835ca777aba281553f3c` (fresh fetch confirmed this SHA)
- Release tranche merge commit: `49d037696a21cba1ca5763d4dd25de86cc47c4b4`
- Imported stack tip: `7b655fb8db9f92682f41ad1e08404bd7c5ff657d`
- Merge parents: production SHA and the imported T3 stack tip.

## What is in the candidate

PR #63 → PR #70 plus T3's corrected test fixtures/doubles, merged with ancestry retained. Source changes include trusted map scope, immutable candidate/digest checks, XML admission and release acceptance authority. The merge was conflict-free. Focused suites passed: 112 acceptance tests and 113 adjacent XML/release tests; all were run on Windows with Python 3.12.2 and `PYTHONPATH` cleared.

## Exclusions and review questions

- **T1 calibration / PR #65, #66, #68, #69:** excluded. Candidate `00f059fbc067aace82212e2b768f016b0bd0d71b` has a reproduced failure in `test_matching_camera_response_identity_validates_the_pair` (141 passed, 1 failed); do not relax complete sensor-set validation. The live rig and saved-frame-size readback remain unverified.
- **T2 submission mirrors:** excluded. The exact dirty T2 worktree/ref was not located. The available policy describes submission infrastructure as an archived migration donor, while a submission-only test requires importing `APPLIED_SENSOR_RIG/v2`; policy and source handoff need resolution.
- CRS, OSM, RQ5, fuzzer/feature gap, lifecycle, leases, GUI and remaining PRs were not integrated in this tranche. Use `F:\CARLA_RECOVERY\handoff\OPENCODE_V132\v132_pr_inventory.json` and `BLOCKERS_FOR_CLAUDE.md` for the current local source inventory; neither substitutes for refreshed live review-thread/CI data.
- PR #30 inline threads remain unresolved; no thread was auto-resolved.

## Verification limits

Full offline CI, exact-head GitHub checks, independent Claude review, live CARLA runtime, paired RQ3 capture, and RQ5 training/evaluation were not run. The GitHub branch-head query succeeded for production and the T3 handoff, but later remote queries were intermittent. Focused test output was not saved to a hashed log, so this handoff claims counts only.

## Required next actions

1. Recover the T2 worktree and its exact dirty diff or obtain an explicit mirror-policy disposition.
2. Repair T1's stale shared synthetic fixture under an exclusive owner, preserving the full-sensor negative controls; rerun its suite including PR #65 saved-frame-size tests.
3. Obtain exact-head GitHub CI and independent review after each integration tranche.
4. Reconcile the CRS, OSM, RQ5, lifecycle, lease and remaining PR ancestry/overlap before importing them.
5. Keep production merge blocked until offline gates, independent review, applicable runtime evidence, research admission and explicit authorization pass.
