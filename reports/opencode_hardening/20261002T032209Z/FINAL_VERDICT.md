# FINAL VERDICT: PARTIAL_WITH_EXACT_BLOCKERS

**Branch:** `opencode/p1-runtime-capture-20261001`
**Starting head:** `233e452ff16db3d35ca717d0bf02e4779e86b258`
**Result head:** `6cfec6fd5a9fda1c4d2fcaa6cec4d34222b36293`
**Map:** `auto_map_of_record` · `370abbbb…c8c8` · 149,799,632 bytes · `ingolstadt_local_rebased` — VERIFIED

## What was delivered

Nine findings, A–I, all PASS offline. Four commits.

| | Finding | Outcome |
|---|---|---|
| A | Writer backpressure | Per-sensor frame-id accounting; strict `CAPTURE_FRAME_DROP`; never inferred from file counts |
| B | Writer drain | Timeout is real; `WRITER_DRAIN_PASS`/`TIMEOUT`/`FAILURE` all reachable; output quarantined on timeout |
| C | Frame-id authority | Correspondence from actual `data.frame`; artifacts bound to frame id; 5 negative controls |
| D | TM API | `hybrid_physics_mode` / `hybrid_physics_radius` — real CARLA names, no follow-gap substitution |
| E | TM ownership | Owner-token exclusivity; transactional `close()`; every release path tested |
| F | TM evidence | Claims computed from the actor ledger; empty ledger yields `None`, not `true` |
| G | Walker determinism | Strategy A hashed manifest; CARLA-side randomness labelled and refused |
| H | Walker transaction | Rollback at every step; `controlled=True` only on the committed path |
| I | State contamination | Back-to-back runs; process-global RNG explicitly checked |

**Tests:** targeted 210 passed / 0 failed. Full suite 7091 passed / 4 failed / 10 skipped. `compileall` exit 0.

## The verified regression comparison you approved

Two full runs in two isolated worktrees — detached baseline at `233e452f`, and this branch:

```
baseline  233e452f   7009 passed   4 failed
branch    6cfec6fd   7091 passed   4 failed
new failures: 0        fixed: 0        identical failure sets: yes
```

The 4 failures are pre-existing `tests/contracts/test_no_dead_pipeline_signals.py` cases: `ultimate_pipeline/signals/` is untracked at `233e452f`, so each declared artifact lacks a registered production writer.

One methodological note worth recording: my **first** comparison showed 131 "new" failures and was **invalid** — that run shared the machine with the concurrent agent and pytest temp dirs. Isolating both sides with `-p no:cacheprovider` produced the true 0/0 split. I nearly reported 131 regressions that did not exist.

The isolated comparison did surface one **genuine** regression: my P0-4 reconstruction broke three committed tests in `test_o1_cook_provenance_chain.py`. See B3.

## Exact blockers

**B1 — coordinate authority unrecoverable.** `coordinate_contract.py` / `coordinate_frame_contract.py` were destroyed as uncommitted work. They exist nowhere: not in git history, not in any worktree, not in PyCharm LocalHistory (I scanned all 45 MB), not on disk. Original diff required.

**B2 — placement authority not reconstructed.** Never read before loss.

**B3 — P0-4 is NOT VERIFIED.** My reconstruction set `strict_provenance = bool(expected_xodr_sha256) or has_any_manifest`. That broke three committed tests which document the opposite contract: no-manifest tiles may be staged when the XODR check passes (synthetic-fixture opt-out). I corrected the behaviour rather than deleting the tests, splitting it into the verified half (a pinned `expected_xodr_sha256` is the authority; a mismatch is refused outright) and the unverified half (forcing per-tile enforcement on a no-manifest caller). The code carries `P0-4 status: NOT VERIFIED` and a test asserts that marker stays. **The original diff is needed to close this.**

**B4 — 8+ further files destroyed.** `carla_server`, `carla_readiness`, `session`, `main_pipeline`, `quality_gates`, `registry`, `release_profile`, `stage_10_tile_qa`, `stage_12_domain_gap`, `pipeline_health_summary`. Never read; require your restore.

**B5 — concurrent agent owns the shared checkout.** Another opencode agent is writing `ultimate_pipeline/research/rq1_determinism_authority.py` (12,299 bytes, untracked), `tools/rq1_trial_run.py`, `cache/tile_cache.py`, `cache/osm_index.py`, `geometry/vectorized.py`, `parallel/resource_aware.py`. It has committed nothing. I did not stage, commit, or write anything in that tree.

**B6 — 4 pre-existing contract failures.** Identical at baseline and on this branch. Not caused by, and not fixed by, this batch.

**B7 — no hard shutdown bound.** Python threads cannot be force-killed. `join_writer_threads` honours its timeout and reports honestly, but a job already executing cannot be interrupted. A genuinely bounded strict teardown needs writer execution in a separate process. Documented, **not implemented** — and I am not claiming otherwise.

**B8 — no live CARLA.** All 12 live items remain `BLOCKED_EXTERNAL`.

## Why there is no review head

You asked for one immutable head containing coordinate authority + placement authority + recorder P0 + provenance fix + runtime QA fix + integration work. Four of those six are unavailable to me (B1, B2, B4, and P0-4 is partial per B3), and the fifth's tree is actively being written by another agent (B5). Publishing now would mean either committing someone else's in-flight work under my name or shipping a head that silently omits two of the six required components.

Under your own rule — `UNPUSHED_RESEARCH_CODE => NOT_ADMISSIBLE_FOR_FINAL_CLAIMS` — this branch is **not admissible** until reviewed and published, and even then B1/B2/B4 leave it incomplete.

## Sequence to close

1. Restore from your backup: coordinate authority, placement authority, the 8+ files, the original P0-4 diff
2. Have the concurrent agent commit to its own branch
3. Then: one immutable review head from `233e452f` + restored work + `6cfec6fd`, re-run the classified regression

On your RQ1 items: `rq1_trial_run.py` not emitting the fields the matrix requires (your P0-3) is offline-fixable and unblocks the N=5 campaign; the RQ3 wrong-map-lineage defect (your P0-6) is also offline-fixable and is a real claim-integrity bug. Both need no live server. I would start there once the tree is stable — but not before, since B5 means the tree is not currently stable.

Evidence: `reports/opencode_hardening/20261002T032209Z/`