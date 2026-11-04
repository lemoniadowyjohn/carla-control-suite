# Execution backlog after the ARCH-X8-X9 review (2026-11-04)

Order matters. **One writer per branch at a time.** Codex is for investigation-heavy work; OpenCode or
a Claude Sonnet implementer is for small, fully specified work. Every task:
- runs on E:/G:, never H:;
- puts TMP/TEMP and pytest `--basetemp` on the output drive;
- does not push, merge or start CARLA;
- shows the failing test before the fix;
- gets an independent reviewer from a different model family.

| ID | Owner | Depends on | Size |
|---|---|---|---|
| C0 | operator (+ Codex for the manifest) | disk | S |
| C1 | Codex | — | M |
| O13 | OpenCode / Sonnet | — (can run in parallel with C1 on a different branch) | S |
| C2 (= X8) | Codex | C1 reviewed, O13 merged, ≥ 15 GB free | L |
| C3 (= X9b part 2) | Codex (running) | — | M |
| C4 (= P0-TC-001) | Codex | — | M |
| O14 | OpenCode / Sonnet | — | S |
| O15 | OpenCode / Sonnet | — | S |
| O16 | OpenCode / Sonnet | C1 + this review accepted | S |

---

## C0 — Archive local evidence inputs (operator decision + Codex)
The stage files of run `reports/rq1_trial_runs/run_01/20261007_214826_524342/` (01: 150 MB; 02, 05,
06 and 07: about 138 MB each) are the only inputs behind the GAP-070/079 numbers, and they are
untracked.
- **Operator:** choose a store: Git LFS on a dedicated evidence branch, a GitHub release asset, or an
  external archive.
- **Codex:** write `reports/production_readiness/<UTC>_EVIDENCE_INPUT_MANIFEST/manifest.json` with the
  path, sha256 and bytes of every file, and the store URL. Do not modify or move the files.

## C1 — Harden the junction connector snap (Codex) — required before X8
- **Branch:** new `fix/gap070-snap-hardening-20261105` from `2cee039f`, worktree on E: or G:.
- **Only file to change:** `ultimate_pipeline/tools/junction_connector_snap.py`; tests in
  `ultimate_pipeline/tests/unit/test_junction_connector_snap.py` and
  `tests/unit/test_junction_connector_classifier.py`.
- **Do:**
  1. **U-turn exclusion (F-01/F-02).** Before any snap, compute the contactPoint-aware incoming and
     exit poses. If they coincide (≤ 1e-3 m) or the required turn is > 150°, skip with the new counter
     `skipped_uturn_shared_reference`. Apply the same exclusion on the integration snap path; the
     function is shared, so it covers both.
  2. **Heading convention (F-06).** Required start heading = hdg_end(incoming) or hdg_start(incoming)
     + π; required end heading = hdg_start(exit) or hdg_end(exit) + π. Assert both.
  3. **Tangent scaling (F-03).** Tangent magnitude = chord length. Compute the arc length numerically
     with the kernel (≥ 800 samples; confirm convergence against 8,000). If `|arc/length − 1| > 1e-4`,
     **reject the refit and restore**. Do not rescale s-indexed children in this task.
  4. **Displacement guard (F-04).** Re-enable `rechain_guard_m`: skip when the start must move more
     than the guard (`skipped_displacement_exceeds_guard`). Keep the default value, and mark it in the
     docstring as **an unresolved threshold decision**. Do not invent a new value.
  5. **Post-refit gates (F-05).** Reject and restore on any of:
     - a zero-speed point;
     - a non-simple curve (shapely `is_simple`);
     - endpoint position > 1e-6 m;
     - heading > 1e-6 rad;
     - peak curvature > the original connector's peak (conservative default; the factor stays an
       operator decision).
     Count each reason separately.
- **Tests (failing first, one per item):**
  - a synthetic shared-reference U-turn (snapped 0, skipped_uturn 1, planView byte-identical);
  - the real fixture connector 51810 with its roads 47570 and 42130;
  - the stretched case 68739 (3 m road, 8 m move), which must be rejected or guarded;
  - a flipped-contactPoint case;
  - a synthetic cusp and a synthetic loop.
- **Measure in memory** on `05_planview…` (sha256 `45c52059…`) with `x7_geom_audit.py` from
  `docs/reviews/ARCH_X8_X9_20261104/evidence/`, extended with the new counters. Report:
  - refits, skips by reason, and kinks > 30°;
  - cusps / non-simple / arc-ratio violations (all must be 0);
  - radius < 2 m before vs after.
