# Live Repository — Read-Only Value Audit

**Repository:** `lemoniadowyjohn/carla-control-suite`
**Mode:** STRICTLY READ-ONLY — no branch, commit, push, fetch, checkout, reset, clean, worktree remove, or prune. No files written inside the repository.
**Output:** external directory only.
**Canonical topology:** `3a6f32255916b9783e41981ba284d68401294a92` (`origin/fix/topology-convergence-gap026-gap048-20261011`)

---

## Scope conflict resolved

This task (`REPO-CONV-03R`) explicitly forbids commits, pushes, and worktree removal, while `REPO-CONV-02`/`REPO-CONV-05` require exactly those. **This read-only task was executed; the mutating stages were not.** Everything stages 2–3 exist to *discover* was determined here without any mutation. Preservation and cleanup remain unperformed by design.

---

## Terminal summary

```
REPOSITORY_CHANGED_DURING_AUDIT=false   (HEAD/show-ref/worktree-list/ls-remote all identical at T0 vs T1)

WORKTREES_ANALYZED=33
WORKTREES_CHANGED_DURING_AUDIT=0

UNIQUE_CODE_WORKTREES=8      (clean+stable, awaiting review)
UNIQUE_EVIDENCE_WORKTREES=1  (carla_-main, 8 unpreserved evidence files)
ABSORBED_WORKTREES=0         (all remaining are PRESERVE_DIRTY or stale registrations)
UNKNOWN_WORKTREES=0

BRANCHES_CLASSIFIED=751
BRANCHES_UNKNOWN=0

CANONICAL_TOPOLOGY      =3a6f3225  origin/fix/topology-convergence-gap026-gap048-20261011
CANONICAL_COOK_DIAG     =73cbcb3e  origin/fix/gap049-poller-delta-only-20261011
CANONICAL_RUNTIME       =(no single canonical; GAP017 toolkit SEMANTICALLY_SUPERSEDED)
CANONICAL_RQ1           =(tools/rq1-stage-profiler-20261008 not yet canonical)
CANONICAL_RQ2           =2159a358  origin/rq2-authority
CANONICAL_RQ3           =fix/rq3-grid0828-governance-20261007
CANONICAL_RQ4           =b15-rq4-forensics (41e2b7cd) — CURRENT_LIVE_VALUE
CANONICAL_RQ5           =7a2310c2  origin/rq5-readiness

HIGH_VALUE_STABLE_FILES=8
LIVE_FILES_DEFERRED=0

EVENTUAL_SAFE_REMOVAL_COUNT=8
EVENTUAL_RESCUE_BRANCHES_NEEDED=0 (determined, not created)

RQ1_STATUS=IMPLEMENTED_NOT_REAL_VERIFIED
RQ2_STATUS=IMPLEMENTED_NOT_REAL_VERIFIED
RQ3_STATUS=IMPLEMENTED_NOT_REAL_VERIFIED
RQ4_STATUS=IMPLEMENTED_NOT_REAL_VERIFIED
RQ5A_STATUS=IMPLEMENTED_NOT_REAL_VERIFIED
RQ5B_STATUS=BOUNDED_EXPLICIT_LIMITATION

FINAL_VERDICT=READ_ONLY_VALUE_MAP_COMPLETE
```

---

## 1. High-value stable evidence (8 files, all unrecoverable from git)

Every one verified: present, **size+mtime stable across the hashing window**, `sha256` computed, **0 commits anywhere**.

| file (repo root unless noted) | bytes | in any commit |
|---|---|---|
| `GAP026_ROOT_CAUSE_AUDIT.json` | 5,156 | 0 |
| `GAP026_FIX_VALIDATION.json` | 3,006 | 0 |
| `reports/GAP026_FINAL_CLASSIFICATION.md` | 1,438 | 0 |
| `reports/GAP055_FINAL_VERDICT.md` | 3,749 | 0 |
| `reports/GAP055_SHARED_TREE_CONTAMINATION_INVENTORY.txt` | 11,712 | 0 |
| `RQ2_FINAL_VALIDATION.json` | 1,903 | 0 |
| `RQ4_FINAL_VALIDATION.json` | 2,252 | 0 |
| `HH1_VERIFICATION_REPORT.md` | 8,632 | 0 |

Path correction confirmed: `GAP026_ROOT_CAUSE_AUDIT.json` and `GAP026_FIX_VALIDATION.json` are at **repository root**, not `reports/`.

**These are the only genuine HIGH__UNIQUE_NOT_IN_ANY_COMMIT artifacts found, and they are the entire irreversible-loss risk in this repository.**

