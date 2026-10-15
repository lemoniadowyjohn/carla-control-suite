# Recent branch value / absorption / rebase triage — 2026-10-09

**READ-ONLY.** No rebase, merge, cherry-pick, force-push, branch deletion or
worktree modification was performed. `BRANCHES_MODIFIED=false`.

`SESSION_CLOSURE_20261009.md` was **not trusted**. Everything below was
re-derived from `origin` refs after `git fetch --all --prune`, per the stale-document
warning.

## Authorities (re-derived live)

| role | ref | sha |
|---|---|---|
| production | `origin/integration/production-large-map-20260918` | `68868f763d22a630fc9ba8d818ed1919a7b8414d` |
| consolidation | `origin/integration/consolidate-fixes-20261008` | `75371cd900f2ec4ef745bfe2db78f03eb1765642` |
| gap register | `docs/sync-gap-register-md-20261008` | `4a5dc8da36e7bd236ae4ea1a9aa9c7824fda9cbf` |

Consolidation vs production: **8 ahead / 0 behind**.
Gap register vs production: **22 ahead / 16 behind**, merge-base `647c0ad5` → **do not merge wholesale** (confirmed, instruction upheld).

## Recent branch count — 24 reproduces exactly at a 36h window

Derived from remote refs' `committerdate`, not a hand-written list.

| window | count |
|---|---|
| 24h | 9 |
| **36h** | **24** ← matches the reported figure |
| 48h | 36 |
| 60h | 40 |
| 72h | 42 |

Total remote branches: 230. The "24" was a 36-hour window. Reported, not forced.

## The structural finding

Eight of the ten audited branches share the **same polluted base**: they descend from
`647c0ad5` and each carries 12–17 commits (`c907d13b2 … 373d36f90`) that exist in
**neither** production nor consolidation. That shared base is why GitHub reports
"+17/−16" and "+20/−20" for the tool branches — it is **not** evidence of unique value
in those branches.

This is why patch-id and ancestry must both be used. `git cherry` against
consolidation reports 13–20 commits "not present" for branches whose actual content
is byte-identical to consolidation. Ancestry divergence alone would have mislabelled
all of them.

## Consolidation's 8 commits over production

```
75371cd9 test(thesis): NEW-291 SHA-pin mechanism tests + document why no pin is set
c35c3a37 fix(contracts): GAP-051 -- GATE_CLASS_REGISTRY must cover the gates actually emitted
53030452 fix(train_launcher): restore missing validate_num_classes import
e10839c6 feat(gap017): one-command live RPC diagnostic probe
616d1eb7 fix(tests): GAP-047 -- stop collection aborting on an untracked module
ee7dc19a feat(train_launcher): NEW-277 DATASET_ACCEPTANCE enforcement (GAP-039)
c87431fa fix(perception): NEW-276 label_quality any/unlabeled/learnable-fraction split
3de7b33d fix(gap039): implement NEW-274 atomic capture commits + NEW-275 API docs
```

## Phase 4/5 — explicit audit of the ten named branches

