# Session Closure — 2026-10-09 (verification sweep)

**Production branch tip:** `origin/integration/production-large-map-20260918 @ 68868f76` (re-fetched at doc time; unchanged since the 2026-10-08 fast-forward `a82e0201..68868f76`). No merges into production since.

**Map-of-record pin:** `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr` (sha256 `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`)

**Session scope:** Fresh verification pass over the gap register, all branches pushed in the last ~48h, the RQ2 scope-note commit, and RQ1–RQ5 status. This supersedes the 2026-10-08 closure document's numbers (that file is historical; this file re-derives everything live).

"MERGED" below means the production commit SHA containing the work is cited. Nothing else qualifies.

---

## 1. Gap Register Counts — Verified Against Live JSON (54 entries)

Independent re-scan of every `status` field in `MASTER_GAP_REGISTER.json` (`last_updated_utc 2026-10-09T10:15:00Z`), using the register's documented taxonomy (case-insensitive prefix match; `closed` absorbs the non-reproducible closures; `CHECKER fixed` and `ROOT CAUSE PROVEN` are separate buckets):

| Bucket | Count | Member IDs |
|--------|-------|------------|
| **fixed** | 33 | GAP-001..007, 009..012, 016, 018, 019..025, 027..030, 032..035, 040, 043, 044, 045, 051 |
| **closed** | 7 | GAP-013, 014, 015, 037, 041, 050, 054 |
| **deferred** | 1 | GAP-008 |
| **blocked_external** | 1 | GAP-017 |
| **open** | 10 | GAP-026, 036, 038, 039, 042, 046, 048, 049, 052, 053 |
| **checker_fixed_underlying_open** | 1 | GAP-031 |
| **root_cause_proven** | 1 | GAP-047 |
| **Total** | **54** | 33+7+1+1+10+1+1 = 54, 0 unclassified |

**Counts-block verdict: numbers correct, prose fixed.** The block's tallies match the scan exactly. Its reconciliation note had one presentational defect — the range string `027..035` textually includes GAP-031 while the arithmetic (correctly) counts 031 once under `checker_fixed_underlying_open`. Fixed in the working tree (one-line prose edit, counts untouched): the range now reads `027..030,032..035` with 031 explicitly excluded here. No status field was changed.

**Changes since the prior version of this file** (which recorded 52 entries): **+GAP-053** (open: fail-silent per-tile tiling-timeout handling in `run_full_domain_gap.py`) and **+GAP-054** (closed: RQ2 metric-scope determination). The counts block was recomputed for the new taxonomy the same day (closed absorbs 013/014/015; `closed_non_reproducible` retired to 0; two new single-member buckets).

---

## 2. Branch Merge-Base Audit — All Branches Pushed in the Last ~48h

Each branch tip below is the live `origin/` ref, audited with `git merge-base` against production tip `68868f76`. Classification: **AT-TIP** (tip equals production content), **CLEANLY-BASED** (merge-base is the production tip — contains it), **NEEDS-REBASE** (otherwise — merge-base cited, do not merge as-is).

