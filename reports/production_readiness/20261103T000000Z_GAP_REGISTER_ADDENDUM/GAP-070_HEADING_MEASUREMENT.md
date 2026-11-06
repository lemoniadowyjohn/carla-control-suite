# GAP-070 follow-up — junction-exit heading discontinuities (map-wide)

**Checker:** `ultimate_pipeline/quality/check_road_link_reciprocity.py` @ `bbabe38c`, new report-only category `junction_exit_heading_discontinuity` (threshold `EXIT_HEADING_DISCONTINUITY_DEG = 30.0`, an audit-proposed default awaiting operator sign-off; never to be raised to reduce the count).
**Input (read-only):** `reports/rq1_trial_runs/run_01/20261007_214826_524342/07_lanes_20261007_214826_524342.xodr` (untracked run output in the main checkout), sha256 `787870babc93644a8465cf32e29507fd5686b7650dd6a43ed0fd200fe05b6ba3`, unchanged. This map predates the GAP-026 connector fixes (`9ff56e7d`, `2a886117`, `b5ea4911`).

## Result

- **3,720 structurally backed junction exits** have a direction-aware heading difference above 30° between the connecting road's end and the exit road's start.
- **Overlap with the 207 `junction_exit_geometry_gap` exits: 147.** The other 60 are positional-only, matching `GAP-070_CHARACTERIZATION.md` exactly.
- **Distribution:**

  | Heading difference | Exits |
  |---|---|
  | 50–60° | **3,391** (≈ 53.13°, i.e. atan(4/3)) |
  | 30–50° | 49 |
  | 60–170° | 169 |
  | 170–180° | 111 |

  The four buckets sum to 3,720. An earlier version of this file said 157 for 60–170°; that was a summing error.

## The measurement is not a kernel artifact

In 80 randomly sampled exits, the geometry kernel's boundary heading matched a finite-difference heading (sampled points 5 cm apart, or a quarter of the primitive length if shorter) within 1° in 79 cases. The finite-difference re-computation reproduced the reported difference in 79 of 80 (e.g. 53.13° reported vs 53.25° by finite differences; the 0.12° is the step size).

Primitive pairs at the boundary in that sample:
- 78: connecting road ending in `paramPoly3`, exit road starting with a `line`;
- 2: `line` to `line`.

## Interpretation

- **The ~53° population is systematic.** Thousands of exits share the same angle, so this is a generator-level property of the connector `paramPoly3` end tangent, not random noise. It is the GAP-026 connector-tangent class, at the connector's exit interface.
- **The closest existing remediation** is the Hermite tangent fit from `b5ea4911` (`ultimate_pipeline/topology/junction_connector_tangent_fit.py`, `_find_outgoing_anchor`). It is off by default (`UP_ENABLE_JUNCTION_CONNECTOR_TANGENT_FIT`), and its >12° trigger covers this population.
- **The 111 exits at 170–180° are mostly degenerate stubs, not a checker error.** Read-only classification of all 111 (and of the 169 at 60–170°):
  - **Checker direction-convention error: ruled out.** All involved A and B roads have right-hand lanes only, where the slot/contactPoint convention equals the lane travel direction. A lane-side-aware recompute flips 0 of the 280.
  - **Mislinked exit: ruled out for 170–180°.** The A-to-B positional gap is 0.000 m for all 111.
  - **Genuine U-turn connectors: about 10%.** A's own start-to-end heading change is ≥ 90° in 11 of the 111.
  - **Dominant, a 4th mechanism: near-zero-length connector stubs.** These are a single straight line of about 0.1 m whose constant heading is reversed ~180° from the exit road, although their end coincides exactly with B's start. That covers 73% (81/111) of the 170–180° group and 18% (30/169) of the 60–170° group. It is rare elsewhere: 2% at 30–50°, 0.1% at 50–60°, and 0.85% (191 of 22,588) of all junction connecting roads map-wide. This points to a source-stage stub-generation defect (reversed tangent on a collapsed connector), distinct from the 53° `paramPoly3` class.

## Next steps (operator decisions, not done here)

1. Regenerate the map with the current source stage and re-measure. The GAP-026 fixes may already change these counts.
2. Decide whether to enable the GAP-026 tangent fit by default, as a source-stage fix. Raising the threshold to make these pass is not acceptable.
3. Find where ~0.1 m reversed connector stubs are generated (source stage) and whether they should be dropped or re-oriented there.
