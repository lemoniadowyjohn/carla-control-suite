# Errata to ARCH-X8-X9, ARCH-002 and GAP register addendum 2 (found by ARCH-003)

**Root fact (LOCAL_REPRODUCED).** Run `20261007_214826_524342` did not start from OSM.
- Its `run_manifest.json` records `inputs.INPUT_XODR.sha256 =
  370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`.
- `settings_snapshot.json` has `INPUT_XODR = …/ingolstadt_perception_map_of_record_20260916_232831.xodr`
  (the pinned map-of-record) and `PREANCHOR_INPUT_XODR = false`.
- Its stage `01_sanitized` is byte-identical to that pin.
- The map-of-record is itself a processed pipeline output: 32,267 roads, against 32,920 roads and
  3,717 junctions for raw Osm2Odr output (C15 determinism arm).

**So the stage-01 → stage-02 comparison in this run is "map-of-record → map-of-record re-processed by
netconvert", not "Osm2Odr → netconvert".**

| # | Earlier statement | Status | Corrected statement |
|---|---|---|---|
| X1 | ARCH-X8-X9 summary 3: "The U-turns come from CARLA Osm2Odr, not netconvert … `--no-turnarounds` is therefore **not** a GAP-070 remedy" | **INVALID inference** | U-turn connectors are **present in the map-of-record** (3,949) and survive re-processing (3,944). Their origin (Osm2Odr, or the netconvert pass of the run that produced the map-of-record) is **undetermined**. Whether `--no-turnarounds` matters is **open**. Settling it needs a run from raw OSM with per-stage outputs (X8 or X9b). |
| X2 | GAP register addendum 2, GAP-079 subsystem/description: "CARLA Osm2Odr (stage 01) + netconvert repair (stage 02)"; "58 at stage 01 … +23" | **Attribution invalid** (counts stand) | 58 stubs are present in the map-of-record; 81 remain after the pipeline re-applies netconvert to it (+23). The origin is undetermined. **Addendum 2 is committed and immutable**, so record this in a new addendum 3. |
| X3 | ARCH-002 risk R-08: "Pre-existing Osm2Odr U-turns …" | wording | "Pre-existing **map-of-record** U-turns …" |
| X4 | X9 / X9b prompts and `GAP079_X9B_INVESTIGATION_PLAN.md`: "stubs come mostly from CARLA Osm2Odr (01)" | **invalid premise** | The X9b bisection must use a **fresh Osm2Odr conversion** of the pinned OSM (`ingolstadt_authoritative.osm`, sha256 `b9e07465…`, from the run manifest) as stage 01. Bisecting netconvert on the map-of-record measures a second netconvert pass, not the first. |
| X5 | Any statement that run `20261007_214826_524342` is RQ1 (OSM→XODR determinism) evidence | **invalid** | Despite its location (`reports/rq1_trial_runs/`), this run does not execute Osm2Odr, so it cannot evidence OSM→XODR determinism. |
| X6 | `RQ_ANSWERS_20261104.md` (committed `1a36b560`), RQ2 row: "Inside the manual map's convex-hull footprint, lane width and curvature agree closely (lane_width_gap 0.042, curvature_gap 0.093 whole map / 0.22 local)" | **mislabelled** | Hull-local values (`local_registration.json`): lane_width_gap **0.0597**, curvature_gap **0.2206**. The 0.0415/0.0931 values are **whole-map**. Bounding-box local values: 0.0614 / 0.2248, and the road-length ratio becomes **4.488** instead of 2.683. |
| X7 | `RQ_ANSWERS_20261104.md` RQ4 row: "the CI excludes zero for every seed" | **not a separation test** | The CI is a bootstrap over 5 training seeds of **one** map pair. A non-zero cosine distance has no null reference. See `SCI_ARCH001/SCIENTIFIC_CLAIM_BOUNDARIES.md`. |

These do **not** change the lane-level GAP-070 findings: those compare arms on the same input. They
do change origin attributions, and the scope of GAP-079.
