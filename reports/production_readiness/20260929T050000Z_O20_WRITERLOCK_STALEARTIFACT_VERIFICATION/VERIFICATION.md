# O20 WriterLock Adversarial / Stale-Artifact / Failure-Recovery Verification

Independent verification, adversarial stance. Worktree: G:/verify-writerlock-20260929,
detached at a189c1e6 (origin/o20-failure-recovery-resume-audit). All commands run with
`python -m pytest -p no:cacheprovider`, never a manual path list.

## 1. WriterLock adversarial harness — NOT consistently green

`tests/unit/test_writer_lock_adversarial.py` was run as a full file 3 separate times.

Run 1: 5 passed, 3 failed (509s)
Run 2: 5 passed, 3 failed (500s)
Run 3: 4 passed, 4 failed (106s) -- includes ALL 3 of the above plus one extra

The 3 failures in every run are deterministic and 100% reproducible:

- test_scenario_6_7_malformed_and_zero_byte_lock_fail_closed: raises raw
  json.decoder.JSONDecodeError instead of the RuntimeError the test (and callers) expect.
- test_scenario_6_killed_during_publication_leave_partial_lock_fail_closed (created-window
  case): outcome "error" (raw exception) instead of "blocked" (controlled RuntimeError).
- test_scenario_5_delayed_publication_has_no_uncaught_json_race: probe hit thousands of
  raw uncaught exceptions during the widened publish window instead of the expected
  controlled "unparseable" RuntimeError (e.g. run1: raw=2053, held_by=337, unparseable=0).

Root cause (confirmed by direct read of the current ultimate_pipeline/contracts/writer_lock.py
on this branch): `WriterLock.load()` has no try/except around `json.loads()`/`cls.from_dict()`.
`acquire()`'s FileExistsError branch calls `cls.load(lock_path)` on the pre-existing file and
only catches FileNotFoundError -- a corrupt/malformed/zero-byte/torn lock file makes raw
JSONDecodeError/UnicodeDecodeError/TypeError leak straight out of `acquire()`, uncaught.

## 2. Comparing the 4 timestamped report directories — the story explains itself, and it's bad news

- 20260924T121927Z: full pass claimed, `delayed_publication_probe` shows
  `{"unparseable": 1540, "held_by": 379}, "raw": []` -- i.e. it was GREEN at the time, using
  error message "... is unparseable/corrupt (JSONDecodeError); failing closed ..." This exact
  string does NOT exist anywhere in this repo's git history on any branch (`git log --all -S`
  confirms zero hits) -- it only ever existed as an uncommitted working-tree edit.
- 20260924T123000Z: killed_during_publication_* and delayed_publication_probe entries are
  MISSING entirely; contention_16 has a round error ("worker failed to signal ready" -- Event
  timeout, infra flake). Looks like a partial/interrupted run.
- 20260924T124000Z: only 4 lines -- a focused rerun of exactly the scenarios missing/failing
  above (5, 6, 7), all green again.
- 20260924T124500Z (has README.md): full clean rerun, all 12 scenarios PASS, explicitly claims
  a "Production defect found and repaired" in `WriterLock.load()`, and contains a "Note on
  worktree volatility": "an external process restored several tracked files to HEAD (including
  the writer_lock.py repair ...), which produced one transient harness failure. The repair was
  re-applied and the affected scenarios re-verified."

So yes -- these are 4 successive attempts investigating and (they believed) fixing a real bug,
exactly as suspected. But the fix never actually landed on this branch. `git log --all -S"unparseable/corrupt"`
finds nothing; the real analogous fix is commit `1bc93eef` "fix(writer-lock): bounded
fresh-publication re-read for partial O_EXCL publishes (GAP-028)", dated the same day
(2026-09-24 11:54, right before the 12:40/12:45 reports). `git merge-base --is-ancestor 1bc93eef
a189c1e6` returns false: **that commit is NOT an ancestor of o20-failure-recovery-resume-audit**.
It lives on `docs/phase4-writerlock-adversarial-review-20260924`,
`fix/ci-closure-blender-writerlock-20260924`, and `origin/integration/production-large-map-20260918`
(so the fix is real and already in the authoritative integration branch), but was never
merged/cherry-picked into the O20 branch under audit here. The checkpoint commit
(a189c1e6) bundled the adversarial test files and the "PASS" report artifacts from that
campaign without the production fix those reports depend on -- so the branch under review
currently ships tests that assert behavior its own committed code does not implement.

