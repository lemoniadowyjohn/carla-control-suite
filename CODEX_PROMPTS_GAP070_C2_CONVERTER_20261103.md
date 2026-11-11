# Codex prompts — GAP-070 root cause, C2, converter prototype (2026-11-03)

Run one at a time; each is the single writer for its own branch. X4 needs no operator decision. X5 and
X6 each start with a **[DECISION]** gate: do not run them until the operator has answered.

## Shared preamble (paste first)

```
Repo lemoniadowyjohn/carla-control-suite, rules in AGENTS.md.
Base: integration/post-pr16-final-20261102 @ 682e710a (CI green, run 41704108450).
Create your own worktree and branch from it, without downloading LFS objects (disk is nearly full):
  GIT_LFS_SKIP_SMUDGE=1 git worktree add -b <your-branch> E:/wt/<your-branch> 682e710a
Read LFS map files ONLY from the existing full checkout E:/wt/repair-map-realism-p0-837a8504
(read-only; never edit it).
DISK: C: ~1.4 GB, E: ~3 GB free. Set TMP/TEMP to E:/wt/<your-branch>_tmp. Use
pytest -p no:cacheprovider --basetemp=E:/wt/<your-branch>_tmp/bt and delete it after each run.
Never write a map file larger than 20 MB; never keep more than one copy.
Python: C:/Users/admin/PycharmProjects/gpt4/pythonProject3/.venv/Scripts/python.exe
FORBIDDEN:
- push, merge, rebase, reset, force;
- editing configs/*protocol_freeze*.json;
- modifying any existing file under reports/;
- changing map-of-record pins or the registry; promoting maps;
- starting CARLA;
- raising any tolerance or threshold to make a count go down (AGENTS.md: GAP-026 cannot be fixed
  by raising tolerance);
- cosmetic edits to the final XODR. Generator fixes happen at the SOURCE stage only.
Preserve EOL/BOM. Tests come first, failing on the old code. Never write PASS without executed output.
Return: SHAs, diff stats, failing-first tails, test tails, measured numbers, residual risks.
```

---

## X4 — GAP-070 stage bisection: where do the 53° kinks and reversed stubs come from? (no decision needed)

```
[preamble]  Branch: investigate/gap070-stage-bisection-20261103
FACTS (verified at 682e710a):
- ultimate_pipeline/quality/check_road_link_reciprocity.py reports, report-only,
  junction_exit_heading_discontinuity (EXIT_HEADING_DISCONTINUITY_DEG = 30) and
  junction_exit_geometry_gap.
- On the final stage output of one real run,
  C:/Users/admin/PycharmProjects/gpt4/pythonProject3/carla_-main/reports/rq1_trial_runs/run_01/20261007_214826_524342/07_lanes_20261007_214826_524342.xodr
  (sha256 787870ba...), it reports:
  - 3,720 kinked exits; 3,391 at ~53.13 deg. The connector ends in paramPoly3, the exit road
    starts with a line. Kernel headings were verified against finite differences (79/80).
  - 111 at 170-180 deg; 73% of those are ~0.1 m single-line connector stubs with reversed heading
    (all right-hand-lane roads; position gap 0).
  - 207 geometry gaps, which include 147 of the kinked exits.
  See reports/production_readiness/20261103T000000Z_GAP_REGISTER_ADDENDUM/GAP-070_*.md.
- The same run kept every intermediate stage in that directory:
  01_sanitized, 02_sumo_fixed, 03_topology, 04_elevation, 05_planview, 06_continuity,
  06_geometry_frozen, 07_lanes (~120-150 MB each, read-only).
- That run predates the GAP-026 connector fixes 9ff56e7d / 2a886117 / b5ea4911. b5ea4911 added a
  Hermite tangent fit (ultimate_pipeline/topology/junction_connector_tangent_fit.py,
  _find_outgoing_anchor); it is OFF by default (UP_ENABLE_JUNCTION_CONNECTOR_TANGENT_FIT).
  Other connector editors: ultimate_pipeline/tools/junction_connector_rebuild.py,
  junction_connector_snap.py, xodr_carla_hardener.py, and pipeline_stages/stage_05_geometry.py.
TASK (read-only first):
1. Run check_road_link_reciprocity on EVERY stage file (record each sha256 before and after). Table
   per stage: heading_discontinuity count, the 53-deg bucket, the 170-180 bucket, the count of
   ~0.1 m stubs, geometry_gap. Identify the FIRST stage where each population appears and the stage
   where it grows. Track 20 specific exits by (junction, incoming road) across stages; road ids can
   change, so match by junction id plus connection incomingRoad.
2. If 01_sanitized already contains the 53-deg population, the cause is upstream of the pipeline
   (CARLA Osm2Odr / netconvert). Prove it by reading those geometries in 01. Then check whether
   02_sumo_fixed (netconvert repair) changes it.
3. Locate the code that produces the ~0.1 m reversed stubs (grep the length 0.1 / min-length
   constants in the connector tools and the stage modules that run before the stage where the stubs
   first appear).
4. Without writing a full map: apply b5ea4911's tangent fit IN MEMORY to the 06/07 stage tree
   (import its function; do not save the XODR) and re-measure. How many kinks remain, and does it
   create geometry gaps or new self-intersections (use the existing continuity checks)?
5. PROPOSE (do not implement) the minimal SOURCE-STAGE fix for each population: enable the tangent
   fit (with evidence), fix stub generation at its origin, or upstream converter settings. Include
   the expected counts after the fix.
Deliverable: a NEW report directory
reports/production_readiness/20261103T000000Z_GAP070_STAGE_BISECTION/ (README.md + a small JSON with
the per-stage table), committed on your branch. No product code changes in this task.
```

