# V104 P5 — Backlog PR close / supersede / retarget recommendation

**Author:** OpenCode
**Date:** 2026-11-12
**Scope:** the 13 backlog pull requests
**Mode:** **READ-ONLY RECOMMENDATION.** Nothing was closed, retargeted, merged or edited.
**Production lineage:** `integration/production-large-map-20260918` @ `225ed15d0da6444cc257835ca777aba281553f3c`

---

## 0. Scope of the 13

The repository holds 51 pull requests. They partition as:

| Group | PRs | Disposition in this document |
|---|---|---|
| **The 13 backlog PRs** | **#1, #4, #6, #7, #8, #9, #10, #17, #22, #23, #24, #25, #26** | **this document** |
| Current V94 wave | #28, #30–#38 | out of scope (actively reviewed) |
| OpenCode V103/V104 | #39–#47 | out of scope (mine) |
| Codex V86 / V106 in flight | #48, #49, #50, #51 | out of scope (in flight) |
| Already closed | #2, #3, #5, #16, #27, #29 | already closed |

The 13 are the open PRs that are neither the active V94 wave nor OpenCode's
own; they are the residual backlog.

---

## 1. Recommendation at a glance

| PR | Target | Recommendation | Confidence | Decisive fact |
|---|---|---|---|---|
| **#1** | `integration/governed-map-quality-20260729` | **CLOSE** (superseded) | High | 409 of its 660 files are byte-identical on production; its base is already an ancestor of production |
| **#4** | production | **CLOSE** (superseded; merging would regress) | High | production's `AGENTS.md`/`README.md` are *newer*; the PR would revert them |
| **#6** | `main` | **CLOSE** | High | the file it edits does not exist on the production lineage at all |
| **#7** | `main` | **CLOSE** | High | same |
| **#8** | `main` | **CLOSE** | High | same |
| **#9** | `main` | **CLOSE** (would weaken a pin) | High | production already requires `mypy>=1.19`; the PR proposes `mypy>=1.13,<3` |
| **#10** | production | **REWORK / RETARGET** — do not merge as-is; **owner decision** | High | 8 unresolved findings, 2 of them P1, including a literal `...[truncated 447 chars]` file ending |
| **#17** | `integration/post-pr16-final-20261102` | **RETARGET to production** — **owner decision first** | Medium | a new CI surface (gh-aw) whose base is 64 commits behind production |
| **#22** | #17's branch | **RETARGET with #17** | High | stacked on #17; closes with it |
| **#23** | #17's branch | **RETARGET with #17** | High | stacked on #17; a fail-closed diagnostic correction worth keeping |
| **#24** | `main` | **CLOSE** (intent already satisfied on the governed lineage) | High | production's workflows already use full 40-char SHAs for all 19 action refs |
| **#25** | `integration/post-pr16-final-20261102` | **CLOSE the PR; re-derive the 8 residual files on the current production head, by their owners** | High | the PR head is already an ancestor of production; 59 of 67 files are identical; merging would revert newer production content |
| **#26** | #25's branch | **RETARGET to production** (after #25's disposition) | Medium | the V23 audit + Codex/OpenCode remediation handoff is the highest-value item in the backlog |

**Totals: 8 CLOSE, 5 RETARGET/REWORK, 0 merge-as-is.**

---

## 2. Evidence base

Every statement below was produced by execution, not by reading PR descriptions.