| branch | ancestry vs prod | classification | evidence |
|---|---|---|---|
| `fix/gap039-new274-275-20261008` | +0/−1, mb `68868f76` | **A_FULLY_ABSORBED** | `capture_writer.py` + `perception_api.py` blobs **IDENTICAL in cons** |
| `fix/gap039-new276-20261008` | +0/−1, mb `68868f76` | **A_FULLY_ABSORBED** | `label_quality.py` **IDENTICAL in cons** |
| `fix/gap051-registry-coverage-20261008` | +16/−16, mb `647c0ad5` | **A_FULLY_ABSORBED** | `stage_contracts.py` + test **IDENTICAL in cons** |
| `fix/gap047-untracked-module-import-20261008` | +16/−14, mb `647c0ad5` | **A_FULLY_ABSORBED** | both T6 test files **IDENTICAL in cons** |
| `fix/gap039-new291-shapin-20261008` | +16/−17, mb `647c0ad5` | **A_FULLY_ABSORBED** | `test_manual_refs_sha_pin.py` **IDENTICAL in cons** |
| `fix/gap039-new277-20261008` | +16/−13, mb `647c0ad5` | **A_FULLY_ABSORBED** | test **IDENTICAL in cons**; `train_launcher.py` differs by exactly **1 line** — consolidation's `53030452` is a **superset fixup** on top of this branch's work |
| `fix/gap050-output-path-comparator-20261008` | +16/−13, mb `647c0ad5` | **C_OBSOLETE_OR_STALE_PREMISE** | GAP-050 is CLOSED as stale. **Verified directly:** production's `COMPARED_KEYS` does not contain `output_path`, with the comment "`output_path` and `out_dir` are deliberately NOT compared as measured" |
| `tools/cook-diagnostics-harness-20261008` | +16/−17, mb `647c0ad5` | **B_UNIQUE_LIVE_VALUE** | all 3 tools **absent from prod AND cons** |
| `tools/rq1-stage-profiler-20261008` | +16/−20, mb `647c0ad5` | **B_UNIQUE_LIVE_VALUE** | `tools/rq1_stage_profiler.py` **absent from prod AND cons** |
| `fix/carla-smoke-suite-skip-harden-20261009` | +0/−1, mb `68868f76` | **B_UNIQUE_LIVE_VALUE** | test file **absent from both**; `carla_smoke_suite.py` differs from both |

### GAP-050 checked especially carefully, as instructed

The register says the premise is closed/stale. **Confirmed independently rather
than taken on trust:** production at `68868f76` already excludes `output_path` from
`COMPARED_KEYS`. Branch `1e75454e2` re-lands an already-present fix and adds nothing
live. It should remain inert.

### `fix/gap039-new277` is a superset case worth flagging

Consolidation's `train_launcher.py` is **one line newer** than this branch's, because
`53030452` restores an import this branch's version lacked. Consolidation is
strictly ahead. Re-landing `fix/gap039-new277` would **regress** that import — a
concrete argument for classifying it absorbed rather than "needs rebase".

## Minimal commits to integrate

| sha | branch | subject |
|---|---|---|
| `c859cd831` | `tools/cook-diagnostics-harness-20261008` | GAP-049: Add cook diagnostics harness |
| `64ce3fae9` | `tools/rq1-stage-profiler-20261008` | per-stage wall-clock profiler for RQ1 pipeline runs |
| `62f0d2885` | `fix/carla-smoke-suite-skip-harden-20261009` | skip xodr harden in carla_smoke_suite when CARLA unreachable |

**Caveat on the profiler branch:** it carries 5 commits absent from consolidation,
but only `64ce3fae9` introduces the tool. The other four (`dc7b9dc9`, `1829f9b5`,
`495796fc3`, `aff34c37d`) are **gap-register / SESSION_CLOSURE doc commits** that
belong to the register lineage and must not be cherry-picked with the tool.

No shared historical branch needs rebasing; one isolated commit each carries the
live value safely.

## PR #10 — `SUPERSEDED`

State: open, non-draft, unmerged. Head `docs/session-closure-20261008 @ 6e521ec5f`
→ base production. Last updated 2026-10-08T09:08:53Z.

Its body cites the older gap state; the current register at `4a5dc8da` reports
**total 55, fixed 33, closed 7, open 11**.

Recommended: **CLOSED_UNMERGED with a pointer to the register**, or SUPERSEDED —
not merged as-is. It is docs-only and touches no production code, so it cannot
break anything, but its gap-state content is superseded by a register branch that
itself must not be merged wholesale (22 ahead / 16 behind). Its cited production
lineage `a82e0201 → edf9be09 → 68868f76` **is** still accurate, because production
has not moved past `68868f76`.

**PR not mutated by this audit.**

## Artifacts

- `reports/RECENT_BRANCH_VALUE_AUDIT_20261009.json`
- `reports/RECENT_BRANCH_VALUE_AUDIT_20261009.md` (this file)
