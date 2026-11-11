# GAP-070 root cause — the junction connector snap rotates connectors

**Status:** root cause REPRODUCED. This supersedes the "attribution INCOMPLETE" conclusion in
`README.md` (that search covered only `stage_06_links.py`). Nothing has been fixed yet.

## Finding

The ~53° junction-exit kinks (and the related exit geometry gaps) are produced by
`ultimate_pipeline/tools/junction_connector_snap.py::snap_junction_connectors`. Stage 5 calls it on
its continuity output: `pipeline_stages/stage_05_geometry.py::_run_junction_connector_snap`, called
at line ~253. It is **ON by default** (`UP_ENABLE_JUNCTION_CONNECTOR_SNAP`, default `"1"`, line ~103),
and it still is at `682e710a`.

For each connector it judges displaced, the snap sets the start pose of the first geometry (`x`, `y`
and **`hdg`**) to the incoming road's end pose (`_set_geometry_pose`). The connector's
`paramPoly3`/arc shape coefficients are left unchanged. That rotates the whole connector about its
start, so its far end no longer meets the exit road: a heading kink of about 53° at the exit, plus a
positional gap.

The snap was enabled by default on 2026-09-12 (settings-audit decision, `CONNECTOR_SNAP_WIRING_EVIDENCE.json`).
That evidence measured only the ENTRY side (`junction_connector_issues` 8,746 → 5,183) and
structural counts. It never measured the connector's EXIT side, where this damage occurs.

## Reproduction (executed 2026-11-03, current code at `682e710a`, in memory, nothing written)

Input: `reports/rq1_trial_runs/run_01/20261007_214826_524342/05_planview_20261007_214826_524342.xodr`
(sha256 `45c52059…`). This is the stage output just before the snap; it is untracked run output in
the main checkout.

| | heading kinks > 30° | ~53° bucket | 170–180° |
|---|---|---|---|
| 05 as written | 351 | 4 | 111 |
| 05 after `snap_junction_connectors(root)` (defaults) | **3,720** | **3,373** | 111 |
| real 06_continuity / 07_lanes | 3,720 | 3,373 | 111 |

The snap reported `connectors_snapped = 4025`, identical to the run's own
`junction_connector_snap_report.json` and to the 4,025 connectors whose planView differs between 05
and 06. 3,369 of the 3,373 ~53° kinks are on those rewritten connectors; no exit road was rewritten.
Example: connector 51810, `hdg` −3.0159 → 2.80354 (−26.57°), `paramPoly3` coefficients unchanged.

The 170–180° group (111, mostly ~0.1 m reversed single-line stubs) already exists before the snap.
It enters at `02_sumo_fixed` (the netconvert repair) and is a separate issue.

## Consequences

- Every map generated with the current defaults gets about 3,400 connector exit kinks. CARLA can
  load such maps, but the junction exits are geometrically discontinuous, which affects driving
  behaviour and perception captures at junctions (RQ3).
- The b5ea4911 tangent fit does not repair them (3,720 → 3,483, 427 of 22,588 attempted).
- A fix belongs at the source stage, in the snap. It must not raise any tolerance (GAP-026 rule).
  It must keep the entry-side benefit while not breaking the exit side, e.g. move the start but re-fit
  the curve to both end poses (Hermite through the incoming end pose and the exit start pose), or
  restrict the snap to translation where the exit join is preserved. Whatever is chosen has to be
  measured on BOTH sides (entry `junction_connector_issues` and the exit
  heading/geometry-gap checks) before any default change. Regenerating the map-of-record is a
  separate, governed step.
