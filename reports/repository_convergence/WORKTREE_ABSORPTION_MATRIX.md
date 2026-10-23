# Worktree / Branch Absorption Matrix

**Repository:** `lemoniadowyjohn/carla-control-suite`
**Audit mode:** READ-ONLY (no edits, commits, merges, rebases, deletions, worktree removals, heavy tests, CARLA/UE runs, map regeneration)
**Generated:** see `metadata.generated_utc` in the JSON companion

> `safe_removal_candidate=true` **does NOT authorize deletion.** It means only: "no unique content was found by the checks performed."

---

## 0. Two findings that change how this report must be read

### 0.1 The requested primary baseline does not exist as a local branch

The audit named `fix/topology-convergence-gap026-gap048-20261011` as the primary comparison target.

```
$ git rev-parse --verify fix/topology-convergence-gap026-gap048-20261011
fatal: Needed a single revision
```

There is **no local branch** with that name. It exists only as a remote-tracking ref:

| ref | SHA |
|---|---|
| `origin/fix/topology-convergence-gap026-gap048-20261011` | `3a6f32255916b9783e41981ba284d68401294a92` |

`git fetch --all --prune` completed with no output (no remote drift, nothing pruned, no stale refs removed).

All comparisons in this report use `origin/fix/topology-convergence-gap026-gap048-20261011` = `3a6f3225`. **The second primary target, `integration/consolidate-fixes-20261008` (`75371cd9`), is a strict ancestor of the baseline** (0 ahead / 8 behind), i.e. it is already fully absorbed by the convergence branch and cannot serve as an independent comparator.

### 0.2 The repository was being actively modified during the audit

The working tree changed underneath the audit between measurements:

| observation | first | later |
|---|---|---|
| untracked files in `carla_-main` | 276 | 278 / 279 |
| registered worktrees | 31 | 32 |
| HEAD of `carla_-main` | `8015df6a` `integration/tooling-cherry-pick-20261009` | `73cbcb3e` `fix/gap049-poller-delta-only-20261011` |

Reflog for the audit window:

```
73cbcb3e HEAD@{2026-10-11 22:47:20}: commit: fix(cook-diagnostics): poller must emit deltas only, not the whole tree each cycle
9fa11e1e HEAD@{2026-10-11 22:45:57}: checkout: moving from fix/poller-delta-only-20261011 to fix/gap049-poller-delta-only-20261011
8015df6a HEAD@{2026-10-11 22:43:32}: checkout: moving from integration/tooling-cherry-pick-20261009 to fix/poller-delta-only-20261011
```

A concurrent agent/session is writing to this repository **while the audit runs**. Consequences:

- Every number here is a **time-of-observation snapshot**, not a stable state.
- New branches (`fix/gap049-poller-delta-only-20261011`, `fix/gap049-package-write-poller-delta-only-20261011`, worktree `wt-gap049-fix`) appeared mid-audit and were not in the original inventory.
- **No removal decision should be executed against this snapshot.** Re-run against a quiesced repository before acting.

---

## 1. Counts

```
WORKTREES_TOTAL                    = 32
WORKTREES_WITH_UNIQUE_VALUE        =  1   (carla_-main — uncommitted evidence)
WORKTREES_FULLY_ABSORBED (clean)   =  3
WORKTREES_ABSORBED_BUT_DIRTY       =  9   (commits absorbed; uncommitted bytes are NOT)
WORKTREES_DIRTY_UNKNOWN            = 19
WORKTREES_MISSING_ON_DISK          =  0

BRANCHES_TOTAL                     = 514
BRANCHES_ABSORBED_BY_ANCESTRY       = 248
BRANCHES_NOT_ABSORBED              = 266
BRANCHES_REMOTE-PRESERVED          = 192
BRANCHES_WITH_REMOTE (non-absorbed subset) = 109
```

---

## 2. Worktree matrix

`dirty` = modified/deleted tracked files. `untracked` = untracked files. `uniq_files` = files present in the worktree HEAD tree but absent from the baseline tree.

