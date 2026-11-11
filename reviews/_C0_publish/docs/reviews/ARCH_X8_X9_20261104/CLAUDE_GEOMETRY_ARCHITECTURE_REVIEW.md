# Independent OpenDRIVE geometry review — GAP-070 candidate, X8, X9b (2026-11-04)

**Reviewer:** Claude (Opus 5.5), read-only. No code, map, evidence, branch or CARLA state was changed.
**Decision: `REQUIRES_SOURCE_HARDENING`** (details at the end).

## Scope and what was actually audited

| Item | Branch | SHA | Status |
|---|---|---|---|
| Integration (merged code) | `integration/post-pr16-final-20261102` | `1a36b560a69286841d4c42973cf00258a38f56c1` | on GitHub |
| GAP-070 candidate (isolated) | `fix/gap070-connector-snap-exit-20261103` | `2cee039f235f2cff7c87fa1fce935154cdcf3cd8` | on GitHub, not merged |
| GAP-079 inventory (isolated) | `research/gap070-reversed-stubs-20261104` | `06a31ed1` | **local only, not on GitHub** |

**Merged vs isolated.** The integration branch still has the original snap,
`ultimate_pipeline/tools/junction_connector_snap.py:289` (`_set_geometry_pose(geoms[0], target_pose)`).
It is called from `pipeline_stages/stage_05_geometry.py:253` and is **default ON**
(`UP_ENABLE_JUNCTION_CONNECTOR_SNAP`, default `"1"`, line 103). The candidate is 4 commits on top of
`46708baa`, which the integration branch already contains:
- `ffbe677e` and `f765dcb2`: code;
- `03aaccd4`: the measurement receipt only;
- `2cee039f`: tests.
Its only product change is `junction_connector_snap.py` (+157/−29).

**Evidence classes.** Every number below comes from code that was **executed in this review** (scripts
and JSON in `evidence/`, hashes in `evidence/SHA256SUMS.txt`). The input is the untracked local file
`reports/rq1_trial_runs/run_01/20261007_214826_524342/05_planview_20261007_214826_524342.xodr`,
sha256 `45c52059ec5b7d8d1e5f2f90a2f814bde465a923e7e77768c5f5e660790c721c`.
**This input is not on GitHub.** A GitHub-only auditor cannot reproduce these numbers until the input
is archived (see backlog item C0).

## Executive summary

1. **The candidate turns 3,375 of its 4,025 refits (84%) into degenerate curves.** These are U-turn
   connectors: the exit road is the reverse twin of the incoming road, and both share one reference
   line, so the snapped start and the exit anchor are the **same point** (median chord / length =
   3.4×10⁻⁸). A cubic Hermite with coincident endpoints and opposite tangents of magnitude L degenerates
   to `u(p) = L·p·(1−p)`, `v ≈ 0`. That is a zero-width needle that goes out L/4 and comes straight
   back. All 3,375 have arc length = 0.50 × `length`, and all have radius < 2 m. 2,734 have a
   zero-speed cusp, 423 self-intersect, and 2,037 overshoot by more than 0.5 m.
   **The candidate's own validation cannot see any of this.** It checks endpoint positions only
   (`junction_connector_snap.py:413`, 1×10⁻⁶ m), and endpoints and end tangents are exact.
2. **GAP-070's "~53° kinks" are these same U-turn connectors.** The merged snap rotates each of them by
   ≈ −26.57° (= −atan(½)) about its start; the candidate collapses them instead. The counts agree:
   3,373 kinks in the ~53° bucket, 3,375 zero-chord U-turn refits. The root cause in
   `ROOT_CAUSE_JUNCTION_CONNECTOR_SNAP.md` is correct, but incomplete: the snap is applied to a
   connector class where "snap the start to the incoming end" is geometrically meaningless.
3. **The U-turns come from CARLA Osm2Odr, not netconvert.** U-turn connectors (> 150° turn):
   - stage 01: 3,949, of which 3,521 have coincident incoming/exit reference points;
   - stage 02: 3,944 (3,507 coincident);
   - stage 05: 3,944 (3,507 coincident).
   Stage 01 is the map-of-record, so the map-of-record already contains them.
   `--no-turnarounds` is therefore **not** a GAP-070 remedy. Before any snap, their max curvature
   is 0.61 m⁻¹ (radius ≈ 1.6 m) in the original geometry. That is a pre-existing drivability question,
   and it is outside this candidate's scope.