## 3. Stale-artifact injection (B4) — confirmed, independently reproduced

`tests/quality/test_stale_artifact_injection.py`: 20/20 passed on a fresh run, matching
`reports/post_audit_hardening/B4_STALE_ARTIFACT_INJECTION.md` exactly. The test design is
sound: distinct-sha256 maps A (stale, newer mtime) / B (registered), planted in every
plausible discovery path, and it honestly separates governed paths (map_registry.verify_pinned_map,
cook offset source, Import staging/validation, tile FBX provenance -- all content-addressed,
fail closed on drift, PASS) from two explicitly NON-governed paths
(`settings._resolve_input_xodr_with_fallback`, `artifact_locator._newest_final_xodr`) that are
still mtime-tiebreak vulnerable and are deliberately pinned as characterization tests, not
silently claimed fixed. It also surfaced a real, separate compile-time defect:
`scripts/cook_full_grid_tiles.py` cannot be imported because `verify_pinned_map()`'s receipt
omits `rebase_dx`/`rebase_dy` that `_header_offset_from_registry` needs -- fails closed (blocks
the whole full-grid cook), not silent. No conflicting parallel stale-artifact work was found in
memory; this is independent, consistent, and credible.

## 4. Failure-recovery matrix (B6) — real for 4/7 rows, superficial for 2/7, and misnamed

`tests/quality/test_failure_recovery_campaign.py` -> `tests/quality/_b6_failure_injection.py`:
1/1 passed, matches `B6_FAILURE_RECOVERY_MATRIX.md`'s 7/7 PASS claim exactly.

Substantive (real fault injection against a real production gate):
- XODR write: corrupts declared_size post-write -> IdentityVerificationError. Real.
- Geometry freeze: mutates XODR after compute_freeze() -> GeometryFreezeError. Real.
- Candidate promotion: builds a real ArtifactStore/PromotionEngine, mismatched parent hash ->
  PromotionError. Real.
- FBX/import-package staging: missing XODR -> staging fails closed. Real, simple.

Superficial / mislabeled:
- "Enrichment": asserts that appending a comment to text produces different bytes than the
  original. This is tautological -- it can never fail regardless of whether any recovery/error
  handling exists, and it doesn't inject a fault into anything.
- "Tiles": asserts that assigning zero buildings produces zero tiles. A degenerate-input
  invariant check, not a fault injection or recovery scenario.
- "Registry update / invalid role": a real input-validation check, but it's validation, not a
  failure-injection-then-recovery scenario either.

More importantly: **none of the 7 rows test recovery** (resuming/retrying/continuing after a
failure) -- every row tests fail-closed detection only (does the fault get rejected). Given the
campaign's own name is "O20: failure recovery resume audit," this is a real scope gap: the
artifact is titled and reported as a "Failure Recovery Matrix" but doesn't exercise any resume
or retry path.

## 5. WriterLock stress retest (extra verification beyond the 3 required runs)

Run 3 above also produced a 4th failure: `test_scenario_1_2_8_16_simultaneous_processes_and_50_rounds`
failed at the 2-way level with `rounds_with_multi_winners == 1` (out of 50) -- i.e., two
concurrent processes both reported `WriterLock.acquire()` succeeding in the same round. This is
exactly the class of bug GAP-024 claims to have fixed (O_CREAT|O_EXCL as sole arbiter). Given
the instruction to never dismiss a single failure as flaky, this was stress-retested in
isolation: `WRITER_LOCK_ADVERSARIAL_ROUNDS=100` against just that one test (300 total rounds
across 2/8/16-way) ran clean -- exactly one winner every round, 0 errors, 16m56s. Across all
runs combined this session, the multi-winner event occurred exactly once in ~250 2-way rounds
(~0.4%) and did not reproduce in a dedicated 300-round retest. This does not disprove a rare
race exists, but O_CREAT|O_EXCL is a single atomic syscall and a genuine violation of it would
be a serious platform-level finding; the far more likely explanation, given system load varied
enormously during this session (worktree checkouts elsewhere on the same disk took 10-20x
longer than normal due to concurrent subagents, and the anomaly's run had a much shorter total
runtime than the other two full-file runs, consistent with a moment of extreme scheduling
variance), is test-harness/OS-scheduling flakiness under contention rather than a logic defect
in acquire() itself. Flagged as unresolved-but-probably-benign rather than dismissed.

