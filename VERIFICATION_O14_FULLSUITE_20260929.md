# Independent verification: O14 clean-clone audit, BRANCH_ARCHIVAL_PLAN.md, AGENTS.md diff, full bare pytest suite

Branch under review: `o20-failure-recovery-resume-audit` @ `a189c1e6` (the checkpoint commit that
protectively committed O1-O20 plus uncommitted evidence found after a session restart; the
checkpoint's own message states "None of this has been independently reviewed/verified by the
coordinator yet"). This document is that independent review.

Method: all checks below were run from a **genuinely fresh, isolated** `git worktree add --detach
origin/o20-failure-recovery-resume-audit` at `G:\worktrees\o20-verify-o14fullsuite-20260929` (not
the pre-existing dev checkout), fetched fresh from origin. No manual pytest path lists were used;
the full bare `pytest` invocation always relies on `pytest.ini`'s 12 `testpaths` entries.

## 1. O14 ("clean clone offline onboarding audit", commit `dbc70314`) — findings + independent re-verification

**What O14 did.** `tools/clean_clone_offline_audit.py` (added by `dbc70314`) runs 5 checks against
`Path.cwd()`: `git_default_branch`, `git_lineage`, `python_import` (`import ultimate_pipeline`),
`map_registry` (`verify_pinned_map('auto_map_of_record')`), and `git_lfs` (a **presence-only**
check: if `.gitattributes` contains `filter=lfs` at all, the check is unconditionally marked
`INCOMPLETE` — it never actually tests whether LFS smudging works).

**What O14 found.** Its own recorded result (`CLEAN_CLONE_OFFLINE_AUDIT.json`) is
`"status": "INCOMPLETE"` — 4/5 checks PASS, `git_lfs` INCOMPLETE by design. Critically, O14's own
`limitations` field says: *"A current checkout audit cannot prove a fresh clone unless
--clone-root points to one."* It was run with `--clone-root` defaulting to
`Path.cwd()` = the pre-existing dev checkout (`C:\Users\admin\...\carla_-main`), **not a real
fresh clone** — so its own PASS results for `python_import` and `map_registry` are not proof that
onboarding works for a new contributor; only that the already-set-up dev machine works.

**Independent re-verification (this session, from the fresh worktree):**

- **Production-branch discovery: FAILS.** `git remote show origin` reports `HEAD branch: main`,
  i.e. a plain `git clone <url>` lands a new contributor on `main`. But `origin/main` (and local
  `main`) is a single-commit stub (`e0aa1aab "Initial commit"`, README.md + .gitignore only) —
  confirmed **not an ancestor** of any real work (`git merge-base --is-ancestor origin/main
  origin/integration/production-large-map-20260918` → not an ancestor). The actual production tip
  is `integration/production-large-map-20260918` (confirmed via `CHANGELOG.md`'s own text, and
  because the task's 6264/6/0 baseline report commit `cfa39372` lives there). **A fresh clone does
  not discover the production branch.**
- **`map_registry` resolution: genuinely works, more rigorously confirmed than O14's own check.**
  `verify_pinned_map('auto_map_of_record')` was run under a **completely unrelated, bare system
  Python 3.14.5** (`py -3`, zero packages beyond stdlib — no numpy, no pyproj) from the fresh
  worktree and returned the correct sha256 (`370abbbb...`, matching the pinned map-of-record).
  This is stronger evidence than O14's own check (which only ran inside the pre-populated dev
  `.venv`).
- **`python_import`: also genuinely works with zero setup** (same bare-Python test); confirmed
  `ultimate_pipeline/__init__.py` does nothing heavier than a `sys.path` append, so it imports
  without requiring `pip install` first.
- **Offline smoke test: O14 never actually ran one** (no such step exists in its script). O14's
  own unit test (`tests/unit/test_o14_clean_clone_offline_audit.py`) passes in isolation (2
  passed), but that only tests the audit script's internal contract, not a real pipeline smoke
  test.
- **git-lfs: a real, undocumented onboarding gap.** 62 LFS-tracked files (including the 149 MB
  map-of-record `.xodr`) smudged correctly in the fresh worktree — but only because this
  workstation already has git-lfs installed/configured. `README.md` documents **no** `git lfs
  install` step anywhere (grepped for "lfs" and "clone" — zero hits). A genuinely new contributor
  without git-lfs preconfigured would get unusable pointer-stub files, and nothing in the docs
  would warn them. O14's own `git_lfs` check can never discriminate broken-from-working (see
  above), so it would not catch this either way.