### X4 follow-up from the Claude verifier (2026-11-03): pass this to Codex verbatim

```
Your stage_bisection.json shows the 53-deg kinks drop 3,411 -> 4 at 02_sumo_fixed, stay at 4
through 03 and 05, and return as 3,373 at 06_continuity.
Execution order by file mtime is 05 (22:22) -> 06_continuity (23:17) -> 06_geometry_frozen (23:24)
-> 04_elevation (23:28) -> 07_lanes (23:31). The "04_elevation" file is written AFTER stage 6, so
do not read it as stage 4 input.
Independently verified by the Claude verifier:
- 06_continuity derives from 05, not 01: planView(06)==planView(05) for 2,616 of 3,000 sampled
  roads, and planView(06)==planView(01) for 0.
- Stage 6 rewrote the planView of 4,025 roads. All 4,025 are junction connectors.
- 3,369 of the 3,373 53-deg kinks are on exactly those rewritten connectors; 0 exit roads were
  rewritten.
- The rewrite changes ONLY geometry@hdg and keeps the paramPoly3 coefficients. Example connector
  51810: hdg -3.0159 -> 2.80354, a rotation of -26.57 deg (= -atan(1/2)); bU/cU/bV/cV unchanged.
  So a heading-only start recompute rotates whole connectors and breaks the exit join.
- In CURRENT code (and at 8c246fc5, the code of that run) every heading-mutating step in
  _step6_planview_continuity is gated behind unsafe flags that are OFF by default
  (cee01874, 352260f1).
So X4 step 5 must answer:
(a) Did that run have ENABLE_UNSAFE_* / RELEASE_PROFILE=EXPERIMENTAL_UNSAFE on? Check its logs,
    validation report and run receipts.
(b) If not, which UNGATED path in stage_06_links.py (e.g. the "planView seam auto-repair" block
    that writes cont_out, ~lines 600-720) or a helper it calls sets geometry hdg on connectors?
    Reproduce: run that path in memory on 05_planview and diff against 06.
(c) Is that path still live and ungated at 682e710a?
Also: b5ea4911's tangent fit only took 3,720 -> 3,483 and 3,373 -> 3,370 (427 of 22,588 attempted),
so enabling it is NOT the fix. The fix belongs where stage 6 rotates connectors. That is a
source-stage change; GAP-026 rules apply, no tolerance raise.
Finish the README.md of the stage-bisection report, then commit it on your branch.
```

## X7 — fix the junction connector snap so it stops breaking junction exits (source stage)