4. **The other 650 refits are well-formed but violate the OpenDRIVE length contract.** None has a cusp
   or a self-intersection, but `length` is not recomputed: 344 have arc length off by more than 10%
   (worst: road 68739 has `length` 2.99 m, chord 10.92 m and arc 11.10 m, i.e. 3.7×). 28 now have a
   radius under 2 m (3 before), and 81 more than doubled their peak curvature. The cause is the
   tangent magnitude: it is fixed to the old `length` (`:211-212`), not scaled to the chord, and the
   start displacement has no upper bound (`rechain_guard_m` is accepted, then deleted at `:302`).
5. **The candidate's published claims** (4,025 refits; entry mismatches 4,092 → 67; end mismatches
   4,043 → 560; exit kinks 351 → 349; no new gaps) **reproduce, and they are the wrong acceptance
   metrics.** All of them measure endpoints. None measures the interior of the curve, the arc length
   or the curvature. The "entry mismatch" improvement is mostly the 3,375 U-turns being forced to a
   shared point, and that is exactly what breaks them.

## Findings

Each finding: severity · branch@SHA · path:line · reproduction · mechanism · smallest fix · tests ·
threshold.

### F-01 — P0 — Zero-chord U-turn connectors become degenerate needles
- **Where:** candidate `2cee039f`, `ultimate_pipeline/tools/junction_connector_snap.py:196-232`
  (`_replace_with_hermite`), selected at `:380-382`.
- **Reproduce:** `python evidence/x7_geom_audit.py` (candidate worktree on `sys.path`, input
  `45c52059…`). In `by_class.uturn_zero_chord`, n = 3375, `arc_ratio_p50` = 0.5000, `cusp` = 2734,
  `not_simple` = 423. Example connector **51810** (junction 1):
  - incoming 47570 ends at (7460.550, 6255.160), hdg 160.6°;
  - exit 42130 starts at that same point, hdg −19.4° (exactly the reverse);
  - the candidate writes `bU = 9.597`, `cU = −9.597`, `dU ≈ 0`, `bV = cV = dV ≈ 0`.
- **Mechanism:** with chord = 0 and Δhdg = 180°, the Hermite constraints force a back-and-forth path
  along one line. The speed |r′(p)| = 0 at p = ½, the heading flips by 180° in zero distance, and the
  curvature is unbounded.
- **Smallest fix:** in the snap (both the merged version and the candidate), **exclude** connectors
  whose topology-declared exit endpoint coincides with the incoming contact point, or whose required
  turn exceeds 150°. Report them as `skipped_uturn_shared_reference`. Do not refit them.
- **Tests (failing first):**
  - a synthetic road pair sharing one reference line, plus a U-turn connector: snapped = 0,
    skipped_uturn = 1, planView byte-identical;
  - the real fixture 51810 extracted with its incoming and exit roads.
- **Threshold:** 0 refits with zero speed (`min |r′| > 0`), 0 self-intersecting refits. Both are hard
  zero. They follow from regularity of the reference line (OpenDRIVE defines heading from the tangent;
  a zero tangent leaves it undefined).

### F-02 — P0 (for any X8 that includes the merged snap) — The merged default-on snap damages the same 3,375 connectors
- **Where:** integration `1a36b560`, `junction_connector_snap.py:289` (rotate-in-place), enabled at
  `stage_05_geometry.py:103/253`.
- **Reproduce:** `ROOT_CAUSE_JUNCTION_CONNECTOR_SNAP.md` (`46708baa`): kinks 351 → 3,720, ~53° bucket
  4 → 3,373. Cross-check: this review's U-turn class has n = 3,375, and example 51810 has hdg −3.0159
  → 2.80354.
- **Mechanism:** the same misclassification as F-01. U-turn connectors are deliberately offset from
  the shared reference point (≈ 3.2 m, at atan(½)), but the snap treats that offset as displacement.
- **Smallest fix:** the same exclusion as F-01, applied to the merged snap. Measure with arm C
  (snap disabled) in X8.
- **Threshold:** junction-exit kinks > 30° in the snapped arm ≤ the count in the snap-disabled arm
  (351 at stage 05). That is a comparative bound and needs no new constant.