## 2. Live-file safety (§6)

`stall_watchdog_log.csv` was being appended to during earlier checks. It was **excluded from hashing** by the size+mtime rule. During *this* audit window all 8 target files proved stable, so `LIVE_FILES_DEFERRED=0` — but the surrounding writers (cook poller, watchdog, `run_pipeline`) remain active and can re-enter at any time.

## 3. GAP049 current state (§11)

On `73cbcb3e`:
- `UNCHANGED_ROWS_REMOVED=true` — `if record.status != "unchanged"` filter added
- `PER_ROW_FLUSH_REMOVED=true` — flush moved to per-cycle
- `POLLER_DISK_OUTPUT_DEFECT=RESOLVED_IN_PATCH` (273 MB/1.43M-row → delta-only)
- `POLLER_SCAN_OVERHEAD=STILL_PRESENT` — `_compute_sha256` still runs on **every file every cycle**; it is the change-detection mechanism, so delta filtering did not remove it

Status: `LOCAL_PASS_CI_PENDING`. Not yet on canonical (1 patch-unique commit).

## 4. Worktree state

- `CLEAN_STABLE=8` — `b15_B_placement`, `b15_C_rq4`, `lane_A2_rq2-authority`, `lane_A4_rq5-readiness`, `wt-base-9fa11e1`, `wt-gap026-fix`, `wt-gap049-ev`, `wt-gap049-fix`
- `PRESERVE_DIRTY=21`
- `MISSING_PATH=4`

**Prior removal candidates re-checked — and corrected:**

| worktree | finding |
|---|---|
| `wt-topology-convergence` | **directory already gone**; HEAD `3a6f3225` still on remote |
| `wt-consolidate-20261008` | **directory already gone**; HEAD `75371cd9` on 6 remote refs |
| `lane_A1_rq1a-execution` | still present, but `PRESERVE_DIRTY` (untracked) — **not** a removal candidate |

Three new worktrees appeared mid-session (`wt-admission`, `wt-base-9fa11e1`, `wt-gap049-ev`), and the 4 above vanished — **all changes made by other agents, not this audit.**

## 5. Two preservation risks found

1. **4 stale worktree registrations** (`wt-gap048-m3`, `wt-topology-convergence`, `wt-consolidate-20261008`, `wt-rq2-merge-verify-20261009`) — registered but absent on disk.
2. **`af90dd91` (`integration/rq2-authority-merge-20261009`) is contained in ZERO remote refs.** Its worktree directory is gone; the commit now survives *only* as a local branch. This is the single highest-risk local-only artifact after the 8 evidence files.

## 6. Completion matrix (19 items)

`IMPLEMENTED_NOT_REAL_VERIFIED=10`, `NOT_RUN=5` (GAP031/038/042/052/053), `BOUNDED_EXPLICIT_LIMITATION=2`, `LOCAL_PASS_CI_PENDING=1` (GAP049), `CURRENT_LIVE_VALUE_PENDING_MERGE=1` (GAP046).

`CODE_IMPLEMENTED` / `UNIT_TESTED` reflect **presence on the canonical tree, not execution** — no test was run (read-only). `RUNTIME_VERIFIED=false` throughout: no RPC-response evidence was inspected, and per repo rule port-listening is not CARLA success.

## 7. Branch classification

751 branches, **UNKNOWN=0**: 337 `ANCESTOR_ABSORBED`, 215 `SEMANTICALLY_SUPERSEDED`, 98 `HISTORICAL_EVIDENCE`, 51 `CURRENT_LIVE_VALUE`, 34 `PATCH_EQUIVALENT`, 16 `CONTENT_ABSORBED`.

Apparent "unique file count" mostly reflects generated artifacts, not value — `p0-coord-frame-tile-placement`'s 989 unique files are 418 `.json` + 160 `.properties` + 80 `.osm` + 64 `.fbx` cook outputs.

---

## Output files (external only)

`START_SNAPSHOT.json` · `END_SNAPSHOT.json` · `WORKTREE_VALUE_MATRIX.json` · `BRANCH_VALUE_MATRIX_V2.json` · `BRANCH_FAMILY_CANONICAL_MAP.json` · `STABLE_EVIDENCE_INVENTORY.json` · `EVENTUAL_MERGE_PLAN.json` · `EVENTUAL_WORKTREE_REMOVAL_PLAN.json` · `COMPLETION_MATRIX.json` · `LIVE_REPO_AUDIT_SUMMARY.md`

No repository file was created, modified, or deleted.