| Branch (origin/) | Tip | Merge-base w/ prod tip | Status |
|---|---|---|---|
| `fix/signal-producers-and-unknown-state-20261007` | `68868f76` | `68868f76` | **AT-TIP** (= production content) |
| `fix/carla-smoke-suite-skip-harden-20261009` | `62f0d288` | `68868f76` | **CLEANLY-BASED** |
| `integration/consolidate-fixes-20261008` | `75371cd9` | `68868f76` | **CLEANLY-BASED** |
| `fix/gap039-new276-20261008` | `176822c9` | `68868f76` | **CLEANLY-BASED** |
| `fix/gap039-new274-275-20261008` | `61df05a4` | `68868f76` | **CLEANLY-BASED** |
| `docs/session-closure-20261008` | `6e521ec5` | `68868f76` | **CLEANLY-BASED** (docs only) |
| `tools/rq1-stage-profiler-20261008` | `64ce3fae` | `647c0ad5` | **NEEDS-REBASE** |
| `docs/sync-gap-register-md-20261008` (this document's branch) | `541d0224` | `647c0ad5` | **NEEDS-REBASE** (see note) |
| `docs/rq2-metric-scope-determination-20261008` | `4ac356ea` | `647c0ad5` | **NEEDS-REBASE** |
| `rq5-readiness` | `7a2310c2` | `7fbd33ff` | **NEEDS-REBASE** (older lane base) |
| `rq2-authority` | `2159a358` | `7fbd33ff` | **NEEDS-REBASE** (older lane base) |
| `tools/cook-diagnostics-harness-20261008` | `c859cd83` | `647c0ad5` | **NEEDS-REBASE** |
| `fix/gap039-new291-shapin-20261008` | `8a796839` | `647c0ad5` | **NEEDS-REBASE** |
| `fix/gap051-registry-coverage-20261008` | `cfc0cd9c` | `647c0ad5` | **NEEDS-REBASE** |
| `tools/gap017-diagnostic-toolkit-20261008` | `35e78936` | `647c0ad5` | **NEEDS-REBASE** |
| `fix/gap047-untracked-module-import-20261008` | `ec86903f` | `647c0ad5` | **NEEDS-REBASE** |
| `docs/gap047-real-root-cause-20261008` | `4c69461c` | `647c0ad5` | **NEEDS-REBASE** |
| `docs/pcd3d-es31-fix-disclosure-20261008` | `2489c89e` | `647c0ad5` | **NEEDS-REBASE** |
| `fix/gap050-output-path-comparator-20261008` | `1e75454e` | `647c0ad5` | **NEEDS-REBASE** (GAP-050 itself closed; fix unneeded) |
| `docs/ff1-ff4-scout-reports-20261008` | `e636421f` | `647c0ad5` | **NEEDS-REBASE** |
| `fix/gap039-new277-20261008` | `e61b7fcd` | `647c0ad5` | **NEEDS-REBASE** |
| `docs/policy-decisions-gap026-20261008` | `bdf0c5db` | `647c0ad5` | **NEEDS-REBASE** |
| `docs/fix-verification-close-20261008` | `aa83d278` | `647c0ad5` | **NEEDS-REBASE** |
| `docs/fix-repo-state-sync-self-reference-20261007` | `cc0a659c` | `a82e0201` | **NEEDS-REBASE** (prior production tip) |

**Note on this branch:** `docs/sync-gap-register-md-20261008` itself is NEEDS-REBASE (cut from the `647c0ad5` working line; production moved past it via the reconciliation fast-forward). It is documentation/register-only; a rebase replays cleanly in principle but was **not performed** — rebase/modify/merge of audited branches is out of scope for this task.

**No branches merged into production.** Tip unchanged since 2026-10-08.

---

## 3. Policy Decision vs. Further Engineering vs. Done

| Gap | Category | Detail |
|-----|----------|--------|
| **GAP-017** | **Blocked external (owner action)** | Packaged CARLA RPC hang. Sharper diagnostic on record (CPU spin, zero logs); needs debugger/ETW on the live process — not done, not delegable. Diagnostic toolkit exists and is independently tested (`tools/gap017-diagnostic-toolkit-20261008`, unmerged). |
| **GAP-026** | **Policy decision required** | 12.7% lane-link pose failures on promoted map; checker runs but no gate reads it. 4 costed options in policy doc (unmerged branch). AGENTS.md bars tolerance-raising. |
| **GAP-036** | **Policy decision required** | Build executing consumer vs. deprecate the YAML contract. |
| **GAP-037** | **Done (closed 2026-10-08)** | Premise went stale — moved to closed this session; no longer awaiting a decision. |
| **GAP-038** | **Policy decision required** | Wire in vs. defer the two unwired contract modules. |
| **GAP-039** | **Engineering in flight** | NEW-274/275/276/277 implemented on pushed-but-unmerged branches; NEW-288 settled moot (pre-existing guard); NEW-291 inert pending SHA pins. Gap stays open. |
| **GAP-042** | **Policy decision required** | OSM2World re-enable vs. RoadRunner install+wire. |
| **GAP-046** | **Engineering in flight** | X2 driver fix committed (dies loudly, verified). Blocked downstream by GAP-048's map defect. |
| **GAP-047** | **Root cause proven, fix unmerged** | CI cause identified; fix sits on `integration/consolidate-fixes-20261008` (cleanly based), not production. CI itself still red — see §5. |
| **GAP-048** | **Engineering in flight** | 10,556 missing lane successors; fix module resolves 0 (needs through-junction strategy). |
| **GAP-049** | **Engineering in flight** | Cook stall at package 2975; harness ready, hang unresolved. |
| **GAP-050/054** | **Done (closed)** | Stale premise / out-of-contract-scope respectively. |
| **GAP-052/053** | **Open** | Procedural mitigation (052); narrow timeout-skip fix pending (053). |

---

## 4. RQ1–RQ5 Status (one table)

| RQ | Status | Basis |
|----|--------|-------|
| **RQ1** | Blocked — 0 clean trials | Driver robustness fixed and verified (loud failures); current blocker is GAP-048's map defect (10,556 missing successors fail the final_integrity gate on the pinned map). |
| **RQ2** | Headline solid; scope clarified | Ratios re-verified 2026-09-17 vs current pin (2.683x / 3.782x / 3.561x; Fréchet 58.18/36.13/140.48 m). Curvature KL, alignment quality, per-tile metrics determined OUT of contracted scope (`RQ2_METRIC_SCOPE_DETERMINATION_20261008.md`, `4ac356ea`); scope note committed to thesis doc (`541d0224`, numbers untouched). |
| **RQ3** | Double-blocked | GAP-017 (no live CARLA) + GAP-042 (no roads/terrain) — neither delegable to engineering alone. |
| **RQ4** | Done | Leak-free retrain complete (reported previously; unchanged). |
| **RQ5(a)** | Double-blocked | Same two blockers as RQ3. |
| **RQ5(b)** | No open task addresses it | Data-acquisition problem outside this codebase. |

---

## 5. CI — Explicitly NOT Green

Re-queried live at doc time: the newest `tests.yml` run on the production branch is still **#208 (`37705726382`) on `68868f76` — completed, conclusion failure** (offline-tests collection abort, exit 2; five other jobs green; step logs access-gated). No newer run exists. GAP-047's fix is proven but unmerged, so CI is expected to stay red until the consolidate-fixes line lands. **Do not cite CI as a passing gate.**

---

## 6. Key Artifacts

| Artifact | State | Evidence |
|----------|-------|----------|
| `MASTER_GAP_REGISTER.json` | **Counts verified; one prose line fixed** | 54 entries; tallies match direct scan; `027..030,032..035` clarification committed with this doc |
| `MASTER_GAP_REGISTER.md` | **Stale** | Still at the 47-entry generation; the `tools/sync_gap_register_md.py` classifier predates the new `checker_fixed_underlying_open` / `root_cause_proven` buckets and would mis-scan — sync tool needs a bucket update before reuse |
| `docs/research/THESIS_TO_CURRENT_PROGRESS.md` | **RQ2 scope note committed** | `541d0224`, 2-line insertion, byte-identical to approved diff, zero numbers changed |
| Map-of-record | **Pinned at `370abbbb...`** | Unchanged; last `verify_pinned_map` returned VERIFIED (149,799,632 bytes, STRUCTURED) in a prior session — not re-run in this sweep |
| Full pytest (production tip) | **7341 passed + known flake** | 1571 s isolated worktree (prior measurement, attributed not re-run) |

---

## 7. PR

No PR is open for this document. To open one manually (no `gh` CLI in this environment):

`https://github.com/lemoniadowyjohn/carla-control-suite/compare/integration/production-large-map-20260918...docs/sync-gap-register-md-20261008`

Note: that compare includes the branch's register/thesis commits too (it NEEDS-REBASE, see §2) — a docs-only PR would need a dedicated branch cut from the production tip. **No merges performed by this session.**

---

*Re-verified 2026-10-09 against live JSON, live refs, live CI API, and committed diffs — no aspirational language. "Merged" claims cite production SHAs; everything else names its branch and state.*