| worktree | branch | head | dirty | untracked | uniq_files | remote | classification | safe_removal | reason |
|---|---|---|---|---|---|---|---|---|---|
| carla_-main | (detached / moving) | 8015df6a | 1 | 278 | 0 | n/a | **UNIQUE_LIVE_VALUE** | **false** | ~279 untracked files exist in **zero commits** anywhere. Not removable under any circumstances. |
| wt-topology-convergence | (detached) | 3a6f3225 | 0 | 0 | 0 | n/a | EXACT_SHA_ABSORBED | true | HEAD **is** the baseline. Zero unique content. |
| wt-consolidate-20261008 | integration/consolidate-fixes-20261008 | 75371cd9 | 0 | 0 | 0 | yes | EXACT_SHA_ABSORBED | true | Strict ancestor of baseline. |
| lane_A1_rq1a-execution | (detached) | 7fbd33ff | 0 | 0 | 0 | n/a | EXACT_SHA_ABSORBED | true | Ancestor; clean. |
| wt-topo-conv | (detached) | 3a6f3225 | 0 | 1 | 0 | n/a | ABSORBED_BUT_DIRTY | false | 1 untracked file not in any commit. |
| wt-gap026-audit | (detached) | 9fa11e1e | 0 | 7 | 0 | n/a | ABSORBED_BUT_DIRTY | false | 7 untracked files uncommitted. |
| wt-rq2-final | (detached) | 65eb0f14 | 0 | 4 | 3 | n/a | ABSORBED_BUT_DIRTY | false | 4 untracked files. |
| session-batch1-full-verify-20260913 | integration/production-large-map-20260918 | 65eb0f14 | 0 | 1 | 3 | yes | ABSORBED_BUT_DIRTY | false | 1 untracked file. |
| rq5-isolation-20261009 | fix/rq5-test-isolation-leak-20261009 | 68868f76 | 0 | 2 | 0 | yes | ABSORBED_BUT_DIRTY | false | 2 untracked files. |
| wt-runtime-rig | integration/opencode-runtime-rig-environment-closure-20261001 | 692b4239 | 33 | 0 | 2 | no | ABSORBED_BUT_DIRTY | false | **33 modified tracked files** — substantial uncommitted work. |
| new316-333-perception-hardening | fix/new316-333-perception-environment-20261001 | 278968f9 | 34 | 0 | 3 | no | ABSORBED_BUT_DIRTY | false | **34 modified tracked files.** |
| rq1-matrix-fix | fix/rq1-matrix-integrity-20261001 | d12a0314 | 23 | 0 | 3 | no | ABSORBED_BUT_DIRTY | false | **23 modified tracked files.** |
| wt-p1-base | (detached) | 233e452f | 18 | 0 | 2 | n/a | ABSORBED_BUT_DIRTY | false | **18 modified tracked files.** |
| wt-gap055-fix | fix/gap055-ci-windll-platform-guard-20261009 | bec68678 | 0 | 0 | 0 | no | ABSORBED (see §3.1) | false | Commits are patch-divergent from baseline but **file content identical**; worktree dir is stale/prunable. |
| wt-gap026-fix | fix/gap026-junction-lanelink-generator-20261011 | 0f3c3601 | 0 | 0 | 0 | no | PATCH_EQUIVALENT_ABSORBED (see §3.2) | false | Content absorbed; branch ref still exists and diverges. |
| wt-gap048 / wt-gap048-m3 | fix/gap048-through-junction-20261009 / detached | ef3003c2 | 0 | 16 | 0 | no | PATCH_EQUIVALENT_ABSORBED | false | Content absorbed; m3 has 16 untracked files. `wt-gap048` is **prunable** (gitdir points to non-existent location). |
| wt-gap049-fix | fix/gap049-package-write-poller-delta-only-20261011 | 73cbcb3e | 2 | 0 | 1 | no | UNIQUE_LIVE_VALUE | **false** | Newest work; 1 file (`test_package_write_poller_delta_only.py`) exists nowhere else. Created mid-audit. |
| rq5-sightb-20261009 | (detached) | cfc0cd9c | 0 | 100 | 7 | n/a | UNKNOWN_REVIEW_REQUIRED | false | 15 patch-unique commits, 100 untracked files. |
| wt-rq2-merge-verify-20261009 | integration/rq2-authority-merge-20261009 | af90dd91 | 0 | 0 | 9 | no | UNKNOWN_REVIEW_REQUIRED | false | 2 patch-unique commits, 9 unique files. |
| wt-p1 | opencode/p1-runtime-capture-20261001 | 542b82e9 | 1 | 0 | 15 | no | UNKNOWN_REVIEW_REQUIRED | false | 4 patch-unique commits. |
| b15_A_rq1b | b15-rq1b | 4d78561c | 0 | 3 | 20 | no | UNKNOWN_REVIEW_REQUIRED | false | Rescue commit, 20 unique files. |
| b15_B_placement | b15-placement | 6e4f56e8 | 0 | 0 | 13 | no | UNKNOWN_REVIEW_REQUIRED | false | 13 unique files. |
| b15_C_rq4 | b15-rq4-forensics | 41e2b7cd | 0 | 0 | 18 | no | UNKNOWN_REVIEW_REQUIRED | false | Forensics commit, 18 unique files. |
| lane_A1_rq1a-execution (F:) | rq1a-execution | 7437ee53 | 0 | 11 | 14 | no | UNKNOWN_REVIEW_REQUIRED | false | Determinism-matrix execution result. |
| lane_A2_rq2-authority | rq2-authority | 2159a358 | 0 | 0 | 11 | no | UNKNOWN_REVIEW_REQUIRED | false | RQ2 authority layer. |
| rq2-validate-20261008 | rq2-authority-validate-20261008 | 2159a358 | 0 | 1 | 11 | no | UNKNOWN_REVIEW_REQUIRED | false | Same SHA as lane_A2. |
| lane_A4_rq5-readiness | rq5-readiness | 7a2310c2 | 0 | 0 | 32 | no | UNKNOWN_REVIEW_REQUIRED | false | RQ5 gate fixtures (LFS). |
| p0-coord-frame-tile-placement-20261001 | fix/p0-coord-frame-tile-placement-authority-20261001 | fb6c5e18 | 0 | 1 | **989** | no | UNKNOWN_REVIEW_REQUIRED | false | **989 unique files** — largest divergent surface. |
| carla_final_offline_closure | review/carla-final-offline-closure-20261003 | f6b983ef | 0 | 2 | 139 | no | UNKNOWN_REVIEW_REQUIRED | false | 38 patch-unique commits. |
| carla-control-plane | control/writer-lock-semantic-diff-20261006 | fdc8c166 | 1 | 42 | 71 | no | UNKNOWN_REVIEW_REQUIRED | false | 9 patch-unique commits, 71 unique files. |
| smoke-harden-20261009 | fix/carla-smoke-suite-skip-harden-20261009 | 62f0d288 | 0 | 1 | 0 | yes | PATCH_EQUIVALENT_ABSORBED | false | Content absorbed. |
| agent-a601acc34bd5e6126 | worktree-agent-a601acc34bd5e6126 | e0aa1aab | 2 | 27 | 0 | no | UNKNOWN_REVIEW_REQUIRED | false | Stale 2026-01-08 "Initial commit"; 4375 files differ but 0 unique. |
| agent-a9677fdcd7c1172ea | worktree-agent-a9677fdcd7c1172ea | e0aa1aab | 2 | 16 | 0 | no | UNKNOWN_REVIEW_REQUIRED | false | Same stale commit. |