### F-03 — P1 — Geometry `length` is not the arc length after a refit
- **Where:** `2cee039f`, `junction_connector_snap.py:205-226` keeps `length` and uses it as the
  tangent magnitude.
- **Reproduce:** `by_class.other.arc_dev_gt_10pct` = 344 of 650. Worst: 68739 / 67905 / 68731
  (arc / length 3.71 / 3.69 / 3.66).
- **Mechanism:** with `pRange="normalized"` the kernel evaluates `p = s/length`
  (`opendrive_geometry_kernel.py:48`), so endpoints still land at s = length, but s is no longer arc
  length. OpenDRIVE defines `@length` as the reference-line length. Lane widths, laneSections,
  elevation, superelevation, objects and signals are all positioned in s, so they get compressed or
  stretched. CARLA waypoint spacing and route distances are wrong too.
- **Smallest fix:**
  1. tangent magnitude = chord length (or an iterative solve that keeps tangent ≈ arc length);
  2. compute the arc length numerically;
  3. either rescale every s-indexed child of that road by `arc/length` and set `length` = arc, or
     reject the refit if `|arc/length − 1|` exceeds the threshold.
  Rejecting is smaller and safer.
- **Tests:** a 3 m connector displaced by 8 m is refit with |arc − length| ≤ tol, or rejected.
  Assert that every s-indexed child stays within [0, length].
- **Threshold:** `|arc/length − 1| ≤ 1×10⁻⁴`. This is meant as a numerical-integration tolerance, not a quality
  tolerance. The integrator's accuracy at this setting has not been measured: the audit script uses
  the trapezoid rule over 800 samples. C1 must confirm it by comparing against 10× the sample count.
  Changing the tolerance is an operator decision.

### F-04 — P1 — Unbounded start displacement; `rechain_guard_m` is silently ignored
- **Where:** `junction_connector_snap.py:284-302` (`del rechain_guard_m`); `:382` only skips gaps
  ≤ `max_gap_m` (2 m).
- **Reproduce:** `other_worst_kmax` in `x7_geom_audit.json`: 68739 has chord 10.92 m from a 2.99 m
  connector. Its start moved roughly 8 m.
- **Mechanism:** any connector whose start is more than 2 m from the incoming end is moved, no matter
  how far. Large moves stretch short connectors (F-03) and create end corners: radius 0.14 m on 68739.
- **Smallest fix:** enforce an upper bound. Refuse when the move is larger than a declared limit, and
  record it as `skipped_displacement_exceeds_guard`. The limit itself is an **unresolved threshold
  decision**. The existing parameter value (50 m) is a placeholder, not a justified bound. Propose that
  it be derived from the incoming road's lane-section width (the maximum lateral offset that can be
  explained by lane geometry), and get operator sign-off.
- **Tests:** a connector displaced beyond the guard is skipped with its geometry byte-identical.

### F-05 — P1 — Validation checks only endpoint position
- **Where:** `junction_connector_snap.py:408-418`.
- **Mechanism:** heading, tangent continuity (G1), curvature, cusps, simplicity and arc length are all
  unchecked, which is why F-01 and F-03 pass.
- **Smallest fix:** after each refit, evaluate with the kernel and require all of:
  - start and end tangent within 1×10⁻⁶ rad of the required (contactPoint-aware) heading;
  - `min |r′| > 0`;
  - `LineString(samples).is_simple`;
  - the F-03 arc-length bound;
  - peak curvature ≤ max(the original connector's peak curvature, the incoming/exit boundary
    curvature) × a factor. The factor is an unresolved threshold decision; "no increase" is the
    conservative default.
  On any failure, restore the original planView. The restore mechanism (`:393, :415`) already exists.
- **Tests:** one failing-first test per gate, using synthetic curves that violate exactly that gate.

### F-06 — P2 (latent) — Heading convention ignores contactPoint
- **Where:** `junction_connector_snap.py:188` (exit anchor) and `:380` (target = incoming start or end
  by distance). `_road_endpoint_pose` (`diagnostics/audit_xodr_visual_geometry.py:73-81`) returns the
  reference-line heading without flipping it for the `start` side.
- **Reproduce:** on this map, 0 of the 4,025 refits are affected: all use incoming `end` and exit
  `start`, with tangent errors ≤ 10° in 0 cases. It is latent: any map where the snap picks an
  incoming `start`, or an exit linked with `contactPoint="end"`, gets a reversed tangent, i.e. a loop.
