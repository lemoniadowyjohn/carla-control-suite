# GAP-070 stage bisection

Baseline: `682e710a` (`integration/post-pr16-final-20261102`).  This report is
diagnostic only: no product code or XODR was changed.  The eight source maps are
the prompt-specified, untracked historical run output under the shared checkout.
They were read-only; `stage_bisection.json` records matching before/after SHA-256
values for every input.

## Result

| chronological artifact | heading discontinuities | 53-degree bucket | 170-180 bucket | 0.1 m reversed stubs | geometry gaps |
| --- | ---: | ---: | ---: | ---: | ---: |
| 01_sanitized | 3,753 | 3,411 | 90 | 58 | 7 |
| 02_sumo_fixed | 351 | 4 | 111 | 81 | 0 |
| 03_topology | 351 | 4 | 111 | 81 | 0 |
| 05_planview | 351 | 4 | 111 | 81 | 0 |
| 06_continuity | 3,720 | 3,373 | 111 | 81 | 1,544 |
| 06_geometry_frozen | 3,720 | 3,373 | 111 | 81 | 1,544 |
| 07_lanes | 3,720 | 3,373 | 111 | 81 | 207 |

`04_elevation` has the same bad population as Stage 6, but its file mtime is
23:28, after `06_continuity` (23:17) and `06_geometry_frozen` (23:24); it is not
evidence of an earlier origin.  The actual transition is `05_planview` to
`06_continuity`.  Twenty `(junction, incomingRoad)` identities were tracked in
the JSON; 1 appears after SUMO repair and all 20 reappear at Stage 6.

The upstream raw conversion does contain 3,411 53-degree kinks.  Netconvert
repair removes all but four.  Stage 6 then creates 3,369 of its 3,373 53-degree
kinks on the 4,025 junction connectors whose planViews it rewrites; no exit road
is rewritten.  The verified example connector 51810 changes only `geometry@hdg`
(-3.0159 to 2.80354, a -26.57 degree rotation) while retaining its paramPoly3
coefficients.  Rotating that start frame swings the whole connector away from its
unchanged exit road.

## Run configuration and live path

`settings_snapshot.json` records all `ENABLE_UNSAFE_*` controls false, including
`ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE`, and
`ENABLE_PLANVIEW_SEAM_AUTO_REPAIR=false`.  Therefore this is not evidence that
the explicitly unsafe toggles were enabled.  However,
`stage6_containment_runtime.json` contains references to
`PlanViewSmoother.recompute_geometry_starts` and "plan-view seam auto-repair",
but this alone does not establish execution.  The recorded strict configuration
and the baseline's `THESIS_STRICT` containment route should instead select the
read-only diagnostic path and disable heading mutation and seam auto-repair.
The 4,025 observed rewrites are therefore an unresolved historical
runtime/config mismatch.  Read-only audit also rules out the visible candidates:
the ungated `MeshContinuityRepairer` changes only `geometry[i>0]`; the
recompute/seam helpers likewise affect only later geometries and would change
`x/y` as well as heading.  All 22,588 Stage-5 junction connectors have one
geometry, while an in-memory default-config reproduction changed 1,098
non-connectors and zero connectors.  Any remediation must first reproduce the
05-to-06 delta and identify the historical runtime or untracked mutator; this
report does not claim a live checked-in source path.

## Tangent-fit counterfactual

The in-memory `b5ea4911` tangent fit examined 22,588 connectors and attempted /
rebuilt 427.  On `06_continuity`, it changed 3,720 heading discontinuities to
3,483 and the 53-degree bucket from 3,373 to 3,370; it is therefore not the
source-stage fix.  The existing continuity check reported 0 non-junction issues,
4,689 junction-connector issues, and 144 micro-stub heading advisories after the
fit.  The repository has no applicable in-memory self-intersection check, so
self-intersection is explicitly `NOT_MEASURED`, not passed.

## Proposed fixes (not implemented)

1. **Stage 6 containment and provenance:** do not implement a geometry repair
   yet.  First make Stage 6 fail closed on any junction-connector planView
   mutation unless its exact caller, before/after endpoint poses, and operation
   are recorded; reproduce the 05-to-06 delta against the historical runtime.
   The acceptance target for a later source-stage repair is the post-SUMO
   baseline of four 53-degree kinks.  Do not enable the tangent fit as a
   substitute.
2. **Reversed stubs:** their first stable population is Stage 2 (81), so trace
   the SUMO-repair connector producer and reject or rebuild only the 0.09-0.11 m
   single-line, reversed-heading connector at its generation point.  No threshold
   increase or final-XODR cosmetic edit is proposed.
3. **Raw converter kinks:** retain the netconvert repair in the pipeline; it
   reduces the raw 3,411 population to four.  Evaluate a converter change only
   under the separately approved X6 prototype.

Residual risk: the historical runtime trace contains operation names that conflict
with the settings snapshot and current strict-containment route.  It does not
prove either operation executed.  A full in-memory reproduction of the exact
helper call is the prerequisite to implementation.

## Execution record

Executed: report-only reciprocity checks across all eight maps; SHA-256 before
and after each read; 20 identity tracks; and in-memory tangent-fit measurement.
No CARLA session, map write, production-code edit, push, merge, or promotion was
performed.  No unit test was applicable because this change adds evidence only.