**Truly safe candidates (3):** `wt-topology-convergence`, `wt-consolidate-20261008`, `lane_A1_rq1a-execution` — all with 0 dirty, 0 untracked, 0 unique files. Even so, deletion is not authorized by this report.

---

## 3. Priority worktrees — detailed absorption findings

### 3.1 `wt-gap055-fix` — GAP-055 WinDLL (a trap for ancestry-only audits)

The worktree HEAD `bec68678` is **not** an ancestor of the baseline, and `git cherry` reports 2 `+` (patch-unique) commits:

```
+ 08a55439 fix(gap055): platform-guard module-level ctypes.WinDLL so Linux collection succeeds
+ bec68678 fix(gap055): guard orphan_terminal_witness WinDLL + extend test coverage
```

An ancestry-only or patch-id-only audit would report this as unique live value. **It is not.**

The baseline carries the same two fixes under **different SHAs** with identical subject lines (`19cdb3a2`, `3c9048be`). The `--stable` patch-IDs differ:

```
baseline 19cdb3a2 pid=8744673375b1378d...
worktree 08a55439 pid=5bd46579162d56e5...
baseline 3c9048be pid=bdc414013d2bca76...
worktree bec68678 pid=22ab20e979bbd8ef5...
```

Patch-ID divergence here is an artifact of differing parent context, **not** differing content. Content check:

```
$ git diff <baseline> bec68678 -- tools/orphan_terminal_witness.py
(no output — identical)
```

The remaining whole-tree diff (`33 files changed, 178 insertions(+), 5449 deletions(-)`) is entirely the baseline being **ahead** — the deletions are baseline-only content, not worktree-only content.

**Classification:** the committed content of the GAP-055 fix **is present on the baseline**. The worktree directory is additionally marked **prunable** (`gitdir file points to non-existent location`).

### 3.2 `wt-gap026-fix` — GAP-026 geometry

```
$ git cherry -v <baseline> 0f3c3601
- 0f3c3601 fix(gap026): junction lane-width harmonizer + outer->inner mispair prune guard (source-stage only)
```

