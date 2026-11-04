# GAP Register Addendum 2 — status updates 2026-11-04

This addendum amends (does not edit) `reports/production_readiness/20261103T000000Z_GAP_REGISTER_ADDENDUM/GAP_REGISTER_ADDENDUM.json`. That file is a historical artifact and was not modified by this work.

Branch: `integration/post-pr16-final-20261102`. Worktree HEAD verified at `a6d1039695cf660428d69dcdde4979d0f0477b23` (`git rev-parse --short HEAD` -> `a6d10396`; `git status --porcelain` showed only the 4 pre-existing untracked entries before this work started).

## Summary table

| id | update_kind | old -> new status | one-line reason | SHA(s) |
| --- | --- | --- | --- | --- |
| GAP-075 | status_change | open -> fixed | Reversed `ValidationReport.add()` argument order fixed package-wide (26 sites, then 20 more) and the test-layout follow-up applied; the "may flip gates" residual checked and found not applicable (`get_failures()` is unchanged and is what gates actually read). | `56efb2cb04a02b9efa7f336d09af499c256f04ac`, `7df27c8001a5d5c5f2f0b45e094bb9e5489086e0`, `a6d1039695cf660428d69dcdde4979d0f0477b23` |
| GAP-067 | status_change | fixed -> fixed (residual closed) | The remaining residual (carla-less env still getting the offline stub via a bare `importorskip`) is closed: real-client-only tests now skip via `require_real_carla()` instead of running against stub attributes. | `6885dfc2ad4950f3267d23b9578efc10dc83a500` |
| GAP-070 | evidence_update | open -> open | Root cause confirmed (default-on junction connector snap rotates connectors, breaking the exit join). A Hermite-refit remediation candidate exists and measures well, but is unmerged and gated on a governed regeneration (X8); not fixed yet. | `46708baa6dc69b299dbb04c6c9ee775ea9bd04fe` (root cause); `03aaccd4baf7d3c11a5cb4b3896aa7644204f8ce`, `2cee039f235f2cff7c87fa1fce935154cdcf3cd8` (unmerged candidate, branch `fix/gap070-connector-snap-exit-20261103`) |
| GAP-079 | new | (none) -> open | New finding: ~0.1 m single-line junction connectors with ~180 deg reversed heading relative to their exit road (170-180 deg bucket: 90 at stage 01, 111 from stage 02 onward; stricter inventory selection: 58 at stage 01, 81 at stage 02). Separate from GAP-070; the GAP-070 candidate fix does not change this bucket. | `06a31ed1e015614674a99c31811a651b751e8789` (branch `research/gap070-reversed-stubs-20261104`, not merged) |
| GAP-076 | note | open -> open | No change to the finding; still open, owner operator. | (none) |
| GAP-077 | note | blocked_external -> blocked_external | No change to the finding; added detail (4 headless pilot attempts, all timing out in `wait_for_carla_ready`, 5.9/6.1 GB VRAM, 82-84 C, no TDR). Still open, owner operator. | (none) |
| GAP-078 | note | open -> open | No change to the finding (environment-only, stale editable install); still open, owner operator. | (none, see caveat below) |

### Caveat on GAP-078's cited SHA

The task brief for this addendum cited `30a754cbf5518592f2f77ac0b8bc86704d2b9101` for the GAP-078 note. That commit resolves to a real commit (`git cat-file -e` succeeded, `git show --stat` succeeded) but its own diff is `docs(gap-register): GAP-070 heading measurement` content — unrelated to the import-authority/`PYTHONPATH` finding. It is cited in the JSON only as a repo-state checkpoint/time marker for when the chunked suite was reportedly run, not as the evidentiary source of the import-authority failure. This writer did not independently reproduce that failure (no stale `authority-convergence` finder or non-project `PYTHONPATH` entry was found in this worktree).

## Register state after this addendum (GAP-056..GAP-079, later entry wins)

- total: 24
- fixed: 19
- open: 4 — GAP-070, GAP-076, GAP-078, GAP-079
- blocked_external: 1 — GAP-077

Computed by `E:/wt/_o10/compute_counts.py` reading both `reports/production_readiness/20261103T000000Z_GAP_REGISTER_ADDENDUM/GAP_REGISTER_ADDENDUM.json` and this addendum's JSON; later entry (by id) wins. Output matched the expected figures exactly; see the implementation report for the full script output.
