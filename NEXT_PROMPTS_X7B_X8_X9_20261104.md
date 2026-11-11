# Next prompts — 2026-11-04 (after X7)

## State verified by Claude (2026-11-04)

- **X7** (`fix/gap070-connector-snap-exit-20261103` @ `03aaccd4`, worktree `E:/wt/fix-gap070-connector-snap-exit-20261103`):
  - Re-measured independently on `05_planview` (sha256 `45c52059…`, unchanged), all numbers reproduce:
    entry start mismatches 4,092 → 67, entry end mismatches 4,043 → 560, exit heading kinks
    351 → 349, ~53° bucket 4 → 4, geometry gaps 0 → 0, 4,025 refits, 0 residuals.
  - **But 2 tests regressed and were not in Codex's "27 passed" run.** In
    `tests/unit/test_junction_connector_classifier.py`,
    `test_snap_classifies_unambiguous_displaced_inferred_and_snaps` and
    `test_snap_allows_ambiguous_when_opted_in` pass before X7 and fail after it (`connectors_snapped`
    0 ≠ 1).
  - Cause: their fixtures have no exit road, and X7 now correctly fails closed on a missing exit
    anchor. Fix the tests, not the code (prompt X7b).
  - X7 does not change the default flag, but the snap is default ON, so **merging X7 changes the
    geometry of every future regeneration.** Merge it only after X7b and X8.
- **Disk:**
  - C: 2 GB, E: 2.1 GB, F: 2.2 GB free.
  - The external USB drives are D (8.4 GB, personal data), G (5.1 GB), H (12.3 GB, QUARANTINED, do
    not use) and I (10.2 GB, personal data).
  - G holds nine orphaned September worktree copies (~3.9 GB each, ~35 GB total; their git metadata
    is already pruned), `carla_map_regen_out` (8.7 GB) and `carla-artifact-archive` (15 GB).
  - **Freeing space on G is an operator decision.** X8 needs ≥ 15 GB free on one drive.

---

## X7b — OpenCode (small, fully specified)

```
Single writer under AGENTS.md. Worktree: E:/wt/fix-gap070-connector-snap-exit-20261103, branch
fix/gap070-connector-snap-exit-20261103, HEAD must be 03aaccd4 (verify; abort if tracked files are modified).
Set TMP/TEMP to E:\wt\_x7b; run pytest with -p no:cacheprovider --basetemp=E:/wt/_x7b/bt; delete
E:/wt/_x7b at the end.
FORBIDDEN: push, merge, rebase, reset, stash, checkout; editing ultimate_pipeline/tools/junction_connector_snap.py
or any product code; protocol freeze files; reports/ files; maps; CARLA.
Only `git add <explicit paths>` + one `git commit`.
PROBLEM: X7 made snap_junction_connectors fail closed when a connector has no topology-declared exit
anchor (report key skipped_missing_exit_anchor). Two tests in tests/unit/test_junction_connector_classifier.py
build fixtures with an incoming road and a connector but NO exit road, so they now get
connectors_snapped == 0 instead of 1:
  test_snap_classifies_unambiguous_displaced_inferred_and_snaps
  test_snap_allows_ambiguous_when_opted_in
FIX (tests only; do not weaken any assertion):
1. Read how X7 resolves the exit anchor in junction_connector_snap.py (the connector's road-level
   successor / the junction connection that names the exit road) and the passing X7 tests in
   ultimate_pipeline/tests/unit/test_junction_connector_snap.py for the fixture shape.
2. Give both fixtures an exit road plus the link that declares it, placed where the connector ends,
   so the original intent (classification + snap) is exercised under the new contract. Keep every
   existing assertion.
3. Add one new test: the same fixture WITHOUT an exit road gives connectors_snapped == 0,
   skipped_missing_exit_anchor == 1, and the connector geometry is unchanged byte for byte.
4. Run tests/unit/test_junction_connector_classifier.py, tests/unit/test_stage05_connector_snap_wiring.py
   and ultimate_pipeline/tests/unit/test_junction_connector_snap.py: all must pass.
   Show the 2 failures before the change.
Commit: "test(gap070): classifier fixtures declare the exit road required by the X7 snap".
Return: SHA, before/after test tails.
```
Then send it to the OpenCode `reviewer`: re-run those 3 files and confirm no assertion was removed or loosened.

---

## X8 — Codex: governed candidate regeneration with the X7 snap (needs ≥ 15 GB free; NO promotion)