- **Hidden workstation-specific paths: confirmed present, and one is actively dangerous.**
  `ultimate_pipeline/config/settings.py:616-617` hardcodes
  `r"E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"` as a fallback default (env-override-first, so inert by
  itself). Far more seriously: `scripts/find_carla_server.py`'s `COMMON_CARLA_PATHS` list of
  hardcoded common install locations is **live-fired** by an inadequately-mocked test — see §4/§5,
  this actually launched the real CARLA simulator during this verification and it is still running
  as of this writing.

**Conclusion on O14:** the audit's individual claims for the checks it ran are directionally
correct, but the audit fundamentally never tested what its name promises (a *clean clone*); it
tested the pre-existing dev workspace. Its own honest self-flag (`INCOMPLETE`) undersells the real
problem (branch-discovery failure, undocumented LFS prerequisite, a live CARLA-launch hazard) and
oversells the parts it marked PASS (they happen to be more robust than O14 itself proved, per this
session's independent bare-Python re-check, but O14 gets no credit for that — it never tried).

## 2. `docs/archive/BRANCH_ARCHIVAL_PLAN.md` — proposal + spot-check

**Proposal:** archive 3 branches (tag first, delete only after approval — explicit "do NOT delete
until reviewed" policy): `main` (Historical/Disconnected → "point to
integration/production-large-map-20260918"), `fix/post-audit-phase-e-junctions-roundabouts-20260803`
(Superseded), `stabilize/research-release-20260905` (Divergent).

**Spot-check (via `git merge-base --is-ancestor`, this session's own established discipline),
all 3 claims:**

1. **`main`** — confirmed **not** an ancestor of `integration/production-large-map-20260918` or of
   this branch's HEAD. Genuinely disconnected/historical. **Claim accurate.**
2. **`fix/post-audit-phase-e-junctions-roundabouts-20260803`** — exists **only as a local branch**
   (not pushed to origin — absent from `git branch -r`). **Is** an ancestor of
   `integration/production-large-map-20260918`. Genuinely fully merged/superseded. **Claim
   accurate**, though the plan's "remote branches can be safely deleted" execution step doesn't
   literally apply since this was never pushed.
3. **`stabilize/research-release-20260905`** — also local-only (not on origin). **Is** an ancestor
   of the production tip. Genuinely fully merged. **Claim accurate** despite "Divergent" being an
   odd label for something fully subsumed rather than actually diverged.

All 3 spot-checked claims hold up. The plan is conservative and correct in substance; its only
imprecision is treating local-only branches as if they needed remote deletion.

## 3. `AGENTS.md` diff review

The diff (inside checkpoint commit `a189c1e6`) adds an entirely new "## Project-Specific Rules"
section (all added lines, nothing removed), including:

> Use `main` as the authoritative working branch; feature branches only via PR

**This is false on arrival.** As shown in §1/§2, `origin/main` is a disconnected single-commit
stub, confirmed not an ancestor of any real work. The real production/authoritative branch, per
this session's own `CHANGELOG.md` and the very commit that supplied the task's 6264/6/0 baseline
(`cfa39372`), is `integration/production-large-map-20260918`.

This directly **contradicts `docs/archive/BRANCH_ARCHIVAL_PLAN.md`** — written in the *same*
checkpoint commit — which correctly calls `main` "Historical (Disconnected)" and says to point to
`integration/production-large-map-20260918` instead.

It also conflicts with `README.md`'s own (separately pre-existing, stale since 2026-09-06,
commit `43e643be`) claims: *"Authoritative lineage: `fix/post-audit-phase-e-junctions-roundabouts-20260803`"*
and *"Stabilization branch: `stabilize/research-release-20260905`"* — both of which
`BRANCH_ARCHIVAL_PLAN.md` (again, the same checkpoint) recommends archiving as
superseded/historical.

**Net finding:** within this one checkpoint commit, three different documents assert three
mutually-contradictory answers to "what is the authoritative/production branch": `main` (per the
new AGENTS.md rule), `fix/post-audit-phase-e-...` / `stabilize/research-release-...` (per
README.md, pre-existing staleness never fixed despite a `c49425ab` "sync README" commit inside
this same branch's own O-series work), and `integration/production-large-map-20260918` (per
CHANGELOG.md, BRANCH_ARCHIVAL_PLAN.md, and reality). AGENTS.md's newly-added claim is the most
actively wrong of the three.

The remaining new AGENTS.md rules (resolve map-of-record via registry not mtime/glob, no
GAP-026 tolerance-raising, exact/no-fabricated test reporting, single-writer discipline, etc.) are
consistent with this session's established memory/discipline and not contradicted by anything
found here.

## 4. Full bare `pytest` suite — exact results vs. the 6264/6/0 baseline

**Baseline** (confirmed from `cfa39372`'s `RESULTS.md`, recorded twice, pre- and post-merge, both
identical): `6264 passed, 6 skipped, 0 failed` (6270 collected), exit 0, ~25-29 min wall time, on
`integration/production-large-map-20260918`.

**Run 1 — true bare `pytest`, zero extra flags, from the fresh worktree of this branch's HEAD
(`a189c1e6`):** collection **aborts**. `collected 6383 items / 1 error` →
`Interrupted: 1 error during collection` → **exit non-zero, ZERO tests executed**, in 65.93s.

Root cause: `scripts/cook_full_grid_tiles.py` (module-level code) calls a new helper
`_header_offset_from_registry(_pinned)` (added by **O1**, commit `f7934c13`) that requires
`pin["rebase_dx"]` / `pin["rebase_dy"]` in the dict returned by `verify_pinned_map()`. But
`verify_pinned_map()` in `ultimate_pipeline/carla_tools/map_registry.py` (never touched by O1)
**never returns those keys** — confirmed directly:
`sorted(verify_pinned_map('auto_map_of_record').keys())` has no `rebase_dx`/`rebase_dy`/
`frame_kind`, even though the raw `PINNED_MAP_REGISTRY['auto_map_of_record']` entry *does* define
`rebase_dx: 832671.676, rebase_dy: 5458671.104` (lines 748-749) — they are simply never propagated
into the function's return value (lines 1018-1034). This raises `ValueError` at import time, so
any file importing `cook_full_grid_tiles.py` at module scope (`tests/unit/test_full_grid_tile_cook.py`)
fails to collect, which **aborts the entire bare pytest run** (pytest's default is to interrupt on
a collection error, not continue). **This is a real, 100% deterministic, reproducible regression
introduced by O1** (re-confirmed via direct interpreter checks, twice, identical result).

Notably, `tests/unit/test_a1_a2_path_and_frame_resolution.py` — a file that only ever landed via
this same checkpoint commit, never as part of any individual O-commit — contains a test
(`test_receipt_exposes_structured_frame`) that explicitly asserts this exact contract
(`receipt["rebase_dx"] == KNOWN_DX`, etc.). Someone in this session wrote the regression test for
this contract but never finished the corresponding implementation, and it was swept into the
checkpoint without ever being run to green — exactly matching the checkpoint's own disclaimer.

**Run 2/3 — full bare `pytest` with `--continue-on-collection-errors`** (bypassing only the one
known collection abort, still the full 12-directory `testpaths`), after deselecting exactly one
proven-hazardous test node (see §5):

```
7 failed, 6360 passed, 6 skipped, 1 deselected, 179 warnings, 10 errors in 1796.04s (0:29:56)
```

(6382 selected = 7 failed + 6360 passed + 6 skipped + 9 execution-phase errors; the 10th error is
the collection-time abort from Run 1, counted separately.)

**Comparison to baseline:** 6360 passed vs. 6264 baseline (+96, consistent with O1-O20 adding
~113 new tests net of the 7 broken/deselected ones: collected 6383 here vs. 6270 baseline). 6
skipped matches exactly. But **7 failed + 10 errors here vs. 0 failed + 0 errors in baseline** —
17 non-passing outcomes that do not exist on the production tip, plus the fact that a literal bare
`pytest` invocation (no flags) doesn't get past collection at all.

**Answer to "does this integrate cleanly with zero new failures": No.**

## 5. Investigation of every new failure/error (real regression vs. environment artifact)

Every failure and error was root-caused to source and **independently re-run in isolation** to
confirm determinism (per this session's established discipline) before being called "real."

| # | Test(s) | Root cause | Isolation re-run result |
|---|---|---|---|
| 1 | `test_full_grid_tile_cook.py` (1 collection error) + `test_a1_a2_path_and_frame_resolution.py::TestRegistryFrameAuthority::test_receipt_exposes_structured_frame` + `::test_xodr_header_offset_matches_registry` (2 FAILED) + 7 more `TestRegistryFrameAuthority`/`TestPortablePathResolution` tests that use the `cook_mod`/`probe_mod` fixtures (7 ERROR) | **O1's `_header_offset_from_registry()` requires `rebase_dx`/`rebase_dy` in `verify_pinned_map()`'s return dict; `map_registry.py` was never updated to actually return them.** Real, deterministic. | Re-confirmed via direct interpreter check, twice, identical `KeyError`. |
| 2 | `test_a1_a2_path_and_frame_resolution.py::TestPortablePathResolution::test_find_carla_server_env_precedence` | **`scripts/find_carla_server.py` has zero `CARLA_EXE`/env-var override support** (confirmed by reading the full source — it only scans a hardcoded `COMMON_CARLA_PATHS` list); the test asserts a contract ("env var > portable default") that was simply never implemented. Real, deterministic. | Re-run alone: `1 failed in 1.35s`, identical `AssertionError: assert None == ...`. |
| 3 | `test_offline_cooking_pipeline_integration.py::TestOfflineCookingPipelineChain::test_tile_fbx_generation_feeds_real_package_staging_and_validation` | **Genuine regression on a pre-existing production-tip test** (confirmed present on `integration/production-large-map-20260918`, last touched well before O1). O1's new provenance-chain validation now requires `source_provenance.map_of_record_sha256` in tile manifests, but the tile-generation producer code this test exercises was never updated to populate that field. Real, deterministic. | Re-run alone: `1 failed in 1.77s`, identical `AssertionError`. |
| 4-6 | `test_writer_lock_adversarial.py::test_scenario_6_killed_during_publication_leave_partial_lock_fail_closed`, `::test_scenario_5_delayed_publication_has_no_uncaught_json_race`, `::test_scenario_6_7_malformed_and_zero_byte_lock_fail_closed` | **A net-new, never-run-to-green test file** (only ever landed via this checkpoint commit; absent from the production tip entirely — the "writer-lock adversarial test suite" the checkpoint commit message itself flags as unreviewed). Three independent real bugs in `ultimate_pipeline/contracts/writer_lock.py`: (a) a killed-during-publication acquire returns `"error"` instead of the intended fail-closed `"blocked"`; (b) `WriterLock.load()` does not catch `json.decoder.JSONDecodeError`, so a malformed/corrupt lock file crashes instead of failing closed; (c) the adversarial probe's "widened empty-publish window" is never actually observed (0 `unparseable` reads) — reproduced with different raw sample counts across two independent runs (330/2160 and 352/1790) but the same qualitative zero outcome both times, indicating a real logic/timing defect, not incidental flakiness. | Each re-run alone, fresh `tmp_path` each time: scenario_6 → `1 failed in 4.99s` (identical `'error' != 'blocked'`); scenario_5 → `1 failed in 10.67s` (identical `0 > 0`, different but still-zero sample counts); scenario_6_7 → `1 failed in 1.47s` (identical `JSONDecodeError`). All 3/3 deterministic. |

**A sixth, separate and more severe hazard (not in the failure/error counts above because it was
deselected for safety — see below):**

`test_a1_a2_path_and_frame_resolution.py::TestPortablePathResolution::test_find_carla_root_env_without_exe`
calls the **real, unmocked** `scripts/find_carla_server.py:get_carla_root()` → `find_carla_server()`,
which iterates hardcoded `COMMON_CARLA_PATHS` (first entry:
`E:\CARLA\CARLA_0.9.16\CarlaUE4.exe`) and, finding it present on this exact workstation, launches
it via `subprocess.run([p, "--help"], timeout=15)`. The Unreal-Engine executable does not exit
promptly; the real `CarlaUE4-Win64-Shipping.exe` process (PID 26812) was confirmed running via
`Get-Process`, accumulating CPU far past the declared 15s subprocess timeout (300s → 44,500+ CPU-s
and counting, still running ~4 hours later at time of writing) — matching this session's
previously-documented "CONFIRMED LIVELOCK" (see memory: `project_c0_clean_regen_pinned.md`,
`project_rq2_rq5_blocker_root_causes_20260830.md`). The parent pytest process hung and had to be
force-stopped via `TaskStop`. **I was correctly blocked by the permission system from killing the
orphaned CarlaUE4 process myself** ("Interfere With Workloads" — appropriate given other subagents
share this machine); **it remains running and needs manual intervention** (`Stop-Process -Id 26812
-Force` on the host, or a reboot). Root cause: this test's sibling
(`test_find_carla_server_env_precedence`, item #2 above) properly mocks `os.path.exists` and
`subprocess.run`; this test forgot to, so on any machine with real CARLA at a common path, an
"offline"/"unit" test silently launches the actual simulator. A grep across `tests/` and
`ultimate_pipeline/` confirmed this is the *only* test calling `find_carla_server()`/
`get_carla_root()` — the hazard is isolated to this one test, deselected for the Run 2/3 numbers
above via `--deselect`.

**Conclusion for §5:** every single failure, error, and the one livelock hazard is a **real,
independently-confirmed regression or defect introduced by this branch's own new/uncommitted
work** (O1's registry-contract change, O1's provenance-chain enforcement, or the never-verified
writer-lock-adversarial and A1/A2 test files swept into the checkpoint). None were environment or
contention artifacts — all reproduced deterministically in isolation, most within seconds.