- **Smallest fix:** required start heading = hdg_end(incoming) if the incoming end is used, else
  hdg_start(incoming) + π. Required end heading = hdg_start(exit) if contact is start, else
  hdg_end(exit) + π. Add an assertion test for both flipped cases.

### F-07 — P2 — The acceptance metrics in the candidate's receipt are endpoint-only
- **Where:** `reports/production_readiness/…X7…/measurement.json` (`03aaccd4`).
- **Mechanism:** the receipt reports entry and exit errors and kinks, but no interior invariants.
  Taken alone it is not acceptance evidence.
- **Fix:** X8 must report the full invariant matrix (`GEOMETRY_INVARIANT_MATRIX.md`).

### F-08 — P2 — Lane-level continuity is not measured anywhere
- **Mechanism:** every continuity metric in use (entry mismatch, exit kink, exit gap) compares
  **reference lines**. U-turn connectors are offset by design, and one-way roads have ~6.5 m
  reference-line offsets. Drivability depends on lane centre and lane boundary continuity at each
  laneLink, which nobody measures.
- **Fix:** add a report-only lane-centre continuity check per `junction/connection/laneLink`: evaluate
  both lanes' centre poses at the contact s with the kernel plus lane widths and laneOffset. Use it as
  an X8 metric before it becomes a gate.

### F-09 — P3 — The 0.1 m reversed stubs (GAP-079) need classification, not deletion
See `GAP079_X9B_INVESTIGATION_PLAN.md`. All 58 (stage 01) and 81 (stage 02) carry declared routing
(verified: `evidence/x9check.py`). Classification is pending X9b part 2.

## Mathematical assessment (Part 2 summary; full matrix in `GEOMETRY_INVARIANT_MATRIX.md`)

- **Endpoint position / tangent:** satisfied by construction (cubic Hermite in the local frame, with
  `a = 0`, `b = t₀`, `c = 3P − 2t₀ − t₁`, `d = −2P + t₀ + t₁`; p ∈ [0, 1]). Verified numerically:
  0 tangent errors > 10°, and positions within 1×10⁻⁶ m.
- **World → local:** `u = cos h·dx + sin h·dy`, `v = −sin h·dx + cos h·dy` (`:208-209`). Correct
  for OpenDRIVE's local u/v frame.
- **`pRange="normalized"`:** the kernel implements `p = s/length` (`kernel:48`). Correct semantics,
  but this makes the arc-length error (F-03) invisible to every s-based consumer.
- **Curvature continuity:** within one cubic, curvature is continuous wherever `r′ ≠ 0`. At the
  connector ends, G2 continuity with the neighbouring roads is **not** enforced (a Hermite has free
  curvature at its ends). Jumps up to 7.0 m⁻¹ were observed at ends (68739). No current gate covers
  G2; whether to require it is an open decision.
- **Degeneracy:** zero chord (F-01) and |Δhdg| ≈ π are unguarded. A near-zero chord with Δhdg ≈ 0
  (a "straight but displaced" connector) would also produce an S-cusp; it doesn't occur here, but it
  has no guard either.
- **Heading wraparound:** `_norm_angle` on Δ (`:210`) is correct for the end-tangent direction.
- **Elevation, lane sections, laneLinks:** not modified by the refit. That is only safe if `length`
  equals the arc length (F-03), because their s-indices then keep their meaning.

## Final decision

**`REQUIRES_SOURCE_HARDENING`.** Running X8 with the candidate as it is would regenerate a map
containing 3,375 degenerate connectors. Minimum actions before a governed X8:
1. **C1:** add the U-turn / shared-reference exclusion to the snap (F-01, F-02). Then decide whether
   to keep the Hermite refit for the remaining ~650, with F-03, F-04 and F-05 gates added, or to
   leave the snap disabled.
2. **C0:** archive the 2026-10-07 stage-5 input (sha256 `45c52059…`), or regenerate it under X8,
   so the evidence is reproducible beyond this machine.
3. **X8 with three arms:** current snap, hardened snap, and snap disabled (control). Run the full
   invariant matrix, plus lane-centre continuity (F-08).
4. **Operator decisions:** the displacement guard (F-04), the curvature factor (F-05), and whether
   the 1.6 m-radius U-turns from Osm2Odr are acceptable for CARLA at all.