```
Repo lemoniadowyjohn/carla-control-suite, AGENTS.md rules (L4: map-of-record work → read-only discovery
first, exactly one writer, then an independent reviewer).
PRECONDITIONS (check first and STOP if any fails): X7b is committed and reviewed; the operator has
freed space; the output drive has ≥ 15 GB free; the output drive is not H: (quarantined).
Branch: research/gap070-regen-candidate-20261104 from fix/gap070-connector-snap-exit-20261103 @ <X7b SHA>.
Create the worktree on the drive with space, without downloading LFS objects:
  GIT_LFS_SKIP_SMUDGE=1 git worktree add <DRIVE>:/wt/gap070-regen <branch>
The pinned inputs (map-of-record registry entries, OSM, DEM) must be resolved via
ultimate_pipeline/carla_tools/map_registry.py (verify_pinned_map), never by glob. Read LFS-materialised
copies from E:/wt/repair-map-realism-p0-837a8504 (read-only).
Set TMP/TEMP and every pipeline output directory on <DRIVE>. Never write to C:.
FORBIDDEN:
- push, merge, rebase, reset;
- editing map_registry pins; promoting; overwriting any existing map or reports/ file;
- editing protocol freezes;
- starting CARLA (the pipeline's live-CARLA steps must stay disabled; confirm the env/settings that do
  that before running);
- raising tolerances.
TASK:
1. Discovery (read-only): find the canonical regeneration entrypoint (scripts/regen_map_of_record.py
   and/or `python -m ultimate_pipeline.cli`); list required inputs, settings and env (THESIS_STRICT,
   RELEASE_PROFILE, UP_ENABLE_JUNCTION_CONNECTOR_SNAP default 1); estimate disk and time. Report
   before running.
2. Run TWO full regenerations (A and B) from the pinned OSM with identical settings into separate
   output dirs, with the X7 snap active (default). Record the command, environment, commit SHA,
   wall time, and per-stage output sha256.
3. Measure on the final XODR of A:
   - check_road_link_reciprocity: violations (must be 0), junction_exit_heading_discontinuity,
     junction_exit_geometry_gap;
   - junction_connector_snap's _count_junction_issues (entry side);
   - the repo's existing quality gates for this stage (lane links / targets, junction integrity,
     geometric continuity, strict validator);
   - road / junction / lane counts.
   Compare against the current map-of-record (registry entry auto_map_of_record, sha256 370abbbb…)
   and against the 2026-10-07 run's 07_lanes (sha256 787870ba…: 3,720 kinks).
4. Determinism (RQ1): A vs B, byte and structural, using the repo's existing determinism tooling
   (tests/unit/test_exp_osm_to_xodr_determinism_normalized.py logic or
   tools/check_osm_to_carla_determinism). Report whether X7 preserves the RQ1 property.
5. Deliverable: a new report directory
   reports/production_readiness/20261104T000000Z_GAP070_REGEN_CANDIDATE/ (README + JSON). Write the
   candidate XODR ONLY to the output drive and record its sha256. Do NOT commit the map. Do NOT promote.
   End with a go/no-go recommendation and the exact governed promotion steps for the operator.
```

---

## X9 — Codex: the ~0.1 m reversed connector stubs from netconvert (stage 2) — read-only first

```
Same preamble as X8 (worktree on any drive; read-only on maps; no CARLA, push or merge).
FACTS:
- stage_bisection.json (reports/production_readiness/20261103T000000Z_GAP070_STAGE_BISECTION/): the
  170-180 deg junction-exit bucket is 90 at 01_sanitized and 111 from 02_sumo_fixed onward. The
  ~0.1 m reversed single-line connector stubs are 58 at 01 and 81 from 02 on.
- So these stubs come mostly from CARLA Osm2Odr (01), and netconvert's XODR->XODR repair
  (ultimate_pipeline/topology/sumo_repair.py) adds about 23.
- The X7 snap leaves them unchanged (170-180 bucket 111 before and after).
TASK:
1. For all 81 stubs at 02 (and the 58 at 01): junction, incoming and exit roads, geometry, lanes, and
   whether any lane-level routing actually passes through them. Are they degenerate connectors that
   CARLA would drive through, or dead artifacts?
2. Diff 01 vs 02 for the 23 that netconvert adds: which netconvert option or behaviour creates them
   (read sumo_repair.py's command; check netconvert --help for the relevant options; you may run
   netconvert on a SMALL extracted region on the output drive, never on the full map in place).
3. Propose a SOURCE-STAGE remedy with evidence: drop degenerate stubs in the topology stage when they
   carry no lane routing, re-orient them, or change netconvert options. Measure it in memory on 02/03
   with the reciprocity, lane-link and junction-integrity checks. No tolerance raise.
Deliverable: a new report directory with README + JSON; no product code unless the remedy is small,
tested failing-first and behind a flag that is OFF by default.
```

---

## Still waiting on the operator

- **X5** (frame-count manifest) and **X6** (netconvert-direct OSM-ID prototype): explicit approval.
  Codex cannot approve them itself.
- **Disk space:** clean up G (see the state section above), and/or run an elevated `powercfg /h off`
  for C: (19 GB).
- **CARLA:** one visible-window run (`E:\CARLA\CARLA_0.9.16\CarlaUE4.exe -quality-level=Low`) or a
  GPU driver check. Four headless attempts hung at the RPC handshake.
- **The PR** to production (`integration/post-pr16-final-20261102` @ `46708baa`). X7 goes in a later
  PR, after X7b and X8.
