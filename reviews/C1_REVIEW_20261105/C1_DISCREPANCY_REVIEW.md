# C1 — comparison of the two completion reports (read-only, 2026-11-05)

**Reviewer:** Claude (Opus 5.5). This is a coordination check, **not** the independent code review:
Claude wrote the C1 specification, so a different model family must still review the patch.
Nothing was modified.

**State examined:** worktree `E:/wt/fix-gap070-connector-snap-safety-c1-20261104`, branch
`fix/gap070-snap-default-off-20261105`, HEAD `0b7b0c90c166371ff6dadb68c937e2a139f61935` (parent
`1a36b560`), plus the uncommitted `tests/unit/test_c1_lane_border_fixtures.py` (sha256 prefix
`61537aa06b2a6bd5`). Evidence package: `G:/audit/C1_CLOSEOUT_20261105/`; its `SHA256SUMS` verifies.

## Confirmed
| Claim | Check | Result |
|---|---|---|
| No Hermite code in C1 | `git diff 1a36b560 0b7b0c90 -- ultimate_pipeline/tools/junction_connector_snap.py` is empty; `_replace_with_hermite` is absent | **confirmed** |
| Default OFF; blocked under release / strict / THESIS_STRICT; UNQUALIFIED_EXPERIMENTAL opt-in | tests at `test_stage05_connector_snap_wiring.py:33-111` | **confirmed** (19 passed on Claude's re-run of wiring + fixtures) |
| Threshold contract unchanged | `wiring:189-191` asserts 30.0 and `max_gap_m == 2.0` | **confirmed** |
| Real-file byte preservation, lane-border and U-turn | `wiring:178-186` (committed) | present; see D4 for what it proves |
| The snap report is not a terminal PASS signal | no reference in `ultimate_pipeline/signals`, `quality`, `core` or `tools` at `0b7b0c90` | **confirmed** |

## Discrepancies
| # | Severity | Discrepancy | Required action |
|---|---|---|---|
| D1 | P1 | **The test counts disagree and can't be reproduced.** Report 1 says 39 passed (4 named files); report 2 says 175 passed, with the command `"pytest C1 fixtures+wiring+snap+classifier+contracts"`, which is not an executable command (shared contract §8). | Record the exact file list and command for the 175, with exit code; until then the 175 is UNVERIFIED. |
| D2 | P1 | **The B-test IDs are reused with different meanings** from the ARCH-002 matrix. ARCH-002 defines B1 = a lane-border connector is not moved, B2 = a connector off every border is still reported, B3 = a U-turn is not moved, B11 = no tolerance raised, B12 = default asserted. Codex's B1/B2/B3/B11/B12 are other checks, which breaks traceability. | Rename to C1-local ids, or map them: ARCH B1 → `wiring:178` (lane_border), B3 → `wiring:178` (uturn), B11 → `wiring:189`, B12 → `wiring:33`; **B2 is not covered** (by design NOT_MEASURED, owned by O13). |
| D3 | P1 | **The uncommitted fixture tests don't exercise product code.** B1 and B2 assert the test's own helper functions against constants; B3, B11 and B12 assert attributes of the fixture the test itself built (tautological). Only `test_default_stage_policy…` calls the product, and it duplicates committed `wiring:178`. The claims "independently calculated oracles" and "wrong border placement is detected" overstate it: no product detector is tested. | Drop the file, or rewrite it against product behaviour (see D4). Do not count it as verification. |
| D4 | P1 | **The byte-preservation tests pass trivially:** with the snap DISABLED, `_run_junction_connector_snap` returns before loading the file, so they prove the default policy, not lane-border correctness. The meaningful, cheap fixture test is missing: with an explicit experimental opt-in, the historical snap must **move** the lane-border connector by 3.25 m (the negative control that reproduces the GAP-070 mechanism at fixture scale). Both reports list the "fixture three-arm comparison" as not done. | Add it: an experimental profile with opt-in on the `wiring:166` fixture; assert the connector start moves from y = −3.25 to y = 0, and that the report says UNQUALIFIED_EXPERIMENTAL. |
| D5 | P2 | No failing-first evidence (the commit body admits it). | Run the new tests against baseline copies of the two product files from `1a36b560` (default ON, no gate) and paste the failures. |
| D6 | P2 | Inconsistent status: report 1 says `TESTED_LOCAL / NEEDS_MORE_PROOF`, report 2 says `READY_FOR_INDEPENDENT_CODE_REVIEW` for the same tree. The fixture file is outside every commit, so a review of `0b7b0c90` alone excludes it. | Status per contract §10: `TESTED_LOCAL`. Commit or drop the fixture file before the independent review, so the review target is one SHA. |
| D7 | P3 | The temp dir `G:/tmp/c1-gap070` (27 KB) is left behind. | Record it, or remove it. |

## Verdict
C1's **policy change is sound and confirmed**:
- default OFF, gated, labelled;
- no Hermite code;
- thresholds unchanged;
- the report is not promotable to PASS.

The **test evidence is weaker than both reports state**: D3 and D4 above, and an unreproducible count (D1).

**Status: `TESTED_LOCAL`.** Not ready for the independent code review until D1, D3/D4 and D6 are
resolved, which is about one small test plus a receipt. GAP-070 and GAP-080 remain open. O13 is
still required for any lane-level claim.

## Integration owner's "full candidate-bound CI suite"
`.github/workflows/tests.yml` runs on push or PR events. The C1 branch is **not on GitHub**, so CI on
`0b7b0c90` requires either pushing the branch or opening a PR. Both need explicit operator
authorization. A local full suite is possible, but disk is tight (E: about 0.6 GB): it must run on G:
with `--basetemp` there.