```
[preamble]  Base: integration/post-pr16-final-20261102 @ 46708baa (NOT 682e710a).
Branch: fix/gap070-connector-snap-exit-20261103
ROOT CAUSE (reproduced, see
reports/production_readiness/20261103T000000Z_GAP070_STAGE_BISECTION/ROOT_CAUSE_JUNCTION_CONNECTOR_SNAP.md):
- ultimate_pipeline/tools/junction_connector_snap.py::snap_junction_connectors is called by
  stage_05_geometry.py::_run_junction_connector_snap. It is default ON
  (UP_ENABLE_JUNCTION_CONNECTOR_SNAP="1").
- For a displaced connector it sets the first geometry's x/y/hdg to the incoming road's end pose
  (_set_geometry_pose) and keeps the paramPoly3/arc coefficients. That rotates the connector, so its
  exit end no longer meets the exit road.
- Measured on 05_planview (sha256 45c52059...): exit heading kinks 351 -> 3,720 and the ~53 deg
  bucket 4 -> 3,373, with connectors_snapped = 4,025.
- The 2026-09-12 default-on decision used entry-side evidence only (junction_connector_issues
  8,746 -> 5,183).
TASK:
1. Write a test that reproduces the defect: a synthetic incoming road, a connector with a
   paramPoly3, and an exit road, where the connector start is displaced. After the snap, the entry is
   joined but the exit heading discontinuity is > 30 deg. It must FAIL on current code.
2. Fix it in the snap (SOURCE STAGE; no tolerance raised; no final-XODR edit). When the start pose
   changes, re-fit the connector so BOTH ends hold: start = incoming end pose, end = exit start pose
   (the pose the connector met before the snap). Use the canonical geometry kernel and a cubic
   Hermite paramPoly3 in local coordinates (pRange normalized), keeping the original length scale.
   If an exit anchor can't be determined, do not rotate. Translate only if that keeps the exit join
   within the existing tolerance, otherwise skip and count the connector as a residual (never
   guess). Record per-connector before/after entry and exit errors in the report.
3. Measure IN MEMORY on 05_planview (read-only, record sha256 before and after) with the new snap:
   - entry side: junction_connector_issues (the same counter the 2026-09-12 evidence used);
   - exit side: check_road_link_reciprocity junction_exit_heading_discontinuity and
     junction_exit_geometry_gap;
   - connectors_snapped / residual counts.
   Expected: entry issues close to the default-on benefit; exit kinks close to the pre-snap 351.
   Report what you actually measure.
4. Do NOT change the default flag and do NOT regenerate or promote any map. Put the before/after
   table in a new report directory and in the commit message, for the operator to decide on the
   default and on a governed map-of-record regeneration.
Run the snap's existing tests (git grep -l junction_connector_snap -- '*test*.py') plus
test_check_road_link_reciprocity.py.
```

## X5 — C2: wire G03 expected frame counts into the strict capture path [DECISION REQUIRED]

```
[preamble]  Branch: fix/c2-expected-counts-20261103
DECISION GATE: ask the operator which source of expected frame counts is authoritative. The
recommendation (audit): a pre-capture manifest whose sha256 is bound into the capture receipt.
configs/rq3_protocol_freeze_v1.json line ~80 says "exact frame counts bound via dataset manifest
hashes at execution". If the operator has not answered, STOP.
FACTS: ultimate_pipeline/perception/record_route_fixed.py run_strict_rq3_capture (~3541) never
calls rq3_capture_contract._validate_frame_set_consistency, and evaluate_frame_completeness is only
used by tools/capture_perception_pair_safe.py:264.
TASK (after the decision):
- Write a pre-capture manifest (sensors, frames per sensor, route id, seed) before the first tick;
  hash it; bind the hash into the capture receipt.
- At completion, call _validate_frame_set_consistency with expected_counts read from that manifest.
  Under THESIS_STRICT a mismatch fails the capture; the legacy path keeps warnings.
- Tests: truncated capture (3/5) -> strict FAIL; exact -> pass; manifest tampered after capture ->
  FAIL (hash mismatch); missing manifest -> FAIL.
- No CARLA: use the existing fake-world fixtures that test_rq3_* already use.
```

## X6 — prototype: netconvert-direct OSM→XODR conversion with OSM way IDs [DECISION REQUIRED]

```
[preamble]  Branch: research/netconvert-direct-osm-ids-20261103
DECISION GATE: the operator must approve evaluating a converter switch. This changes how every map is
generated, so it is a research prototype only; nothing is promoted.
FACTS:
- Today ultimate_pipeline/osm/osm_to_xodr_wrapper.py:254 uses CARLA carla.Osm2Odr.convert, which
  loses OSM way ids (0 of 32,267 roads keep one).
- ultimate_pipeline/topology/sumo_repair.py:49 runs netconvert XODR->XODR only.
- Proven on a 3-way fixture: `netconvert --osm-files X --opendrive-output Y --output.original-names
  true` writes <userData code="sumoId" value="<osm way id>"/> on every road (negative value =
  reverse direction).
- SUMO 1.24.0: C:/Sumo/sumo-win64extra-1.24.0/sumo-1.24.0/bin/netconvert.exe
TASK:
1. On a SMALL clip of the pinned OSM (<= 2 km^2, inside the Grid0828 footprint; write it under the
   tmp dir), convert with BOTH paths: CARLA Osm2Odr with the repo's exact settings/proj_string, and
   netconvert-direct with --output.original-names and the closest equivalent options (document each
   flag).
2. Compare: road/junction counts, total length, lane counts, junction connection counts, georeference
   (same place? use the repo's local_registration frame math), the GAP-070 heading/gap counts on each
   (run check_road_link_reciprocity), and the fraction of roads carrying an OSM way id.
3. Prototype (behind a flag that is OFF by default) the plumbing that carries sumoId into the road
   userData the pipeline reads, plus an exact-id mode for ultimate_pipeline/quality/
   osm_road_link_topology.py instead of the 0.4%-coverage spatial match. Unit tests only; no full-map
   regeneration.
Deliverable: a new report directory with the comparison table and a go/no-go recommendation. Code
stays behind the flag.
```