`-` = the patch is **already present on the baseline** (baseline carries it as `9ff56e7d`). `uniq_files = 0`. The fix is absorbed; only the branch ref diverges. Note the branch name (`...-20261011`) suggests it is *newer* than the baseline, but its content is strictly older/equivalent.

### 3.3 `wt-gap048` / `wt-gap048-m3` — GAP-048 lane successor

```
$ git cherry -v <baseline> ef3003c2
- ef3003c2 GAP-048: Source-stage through-junction lane successor repair (strategy 3)
```

Also patch-absorbed (baseline carries `2af80330`), `uniq_files = 0`. `wt-gap048` is **prunable**. `wt-gap048-m3` additionally carries **16 untracked files** that exist in no commit.

### 3.4 `wt-topology-convergence` / `wt-topo-conv` — the baseline itself

Both are detached at `3a6f3225`, which **is** the baseline. `wt-topology-convergence` is clean (0/0/0) and is the single cleanest removal candidate in the repository.

---

## 4. Duplicate implementation families

`patch_unique` = commits not patch-present on the baseline; `patch_eq` = commits already patch-present.

| family | canonical current branch | older / equivalent branches | extra unique value | fully superseded |
|---|---|---|---|---|
| **GAP-055 WinDLL** | `origin/fix/gap055-ci-windll-platform-guard-20261011` (`bec68678`) | `fix/gap055-ci-windll-import-safety-20261009` (u=1), `-clean-20261009` (u=2), `-platform-guard-20261009` (u=1) | content of all four is on the baseline | 3 older variants, subject to content review |
| **GAP-048 lane successor** | `origin/hardening/new225-233-gap040-048-20261001` (`f3a996f7`, u=1) | `fix/gap048-through-junction-20261009` (patch_eq=1) | hardening branch carries 1 unique commit | `fix/gap048-*` content absorbed |
| **GAP-026 geometry** | `fix/gap026-junction-lanelink-generator-20261011` (patch_eq=1) | `o10-gap026-severe-tail-fixtures`, `o11-gap026-checker-bias-matrix` (both ABSORBED) | `docs/policy-decisions-gap026-20261008` (u=7) is doc-only and **not absorbed** | 2 fixture branches |
| **RQ2 authority** | `rq2-authority` (`2159a358`, u=2) — `rq2-authority-validate-20261008` is the **same SHA** | `integration/rq2-authority-merge-20261009` (u=2), `opencode/batch10-rq2-authority-20261002` (u=1), `origin/rescue/lane-a2-rq2-authority-20261006` (u=1) | merge-verify branch has 9 unique files | exact-duplicate pair (2159a358) |
| **RQ4 reproducibility** | `b15-rq4-forensics` (`41e2b7cd`, u=3) | `rq4-reproducibility` / `origin/rescue/lane-a3-rq4-repro-20261006` (same SHA `c3031ad9`, u=1), `b15-rq4` (u=2), `opencode/batch11-rq4-repro-20261002` (u=2) | forensics branch: 18 unique files | exact-duplicate pair (c3031ad9) |
| **RQ5 readiness** | `opencode/batch12-rq5-readiness-20261002` (`cdf60165`, u=24) | `rq5-readiness` (u=2), `origin/rescue/lane-a4-rq5-readiness-20261006` (u=1) | batch12 carries 24 unique commits; `fix/rq5-test-isolation-leak-20261009` is **fully absorbed** | rq5-isolation branch |
| **CARLA runtime diagnostics** | `tools/gap017-diagnostic-toolkit-20261008` (`35e78936`, u=13) | `o7-rpc-startup-instrumentation`, `o8-runtime-map-qa`, `integration/opencode-runtime-rig-environment-closure-20261001` — all **ABSORBED** | gap017 toolkit: 13 unique commits, live RPC probe | 3 absorbed branches |
| **cook diagnostics** | `fix/gap049-package-write-poller-delta-only-20261011` (`73cbcb3e`, u=1) | `tools/cook-diagnostics-harness-20261008` (`c859cd83`, u=16) | 73cbcb3e is newest and **not** on baseline; fixes a real disk-exhaustion defect | none |
| **RQ1 profiler** | `tools/rq1-stage-profiler-20261008` (`64ce3fae`, u=19) | `fix/gap046-stage-profiler-20261009` (u=3), `trial/rq1-determinism-20261007` (u=2) | `fix/rq1-matrix-integrity-20261001` and `origin/rq1-determinism-matrix-update` are **fully absorbed** | 2 absorbed branches |