* **GitHub REST API** (authenticated) — PR state, base/head SHAs, mergeability,
  the complete file list (paginated: #1 has 660 files and needed 7 pages), all
  review comments and review verdicts.
* **git** against the isolated clone `F:\v103\base` (own common dir
  `F:\v103\_gitdirs\base.git`) at `origin/integration/production-large-map-20260918`
  = `225ed15d0`.
* **Per-file blob comparison** — for every file of every PR, the blob SHA at the
  PR head was compared with the blob SHA at production. "Identical" means the
  same git object, not "similar".

**A methodological correction worth recording.** The first version of the
existence check used `git cat-file -e`, which prints **nothing** on success
*and* on failure. The check was inverted and reported "exists on production:
True" for files that do not exist there. Every file-existence claim in this
document was re-derived using the **exit code**, and the corrected results are
the ones reported. The first draft's conclusion — "every file already exists
on production" — was wrong and was discarded.

---

## 3. The three lineage facts that drive most of the recommendation

```
origin/integration/production-large-map-20260918   225ed15d0   (unchanged)
origin/integration/governed-map-quality-20260729    dac6930a7   ancestor of production
                                                       74 commits ahead of production
                                                       1302 commits behind production
origin/integration/post-pr16-final-20261102         1a36b560a   ancestor of production
                                                       0 ahead / 64 behind production
origin/main                                         fa1116ef1   ancestor of production
                                                       14 ahead / 1302 behind production
```

All three non-production base branches are **ancestors of production**: their
content is already in the production lineage. A PR whose base is an ancestor
of production is showing a diff against a base that has since moved on by
64–1302 commits, so its "changes" are usually already-landed content
presented as new.

`main` is the GitHub default branch and is 1302 commits behind production.
**No PR in this backlog should be merged into `main`.**

---

## 4. Per-PR findings

### #1 — Ingolstadt map quality v2 (draft, 660 files)

* Base `integration/governed-map-quality-20260729` @ `dac6930a7` — an ancestor
  of production, 1302 commits behind.
* Head `improvement/ingolstadt-map-quality-v2-202608` @ `f91f1df5f`, created and
  last touched **2026-08-03** (three months stale). Draft. `mergeable: clean`.
* **409 of 660 files are byte-identical on production.** 247 differ, 4 are
  absent from one side.
* The differing set is dominated by files the PR *added* that production has
  since changed independently (`ultimate_pipeline/carla_tools/*`,
  `ultimate_pipeline/core/*`, `ultimate_pipeline/debug/*`, …), plus
  `.gitattributes`, `pyproject.toml`, `tests/quality/test_ingolstadt_coordinate_verification.py`,
  `ultimate_pipeline/augmentation/realism_augmentor.py` and four candidate XODRs.
* The `opendrive_geometry/` package (11 files) is already on production.

**Recommendation: CLOSE as superseded.** The content has landed in a later
form; re-deriving the 247 differing files against the current production head
would be a different and much larger project than this PR.

**Explicit caution on the four candidate XODRs**
(`reports/ingolstadt_map_quality_v2/work_package_01_coordinate_truth/candidates/*.xodr`,
1.6 M lines each): these are *experiment candidates* from a work package whose
later sibling on production is `work_package_02_connectivity/rejected_attempt_v1/`.
They must not be promoted into the production evidence tree. If the owner
wants the coordinate-truth evidence, it should be re-derived as an immutable
frozen artifact with its own receipt — not merged from a three-month-old draft.

### #4 — docs: sync current authority, worktree hygiene and test coverage gaps (draft, 8 files)

* Base production @ `cfa393726` (production has since moved to `225ed15d0`).
  `mergeable: false` (**dirty** — conflicts).
* 6 of its 8 files differ from production, and **production's versions are the
  newer ones.** Concretely, the PR's `AGENTS.md` replaces the free-model-pool
  section with an older "Project Authority" table; its `README.md` reverts the
  canonical-branch and map-of-record statements; its `docs/KNOWN_LIMITATIONS.md`
  removes the GAP-026 and CARLA-import paragraphs production now carries.
* The 2 files it adds — `docs/engineering/WORKTREE_HYGIENE.md` and
  `docs/engineering/TEST_COVERAGE_GAPS_20260925.md` — are **still absent from
  production**.

**Recommendation: CLOSE as superseded.** Merging it as-is would *revert*
production's newer `AGENTS.md`, `README.md` and `docs/KNOWN_LIMITATIONS.md`.

**Optional follow-up (owner's call):** the two `docs/engineering/` files it
introduces are still missing from production and may still be wanted. If so,
open a **fresh** PR against the current production head that adds only those
two files. Do not resurrect #4 — it is a 2026-09-25 snapshot.

### #6, #7, #8 — Dependabot major-version bumps to `actions/*@v7`

* All three target `main` @ `fa1116ef1` and edit exactly one file:
  `.github/workflows/carla-map-quality-toolkit-ci.yml`.
* **That file does not exist on the production lineage at all** (verified by
  exit code). The production workflows are `.github/workflows/tests.yml` and
  `.github/workflows/carla-runtime.yml`.
* The bumps move `actions/checkout@v4 → @v7`, `actions/upload-artifact@v4 → @v7`
  and `actions/setup-python@v5 → @v7` — **unpinned major-version tags**.

**Recommendation: CLOSE all three.** Two independent reasons:

1. They edit a file outside the governed lineage, from a base 1302 commits
   behind production.
2. **They are a supply-chain regression against the repository's own policy.**
   PR #41's audit (finding R28) requires every action reference to be a full
   40-character commit SHA. Moving to `@v7` is the opposite of that, and the
   production workflows are already fully SHA-pinned (all 19 refs verified
   mechanically — see the P2/P1 work on PR #41).

### #9 — Dependabot `mypy` bump

* Targets `main`; edits `pyproject.toml`, which **does** exist on production.
* Production already requires **`mypy>=1.19`**. The PR proposes
  **`mypy>=1.13,<3`**.

**Recommendation: CLOSE.** This is not merely superseded — merging it would
**relax** a pin that production has since tightened. The correct action is
none.

### #10 — Session closure 2026-10-07/08

* Base production @ `68868f763` (moved on to `225ed15d0`). `mergeable: true`
  (`unstable`). One added file:
  `reports/production_readiness/20260918T000000Z_PRODUCTION_CLOSURE/SESSION_CLOSURE_20261008.md`
  (155 lines). It is **still absent from production**.
* It has **8 review comments, all unresolved**, and 3 review verdicts
  (1 `APPROVED`, 2 `COMMENTED`). The findings are substantive, not cosmetic:

| Severity | Finding |
|---|---|
| **P1** | The gap rollup (47 issues, "updated 2026-10-08") contradicts the checked-in `MASTER_GAP_REGISTER.json` in the same directory, whose `last_updated_utc` is **`2026-09-30T11:38:03Z`** (verified on production). |
| **P1** | The X2 experiment evidence (a 7.9-hour run, a 10,556-lane failure measurement and the resulting RQ1 status) is *reported* but the evidence is not preserved. |
| P2 | The committed file literally ends with `...[truncated 447 chars]`, leaving the PR target statement incomplete. |
| P2 | The worktree inventory totals 27 entries against a claimed 29 — two live worktrees are unaccounted for. |
| P2 | The production-exposure duration is inferred from commit timestamps (63 minutes apart), which does not establish the claim. |
| P2 | The CI failure is diagnosed from exit code 2, which pytest defines as *interrupted*, not *failed*. |
| Medium | The same gap-register mismatch as the P1. |

**Recommendation: REWORK and RETARGET — do not merge as-is, and do not close
without a decision.** This is a *closure* document, so it is squarely in the
terminal/acceptance authority the owner holds. Two specific hazards:

* it would land **next to** `MASTER_GAP_REGISTER.json` and contradict it, in
  the production closure evidence tree;
* it publishes a truncated file and an unpreserved-experiment claim.

**Owner decision required:** either (a) fix the 8 findings and open a fresh PR
against the current production head, or (b) close it and re-derive the closure
from current evidence. **Do not merge.**

### #17, #22, #23 — the gh-aw CI Failure Investigator (a stacked trio)

* **#17** `hardening/ci-failure-investigator-v1` @ `6900bd204` → base
  `integration/post-pr16-final-20261102` @ `1a36b560a` (an ancestor of
  production, 64 commits behind). Draft, 9 commits, 4 files, +2052 lines:
  `.github/workflows/carla-ci-investigator-compile-check.yml`,
  `.github/workflows/carla-ci-investigator.lock.yml` (1826 lines),
  `.github/workflows/carla-ci-investigator.md`, `docs/ci-investigator-pilot.md`.
  **All four are absent from production.**
* **#22** `fix/hgc-pr17-lockfile-trigger-20261106` → base **#17's head branch**.
  One file, +2 lines: adds `GH_AW_AGENT_FILES: "AGENTS.md"` and
  `include-hidden-files: true` to the compile-check workflow's path triggers,
  so the generated lockfile is validated whenever `AGENTS.md` changes.
* **#23** `fix/hgc-pr17-incomplete-diagnostic-20261106` → base **#17's head
  branch**. Two files, +2/−2: makes the investigator report **INCOMPLETE** when
  the GitHub Actions evidence is unavailable, plus the same `GH_AW_AGENT_FILES`
  addition. Last updated **2026-11-11** — the most recently touched PR in the
  whole backlog.

**Recommendation:**

* **#22 and #23 — RETARGET to production, together with #17.** Both are
  substantive: #22 fixes a *validation-trigger* gap for a file that is tracked
  in production, and #23 is a *fail-closed* correction that matches the
  repository's doctrine exactly ("report INCOMPLETE when the evidence is
  unavailable" is the same principle as `PROBE FAILED` in PR #41 and the
  `UNDECLARED_THRESHOLD` verdict in the P2 fix).
* **#17 — RETARGET to production, but the owner decides first.** It introduces
  a **new CI surface** (a GitHub Agentic Workflows investigator, 1826 lines of
  generated lockfile). Two constraints make this an owner call, not an
  autonomous retarget:
  1. `.github/workflows` is under the C08 `DOC_ONLY_NO_WRITE` restriction, so
     OpenCode proposes rather than writes there;
  2. the production branch currently has **no protection and zero rulesets**
     (V104 P0), so a new CI surface would land with nothing enforcing it.

**Ordering matters.** #22 and #23 are based on **#17's head branch**, not on
production. If #17 is closed, both are orphaned. If #17 is retargeted to
production, #22 and #23 must be rebased onto the *new* production-based #17
head and retargeted with it. **Do not close #17 before deciding on #22/#23.**

### #24 — pin portfolio Actions to immutable SHAs

* Targets `main`; edits `.github/workflows/carla-map-quality-toolkit-ci.yml`,
  which **does not exist on production**.
* Its three pinned SHAs (`actions/checkout@11d5960a…`, `actions/setup-python@a26af69be…`,
  `actions/upload-artifact@ea165f8d…`) are for that off-lineage portfolio file.

**Recommendation: CLOSE.** The *intent* — pinning actions to immutable SHAs —
is **already satisfied on the governed lineage**: PR #41's audit verified
mechanically that all 19 action references in `.github/workflows/tests.yml` and
`.github/workflows/carla-runtime.yml` are already full 40-character commit
SHAs. (This is the same verification that caused the false "36-character ref"
finding on PR #41 to be retracted.) Only the off-lineage portfolio workflow
remains unpinned, and it is not part of the governed lineage.

If the owner wants the portfolio workflow hardened, that is a **new** PR
against `main`, and it must not be merged into production as part of this
backlog cleanup.

### #25 — V21/V22 CARLA hardening and independent verification

* Head `review/v21-consolidation-audit-20261106` @ `dfa6ffff0` → base
  `integration/post-pr16-final-20261102` @ `1a36b560a`. Draft, 19 commits,
  67 files, +8582/−5558. `mergeable: false` (**dirty**).
* **The PR head is already an ancestor of production**, and **59 of its 67
  files are byte-identical on production.** The bulk has landed.
* The **8 files that differ** are the substantive residue:

  ```
  ultimate_pipeline/main_pipeline.py
  ultimate_pipeline/pipeline_stages/stage_05_geometry.py
  ultimate_pipeline/pipeline_stages/stage_08_integrity.py
  ultimate_pipeline/quality/map_acceptance.py
  ultimate_pipeline/quality/pipeline_health_summary.py
  tools/verify_import_authority.py
  tests/unit/test_single_writer_arbitration.py
  tests/unit/test_verify_import_authority.py
  ```

  In every case the production version is the **newer** one.

**Recommendation: CLOSE the PR; re-derive the 8 residual files on the current
production head, by their owners.** Merging #25 would **revert** production's
newer `main_pipeline.py`, `map_acceptance.py` and the two stage files.

**This must not be actioned by OpenCode.** `main_pipeline.py` and
`quality/map_acceptance.py` are release-authority files (Codex's exclusive
ownership), and `stage_05_geometry.py` / `stage_08_integrity.py` sit in
Chat-4/Codex territory. The correct action is to tell the owner *"these 8
files still need re-derivation on the current production head; here is the
exact residual"* and let the owner route them.

### #26 — independent V23 source/CI findings and Codex/OpenCode remediation handoff

* Head `audit/independent-source-20261107` @ `5fb0defc3` → base **#25's head
  branch**. 4 commits, 4 files, +509 lines, all documentation:
  `reports/independent_review/2026-11-07/00_INDEPENDENT_AUDIT.md`,
  `01_CODEX_EXECUTION.md`, `02_OPENCODE_EXECUTION.md`, `README.md`.
* **All four are absent from production** (the sibling directory
  `reports/independent_review/V22_FINAL_HANDOFF/` *is* on production).

**Recommendation: RETARGET to production** — the highest-value item in the
backlog, because `02_OPENCODE_EXECUTION.md` is the remediation brief that the
V103/V104 work answered, and the V23 audit is the independent finding set it
answers.

**Two conditions, both owner's call:**

1. It is **stacked on #25**, so #25's disposition must be decided first
   (closing #25 orphans #26 unless #26 is re-based onto production).
2. It was written 2026-11-06/07, **before** the V103/V104 work. Its "open
   issue" lists will be stale. It must be re-dated and re-verified against
   current evidence before it lands, or it will publish a contradictory status
   into the production evidence tree — the same failure mode as #10.

---

## 5. Recommended order of operations

Nothing below is executed by this document. It is the sequence the owner
should follow.

1. **Close, no further work:** #1, #4, #6, #7, #8, #9, #24.
2. **Close #25**, but first record its 8-file residual for the file owners.
3. **Re-base #26 onto production**, re-date and re-verify it, then retarget.
4. **Decide #17** (is the gh-aw pilot still wanted?). If yes: re-base #17 onto
   production, then re-base #22 and #23 onto the new #17 head and retarget all
   three. If no: close #17, then close #22 and #23.
5. **Decide #10** — rework against the current production head, or close and
   re-derive. It is a closure/acceptance document, so it needs the owner.
6. **Optional:** a fresh PR for the two `docs/engineering/` files that #4
   introduced and production still lacks.
7. **Separate, not part of this backlog:** a fresh PR against `main` for the
   portfolio workflow (`carla-map-quality-toolkit-ci.yml`), if the owner wants
   it SHA-pinned. It must not be merged into production.

---

## 6. What this document does NOT do

* It closes nothing, retargets nothing, merges nothing and edits no PR.
* It does not assert that any backlog PR is *correct* — only that it is
  **superseded**, **stacked on a stale base**, **outside the governed
  lineage**, or **carrying unresolved findings**.
* It does not treat "the file already exists on production" as proof of
  supersession. Where a file is *new* on production and merely *similar*
  (e.g. #4's `AGENTS.md`), the recommendation is CLOSE **and** an explicit
  note that a fresh PR may be wanted for the genuinely-new content.
* It does not propose a threshold, a map, or a scientific claim.

---

## 7. Reproduction

```powershell
py C:\Users\admin\AppData\Local\Temp\opencode\_v104_p5_probe.py        # PR inventory
py C:\Users\admin\AppData\Local\Temp\opencode\_v104_p5_collect.py      # per-PR API evidence
py C:\Users\admin\AppData\Local\Temp\opencode\_v104_p5_files.py        # paginated file lists
py C:\Users\admin\AppData\Local\Temp\opencode\_v104_p5_full.py         # per-file blob comparison
py C:\Users\admin\AppData\Local\Temp\opencode\_v104_p5_corrected.py    # corrected existence check
py C:\Users\admin\AppData\Local\Temp\opencode\_v104_p5_git.py          # lineage ancestry
```

Production SHA at the time of the analysis:
`225ed15d0da6444cc257835ca777aba281553f3c` (unchanged throughout).
