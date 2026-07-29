# Stage 6 containment report

Date: 2026-07-29

Objective: contain unsafe Stage 6 geometry mutation in governed release and thesis profiles. No replacement repair heuristic was introduced.

## Verdict

PASS for containment scope:

- Governed Stage 6 runs use `READ_ONLY_DIAGNOSTIC`.
- Release/thesis profiles cannot enable the unsafe flags.
- Unsafe env overrides fail validation instead of being silently accepted.
- Straight-chord connector fallback is blocked by default with `BLOCKED_CONNECTOR_RECONSTRUCTION`.
- Stage 6 containment requires exact protected XODR semantic equality.

## Unsafe operations discovered

| Operation | Active | Configuration flag | Default | Release/thesis value | Mutation domains | Call count | Output artifact | Rollback | Tests |
|---|---:|---|---:|---:|---|---:|---|---|---|
| `PlanViewSmoother.smooth_heading_jumps` | observe-only in governed; mutating only experimental | `ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING` | false | false | `planView.geometry.@hdg` | 1 | `stage6_containment_runtime.json` proposals | input copied unchanged | `test_stage6_containment.py`, `test_stage6_unsafe_flag_policy.py` |
| `PlanViewSmoother.merge_small_geometries` | observe-only in governed; mutating only experimental | `ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE` | false | false | geometry list, segment length, `road.length` | 2 | diagnostic proposals | parent `planView` untouched | `test_stage6_containment.py` |
| `PlanViewSmoother.merge_short_segments` | observe-only in governed; mutating only experimental | `ENABLE_UNSAFE_SHORT_SEGMENT_MERGE` | false | false | geometry list, segment length, `road.length` | 2 | diagnostic proposals | parent `planView` untouched | `test_stage6_containment.py` |
| `PlanViewSmoother.clamp_curvature` | observe-only in governed; mutating only experimental | `ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP` | false | false | `arc.@curvature` | 1 | diagnostic proposals | curvature not written | `test_stage6_containment.py` |
| `PlanViewSmoother.recompute_geometry_starts` | observe-only in governed; mutating only experimental | `ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE` | false | false | geometry `x/y/hdg` | 3 | diagnostic proposals | legacy recompute flag rejected outside experimental | `test_stage6_containment.py`, `test_stage6_unsafe_flag_policy.py` |
| `MeshContinuityRepairer.run` | diagnostic scan only in governed | Stage 6 containment + `CONTINUITY_MODE` | `moderate` globally | `READ_ONLY_DIAGNOSTIC` | geometry starts/headings/chain rewrite | 1 | `continuity_debug.json` | `geo_out` copied to `cont_out` | `test_stage6_containment.py` |
| plan-view seam auto-repair | disabled in governed | `ENABLE_PLANVIEW_SEAM_AUTO_REPAIR` | false under release profile | false | geometry starts/headings | 0 | seam report only outside governed path | not invoked | `test_stage6_containment.py` |
| straight-chord connector fallback | blocked by default | `ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK` | false | false | connector `planView`, connector `road.length` | 1 | connector rebuild/risk reports | original connector preserved | `test_junction_connector_rebuild.py` |

## Observe-only mode

Governed Stage 6 now writes `stage6_containment_runtime.json` with `READ_ONLY_DIAGNOSTIC` entries. Each proposed mutator record includes:

- affected road
- geometry index
- old value
- proposed value
- reason
- predicted endpoint displacement
- predicted tangent change
- dependent records affected

The governed path copies the input XODR to Stage 6 outputs and does not write proposed mutations.

## Release-profile enforcement

Central settings added:

- `ENABLE_UNSAFE_SHORT_SEGMENT_MERGE = False`
- `ENABLE_UNSAFE_SMALL_GEOMETRY_MERGE = False`
- `ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING = False`
- `ENABLE_UNSAFE_CURVATURE_ONLY_CLAMP = False`
- `ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE = False`
- `ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK = False`

Policy:

- `STRUCTURAL_RELEASE`, `CARLA_RELEASE`, `VISUAL_RELEASE`, and `PERCEPTION_RELEASE` reject attempts to enable these.
- `THESIS_STRICT=True` also rejects attempts to enable these and forces Stage 6 containment.
- Development mutation use requires `RELEASE_PROFILE=EXPERIMENTAL_UNSAFE` and `THESIS_STRICT=False`, plus the specific unsafe flag.
- The effective flag values are included in `Settings.to_dict()` for immutable settings snapshots.

## XODR semantic changes

Containment mode requires exact equality for:

- `planView`
- `road.length`
- `elevationProfile`
- `lateralProfile`
- `lanes`
- `junctions`
- `LaneLinks`
- `signals`
- `objects`

If protected semantic equality fails, Stage 6 raises `BLOCKED_STAGE_ORDER_VIOLATION`.

## Connector fallback protection

When tangent-compatible connector construction fails, the rebuild code now reports:

```text
BLOCKED_CONNECTOR_RECONSTRUCTION
```

It preserves the original connector road and reports junction/road IDs in `blocked_connector_candidates`.

## Regression fixtures

Added coverage for:

- Line followed by Arc
- Arc followed by Line
- short Line between two Arcs
- short Arc between Lines
- mixed primitive chain
- heading discontinuity
- valid sharp corner
- junction connector that would previously use a straight chord
- geometry with dependent elevation, lateral, lane, signal, and object records

## Tests

Command run:

```text
python -m pytest tests/unit/test_stage6_unsafe_flag_policy.py tests/unit/test_stage6_containment.py tests/unit/test_junction_connector_rebuild.py ultimate_pipeline/tests/test_contracts.py tests/unit/test_geometric_continuity_migration.py -q --tb=short
```

Result:

```text
123 passed, 32 warnings
```

Warnings were existing missing-path warnings for `COORDINATES_JSON` and `HPC_DIR`.

## Remaining mutators

- Non-governed `EXPERIMENTAL_UNSAFE` can still invoke `PlanViewSmoother` mutators when individual flags are enabled.
- Non-governed Stage 6 can still run `MeshContinuityRepairer` mutation modes.
- ParamPoly3 connector rebuild can still write a verified arc when tangent-compatible construction succeeds.