- **Commit; do not merge.**

## O13 — Connector curve-invariant checker, report-only (OpenCode / Sonnet)
- **New files only:** `tools/check_connector_curve_invariants.py` and
  `tests/unit/test_check_connector_curve_invariants.py`.
- **CLI:** `--xodr <path> --out <json>`. For every road with `junction != -1`, sample each geometry
  with `opendrive_geometry_kernel.pose_at_s`. Report per road:
  - arc length vs `@length`;
  - min speed (paramPoly3 analytic derivative; otherwise from kernel finite differences);
  - simplicity (shapely);
  - peak curvature;
  - endpoint poses.
  Add a summary with counts above the review's thresholds. **Exit code 0 always** (report-only).
- **Tests:** a line, an arc, a paramPoly3 needle (bU = L, cU = −L), a stretched paramPoly3 (length 3,
  chord 10), and a self-intersecting cubic. Assert each flag.
- Used by C1 and C2.

## C2 — X8 governed regeneration (Codex)
See `GAP070_X8_VERIFICATION_PLAN.md`: arms C (snap off), A (merged snap) and B1/B2 (C1). Use the full
metric table, the per-connector comparison, determinism, and an independent recomputation.
**No promotion.**

## C3 — X9b part 2 (Codex; already running at `06a31ed1`)
Add steps E (road-ID remapping, neighbour preservation) and F (U-turn cross-reference) from
`GAP079_X9B_INVESTIGATION_PLAN.md` to the current run. Use the same per-step checkpoint commits.

## C4 — P0-TC-001 terminal release authority (Codex; work in progress)
Finish the tests the reviewer asked for (see `RELEASE_SAFETY_REVIEW_CHECKLIST.md` §A): FAIL/INCOMPLETE,
terminal-status write failure, post-publication revocation, restart, concurrent reader. Then commit on
its own branch and get an independent review.

## O14 — Crop sampling fallback must fail closed (OpenCode / Sonnet)
- **Files:** `ultimate_pipeline/domain_gap/footprint_crop.py` and
  `tools/rq3_crop_auto_to_manual_footprint.py` (the hard_checks dict at `:206-214`), plus their tests.
- **Change:** add the hard check `zero_sampling_fallbacks` (`sampling_fallback_count == 0`). Status is
  PASS only if it holds. Update the docstring of `:217-223` to say the fallback can drop coverage, so
  it is now fatal.
- **Test first:** a road with an unsupported primitive crossing the footprint, with its anchor
  outside, gives status FAIL.
- Re-run `ultimate_pipeline/tests/unit/test_footprint_crop.py`. The real crop has
  `sampling_fallback_count` 0, so its result does not change.

## O15 — Windows CI job (OpenCode / Sonnet)
- **File:** `.github/workflows/tests.yml`.
- **Change:** add a `windows-latest` job running
  `tests/unit/test_single_writer_arbitration.py`, `tests/unit/test_worktree_lock.py`,
  `tests/adversarial/test_terminal_authority.py`, the atomic `write_xodr` tests and
  `tests/unit/test_validation_report_call_order.py`.
- In the job, print the count of collected and skipped tests, and fail it if
  `test_single_writer_arbitration.py` reports 0 tests run.
- Push only as part of the integration branch, after operator approval.

## O16 — Gap register addendum 3 (OpenCode / Sonnet; after this review is accepted)
> **Superseded 2026-11-04:** the GAP numbers below were never registered. The proposed addendum 3 (`docs/reviews/SCI_CORRECT003_20261104/`) allocates GAP-080 to the U-turn lane-level defect. Any of the items below that are adopted later need new ids.
- **New directory:** `reports/production_readiness/<UTC>_GAP_REGISTER_ADDENDUM_3/`. Do not edit
  addenda 1 or 2.
- **GAP-070 evidence update:** the ~53° kinks are the 3,375 shared-reference U-turn connectors. The
  candidate `2cee039f` collapses them into degenerate curves (review F-01), so its status stays OPEN.
- **New entries:**
  - GAP-080: candidate refit `@length` ≠ arc length (F-03);
  - GAP-081: unbounded snap displacement (F-04);
  - GAP-082: no lane-level continuity metric (F-08);
  - GAP-083: crop sampling fallback not fatal (closed by O14 when done);
  - GAP-084: Windows-only tests are never run in CI (closed by O15 when done).
- Cite `docs/reviews/ARCH_X8_X9_20261104/`, committed first, or with its evidence hashes.
