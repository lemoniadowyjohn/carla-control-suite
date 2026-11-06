# GAP-070 characterisation — junction exits whose carriageways do not meet

**Status:** open. This file characterises GAP-070 as recorded in `GAP_REGISTER_ADDENDUM.json`/`.md`; it does not change the status.
**Input (read-only):** `reports/rq1_trial_runs/run_01/20261007_214826_524342/07_lanes_20261007_214826_524342.xodr` (untracked run output in the main checkout), sha256 `787870babc93644a8465cf32e29507fd5686b7650dd6a43ed0fd200fe05b6ba3`, unchanged before and after the analysis.
**Checker:** `ultimate_pipeline/quality/check_road_link_reciprocity.py` @ `bdc91ca3`, category `junction_exit_geometry_gap` (report-only).

## Result

The finding reproduces exactly: 207 of 4,577 junction exits, 45,176 road-road links checked, 0 gated violations.

**These are real map defects, not checker artifacts:**
- **laneOffset explains none of them:** 0 of the 207 A or B roads has a non-zero laneOffset (checked with `tools/phase_g3_cross_section._lane_offset_at`).
- **Full reconstruction doesn't shrink the gap:** rebuilding the lane-boundary polygons (`reconstruct_section`) at both touching ends gives a minimum A-to-B lane-edge distance of 6.5–14.0 m, equal to or larger than the reference-line metric. No pair overlaps or comes within 0.3 m.
- **Every affected connector is curved:** 207 of 207 connecting roads end in a `paramPoly3` primitive.
- **No junction dominates:** the 207 exits span 182 junctions (at most 3 per junction).
- **Lane IDs claim continuity the geometry doesn't deliver:** every A lane successor/predecessor resolves to an existing lane of B (207 of 207). This is the same pattern as GAP-026, but at the connector's *exit* interface.

## Two distinct mechanisms

| Group | Count | Heading difference at boundary | Excess over carriageway width | Nature |
|---|---|---|---|---|
| Tangent kink | 147 | ≈ 53.13–53.17° | 0–0.25 m | angular discontinuity; the distance threshold flags it only incidentally |
| Positional offset | 60 | 0–12° | up to 7.0 m | displacement beyond the one-way reference-line convention (~6.5 m) |

The distance-only definition used by the checker therefore conflates two mechanisms and undercounts the angular one. A future check should also test heading continuity at the boundary.

Example rows (A connecting road, B exit road, J junction):

| A | B | J | gap m | width m | lane-edge min m | heading diff ° |
|---|---|---|---|---|---|---|
| 68894 | 51267 | 3460 | 14.0 | 7.0 | 14.0 | 0.0 |
| 63199 | 44709 | 2392 | 10.5 | 6.75 | 10.50 | 0.0 |
| 68272 | 48822 | 3261 | 10.5 | 6.75 | 10.56 | 0.0 |
| 51930 | 51162 | 1009 | 7.0 | 7.0 | 7.67 | 53.13 |
| 52123 | 46059 | 1032 | 7.0 | 7.0 | 7.67 | 53.13 |

## Relation to GAP-026

- **Same defect class:** connector-geometry endpoint or tangent mismatch.
- **Different interface:** GAP-026's oracle (`GAP026_ROOT_CAUSE_AUDIT.json`) measures junction `<connection>` laneLinks, i.e. the connector's *entry*. GAP-070 is the connector's road-level link to the *exit* road, which no `<connection>` names.
- **No ID-level overlap is computable:** GAP-026 was measured on a different map snapshot (sha256 `370abbbb…`, 32,267 roads).
- **This input predates all three GAP-026 connector fixes** (`9ff56e7d` 2026-10-11, `2a886117` 2026-10-13, `b5ea4911` 2026-10-14). So this result says nothing about whether those fixes reduce GAP-070.
- **Closest existing remediation:** `b5ea4911`'s Hermite tangent fit (`ultimate_pipeline/topology/junction_connector_tangent_fit.py`, `_find_outgoing_anchor`) targets this connector-to-exit interface. It is off by default (`UP_ENABLE_JUNCTION_CONNECTOR_TANGENT_FIT`), and its >12° trigger would cover the 147-exit kink group but not the 60-exit offset group.

## Next steps (not done here)

1. Re-measure on a map regenerated with the current source stage (after the GAP-026 fixes) before treating 207 as current.
2. Add heading continuity at the junction-exit boundary to the checker (report-only first) so the angular group is counted on its own terms.
3. Decide, as a source-stage fix, whether to enable the GAP-026 tangent fit or extend it to the positional group. Raising a tolerance to make these pass is not acceptable.