---

## 5. Uncommitted evidence in `carla_-main` (highest data-loss risk)

The primary worktree holds ~279 untracked files. Spot-checked the scientifically relevant ones:

| file | in baseline? | commits anywhere? |
|---|---|---|
| `reports/GAP026_ROOT_CAUSE_AUDIT.json` | no | **0** |
| `reports/GAP026_FIX_VALIDATION.json` | no | **0** |
| `reports/GAP026_FINAL_CLASSIFICATION.md` | no | **0** |
| `reports/GAP055_FINAL_VERDICT.md` | no | **0** |
| `reports/GAP055_SHARED_TREE_CONTAMINATION_INVENTORY.txt` | no | **0** |
| `RQ2_FINAL_VALIDATION.json` | no | **0** |
| `RQ4_FINAL_VALIDATION.json` | no | **0** |
| `HH1_VERIFICATION_REPORT.md` | no | **0** |

Method validation: the same query against a **known-tracked** file (`reports/C44_fresh_claude_session_test.json`) returns 2 commits, confirming the zero results are real and not a broken query. Breakdown of untracked content: **157** under `reports/`, **52** `scripts/`, **12** `tests/`, **10** `ultimate_pipeline/`, **7** `tools/`.

**These bytes exist in no branch, no remote, and no reflog-safe location.** They are irreplaceable unless captured. Additionally `ultimate_pipeline/pipeline_stages/stage_07_lanes.py` is modified-but-uncommitted, directly overlapping the GAP-026/GAP-048 topology work.

---

## 6. TOP branches requiring review

Ranked by risk of losing real value if removed without inspection.

1. **p0-coord-frame-tile-placement-20261001** — 989 files unique to it; largest divergent surface in the repo.
2. **carla_final_offline_closure** (`f6b983ef`) — 38 patch-unique commits, 139 unique files.
3. **fix/p0-coord-frame-tile-placement-authority-20261001** (worktree of the above) — same surface, not remote-preserved.
4. **carla-control-plane** (`fdc8c166`) — 9 patch-unique commits, 71 unique files, 42 untracked, 1 modified.
5. **review/carla-final-offline-closure-20261003** (worktree) — the above, uncommitted extras.
6. **opencode/batch12-rq5-readiness-20261002** — 24 patch-unique commits (largest commit-count family).
7. **tools/rq1-stage-profiler-20261008** — 19 patch-unique commits.
8. **tools/cook-diagnostics-harness-20261008** — 16 patch-unique commits.
9. **rq5-sightb-20261009** (detached `cfc0cd9c`) — 15 patch-unique commits **and** 100 untracked files.
10. **tools/gap017-diagnostic-toolkit-20261008** — 13 patch-unique commits (live RPC diagnostic probe).

Additional exact-duplicate pairs (same SHA, different names — safe to deduplicate as names, not content): `rq2-authority` = `rq2-authority-validate-20261008` (`2159a358`); `rq4-reproducibility` = `origin/rescue/lane-a3-rq4-repro-20261006` (`c3031ad9`).

---

## 7. What this audit could not determine

- **Patch-level verification was computed exhaustively for ~60 branches and worktree HEADs only.** The remaining ~450 non-absorbed branches carry `NOT_COMPUTED` patch counts in `BRANCH_ABSORPTION_MATRIX.json` and are classified `UNKNOWN_REVIEW_REQUIRED`. A full `git cherry` sweep over 514 branches with divergent history is the exact blocker.
- **The `ahead` column is not a value signal.** Ancient lineages (`safety/pre-codex-clean-handoff-20260427`, `fix/geometry-topology-closure-batch`, `work/codex-jsnap-20260428`) show 400–774 "ahead" purely from lineage divergence since 2026-04/05, not unique work. Most such branches are `HISTORICAL_EVIDENCE` / `OBSOLETE_FAILED_EXPERIMENT`.
- **Sparse/partial checkout state** was not verified per worktree; `dirty` counts reflect each worktree's own index.
- **Because the repo changed mid-audit**, counts are a lower bound on churn, not a fixed state.

---

## 8. Verdict

```
REPOSITORY_VALUE_MAP_PARTIAL_EXACT_BLOCKERS
```

The absorption structure of the four priority worktrees is **resolved with high confidence** (§3), including one genuine trap (§3.1) where ancestry and patch-id both disagree with the content. Repository-wide coverage is **not** complete: 450 of 514 branches remain patch-unverified, and the concurrent-writer condition (§0.2) makes the snapshot non-stable.