## 6. Full bare pytest suite integration — does NOT integrate cleanly

First, a genuinely bare `pytest` invocation (no flags) in a fresh worktree checkout of this
branch: **collects zero tests and aborts**. `collected 6383 items / 1 error` /
`Interrupted: 1 error during collection`. `tests/unit/test_full_grid_tile_cook.py` imports
`scripts/cook_full_grid_tiles.py` at module scope, which raises `ValueError: Registry entry
'auto_map_of_record' is missing structured frame fields 'rebase_dx' / 'rebase_dy'` while
building `HEADER_OFFSET_XY` at import time -- this is the exact defect B4 already found and
explicitly chose not to fix ("Bounded fix (proposed, not applied on this pass)"), but B4
characterized its blast radius as "blocks the full-grid-tile cook." In reality it blocks
**the entire bare pytest suite from collecting at all**. Reproduced identically outside the
worktree, directly in the main repo at the same commit -- not a worktree artifact.

Re-run with `--continue-on-collection-errors` to see past it:

**8 failed, 6360 passed, 6 skipped, 10 errors, 180 warnings in 1612.82s (26m52s)**

- 3 of the 8 failures are the same 3 deterministic writer_lock_adversarial failures from
  section 1 (4th independent reproduction; the rare multi-winner flake from run 3 did NOT
  recur here).
- 1 collection error + 9 more setup-time errors, all in
  `tests/unit/test_a1_a2_path_and_frame_resolution.py::TestRegistryFrameAuthority::*` and
  `TestPortablePathResolution::*` (8 ERROR) plus 4 more FAILED in the same file -- all trace
  to the identical `rebase_dx`/`rebase_dy` missing-structured-frame-fields root cause
  (`KeyError: 'rebase_dx'`, same `ValueError` text). This is one pre-existing production bug
  with a MUCH larger blast radius than B4's report captured: 1 full collection abort + 12
  test failures/errors in test_a1_a2_path_and_frame_resolution.py alone, not just "blocks the
  cook script."
- `tests/unit/test_offline_cooking_pipeline_integration.py::...::test_tile_fbx_generation_feeds_real_package_staging_and_validation`
  FAILED: "tile provenance check failed ... tile manifest ... has no
  source_provenance.map_of_record_sha256" -- plausibly the same receipt/manifest-field-gap
  bug family, not independently confirmed as identical root cause.
- `tests/unit/test_a1_a2_path_and_frame_resolution.py::TestPortablePathResolution::test_find_carla_root_env_without_exe`
  and `test_find_carla_server_env_precedence` FAILED on environment leakage: the test expects
  an isolated tmp path but observed `E:\CARLA\CARLA_0.9.16` -- this machine's real
  CARLA_ROOT/env state leaking into a test that assumes a clean environment. Pre-existing
  test-isolation bug, unrelated to O20.

**Verdict on integration**: none of these 10 non-writer-lock failures/errors were introduced
by the three new O20 test files under review (test_writer_lock_adversarial.py,
test_stale_artifact_injection.py, test_failure_recovery_campaign.py) -- they all trace to a
single pre-existing registry defect this same campaign already found (B4) and explicitly
deferred fixing, or to pre-existing environment leakage. No naming collisions or fixture
conflicts were observed from the new files themselves. But the literal claim "integrates
cleanly" is false: a bare `pytest` run on this branch right now produces zero results, and
`--continue-on-collection-errors` is required just to see that 6360/6374 executed tests pass.
This is a **shippability blocker** independent of anything about WriterLock, stale-artifact,
or failure-recovery: this branch cannot be validated by CI today with a standard bare
`pytest` invocation.
