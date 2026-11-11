# X8 — governed regeneration plan for GAP-070 (2026-11-04)

**Status: BLOCKED** until C1 (snap hardening) is reviewed and ≥ 15 GB is free on one non-quarantined
drive. **Do not run X8 with `2cee039f` as it is**; it would regenerate 3,375 degenerate connectors
(review F-01). The hardened candidate is C1 in `CODEX_OPENCODE_EXECUTION_BACKLOG.md`.

## 0. Preconditions (check every one; STOP on any failure)

| # | Check | How | Pass condition |
|---|---|---|---|
| P1 | Candidate SHA | `git rev-parse` of the C1 branch | the reviewed C1 SHA, recorded |
| P2 | Baseline SHA | integration branch | the exact SHA, recorded (currently `1a36b560`) |
| P3 | Inputs resolved via registry | `ultimate_pipeline/carla_tools/map_registry.py` `verify_pinned_map`; the OSM / DEM / buildings pins | every pin `VERIFIED`; sha256 recorded. Never use a glob or mtime. |
| P4 | Full LFS inputs present | read from the full checkout `E:/wt/repair-map-realism-p0-837a8504` (read-only) | no LFS pointer files among the inputs; any missing input means `INCOMPLETE` |
| P5 | Disk | `df -h` on the output drive | ≥ 15 GB free; not H: (quarantined), D: or I: (personal data) |
| P6 | Live CARLA disabled | the settings/env that turn off live steps | confirmed, and recorded in the receipt |
| P7 | Unsafe planView flags | `settings_snapshot.json` | all false, same as 2026-10-07 |
| P8 | Protocol freezes | sha256 of rq3 `5aa8ae24…` and rq5 `db7155fe…` | unchanged |

## 1. Arms (identical inputs and settings; only the snap differs)

| Arm | Code | `UP_ENABLE_JUNCTION_CONNECTOR_SNAP` | Purpose |
|---|---|---|---|
| **C (control)** | baseline SHA | `0` | the true "no snap" reference; the cheapest and most informative arm |
| **A** | baseline SHA | `1` (merged rotate-in-place snap) | reproduces the current defect (3,720 kinks expected) |
| **B1, B2** | C1 SHA | `1` (hardened snap) | the candidate, run twice for determinism |

Run each arm into its own output directory on the output drive. TMP and TEMP must also be on that
drive. For every arm, record:
- the command line;
- the environment;
- the commit SHA;
- the wall time;
- the sha256 of every stage output.

Keep every intermediate stage XODR until the reviewer signs off (it is needed for root-causing), then
archive per C0. Never overwrite an existing map or `reports/` file.

## 2. Metrics (computed on each arm's final XODR, and on stage 06 where the snap acts)

Hard gates (zero tolerance, from OpenDRIVE well-formedness or existing project contracts):

| Metric | Tool | Threshold |
|---|---|---|
| Road-link reciprocity violations | `tools/check_road_link_reciprocity.py` | 0 (THESIS_STRICT contract) |
| Lane-link targets missing | `quality/check_lane_link_targets_exist.py` | 0 |
| Dangling junction / road references | strict validator | 0 |
| Refit regularity: zero-speed points | new invariant checker (backlog O13) | 0 |
| Refit simplicity: self-intersections | O13 | 0 |
| Refit arc length vs `@length` | O13 | `|arc/length − 1| ≤ 1e-4` (numerical; see review F-03) |
| Refit endpoint position / heading (contactPoint-aware) | O13 | ≤ 1e-6 m / ≤ 1e-6 rad |
| Junction integrity gate | existing stage gates | no new failures vs C |

Comparative gates (no new constants; B must not be worse than control C):

| Metric | Bound |
|---|---|
| Junction-exit heading kinks > 30° (`junction_exit_heading_discontinuity`) | B ≤ C (C ≈ 351 expected) |
| Junction-exit geometry gaps (carriageway rule) | B ≤ C |
| Per-connector peak curvature | for every connector, B ≤ max(C value, boundary curvature) × factor. **The factor is an operator decision**; "no increase" is the conservative default. Also report the count with radius below R_min. **R_min is an operator decision** (e.g. the smallest turning radius of the CARLA vehicle blueprints used in RQ3). |
| Elevation continuity (existing stage-5 gates) | B ≤ C |
| Entry reference-line mismatches (`_count_junction_issues`) | report only; not acceptance evidence (review F-07) |

Report-only (new evidence, not yet gated):
- lane-centre and lane-boundary continuity at every `connection/laneLink` (review F-08);
- the U-turn connector population and its pre-existing radius distribution (≈ 1.6 m at stage 01);
- counts for every snap skip reason (`skipped_uturn_shared_reference`,
  `skipped_displacement_exceeds_guard`, `skipped_missing_exit_anchor`, `skipped_refit_validation`).

## 3. Per-connector comparison

Match connectors across arms by junction id + incoming id + exit id; road ids are deterministic within
one SHA, so verify that first. For each connector, record:
- the planView hash in A, B and C;
- the start/end pose error;
- the arc/length ratio;
- the peak curvature;
- whether the curve is simple;
- the skip reason.

Deliver this as one JSON table, plus histograms. A reviewer must be able to filter to "B differs from
C" and inspect any connector.

## 4. Determinism (RQ1)

- B1 vs B2: byte-identical final XODR after the repo's timestamp normalization
  (`tests/unit/test_exp_osm_to_xodr_determinism_normalized.py` logic), and structurally identical
  (roads, junctions, lanes, lengths).
- Report whether the hardened snap preserves RQ1. Any difference is a STOP.

## 5. Independent verification

A second agent, read-only and on a different model family, recomputes from the arm outputs:
- every hard gate;
- the comparative counts;
- the determinism result.
It does this with its own script, not the writer's. It also hashes every output against the receipt.

## 6. CARLA (operator only)

Only after steps 2-5 pass, and only if the operator permits it:
1. load the B1 final XODR in CARLA 0.9.16 (`OpenDriveMap` generation);
2. confirm the RPC response and the map load;
3. sample waypoints through 20 random junctions that contain refit connectors;
4. drive the Traffic Manager through 5 of them.
Port listening alone is not success; an actual RPC response is required (AGENTS.md). This is blocked
today by GAP-077.

## 7. Deliverable and decision

Write a new directory `reports/production_readiness/<UTC>_GAP070_X8_REGEN/` (README + JSON). The
candidate map stays on the output drive, recorded by sha256 only; it is never committed or promoted.
End with GO / NO-GO and the exact governed promotion steps for the operator. Promotion is a separate,
operator-approved step through the registry.
