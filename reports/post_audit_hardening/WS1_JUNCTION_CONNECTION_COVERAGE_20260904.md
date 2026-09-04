# Round-4 WS-1: junction-connection coverage detection + real-map measurement

Scoping plan: `C:\Users\admin\.claude\plans\velvet-wobbling-lighthouse.md` (round 4). Follow-up to
WS-H (round 3), which found that 9,350 of 32,267 roads (~29%) have a junction-typed `<link>` that
their target junction's `<connection>` list doesn't cite back, and that only 27 lanes end up
genuinely isolated (`component_reachability_summary`).

## What was built

`ultimate_pipeline/quality/check_junction_connection_coverage.py`: a read-only detector (no XML
mutation) that, for every such gap, computes the omitted road's approach pose
(`check_geometric_continuity._pose_at_s`/`_parse_geometries`) and searches the junction's existing
`connectingRoad` candidates (both ends of each) for a geometric+heading match, classifying each gap:

- **CONFIDENT** — exactly one candidate within `tolerance_m=5.0` AND `eps_hdg=0.01` rad.
- **AMBIGUOUS** — 2+ candidates pass both thresholds.
- **NO_CANDIDATE** — nothing passes.

Roundabout-classified junctions (`roundabout_reconstructor._RoundaboutDetector.detect`) are
excluded, since their connection lists are wholesale-rewritten elsewhere in the pipeline. 6 tests,
RED-verified (module absent → ImportError).

## Real-map measurement

Run against the current map-of-record candidate
(`ingolstadt_perception_map_of_record_20260904_deepaudit.xodr`):

| Classification | Count | % of gaps |
|---|---|---|
| CONFIDENT | 453 | 4.8% |
| AMBIGUOUS | 8,651 | 92.5% |
| NO_CANDIDATE | 246 | 2.6% |
| **Total gaps** | **9,350** | 100% |

Roundabout junctions skipped: 0 (no overlap with this pattern on this map). Of the 453 CONFIDENT
matches, 441 (97.4%) have a true geometric `contactPoint` that disagrees with the naive "always
start" default — concretely confirming `map_acceptance.py`'s own docstring observation that this
generator's `contactPoint` values are unreliable.

## Decisive finding: CONFIDENT matches don't rescue any of the 27 actually-isolated lanes

Per the plan's own decision gate ("this number determines whether WS-2 is worth building at all"), a
throwaway simulation (not committed — added all 453 CONFIDENT connections + naively-paired
`<laneLink>`s to a copy of the real candidate, then re-ran `component_reachability_summary()`) found:

- **Isolated lane count before: 27. After: 27. Delta: 0.**

Every CONFIDENT match is a road that already has connectivity via some other path (rescued by its
other end already) — a structurally correct but reachability-irrelevant connection. The concrete
WS-H example, road 42335 (predecessor→junction 11, no successor at all, verified zero connectivity
on either end), classifies as **AMBIGUOUS** (4 candidate connecting roads, all at essentially
`dxy≈0m, dhdg≈0rad` — they physically coincide at the junction's shared attachment point). This is
the general pattern behind the AMBIGUOUS dominance: real junctions commonly have multiple connector
roads meeting at the same physical point, which pure position+heading matching cannot disambiguate —
and it is specifically the roads with this multi-candidate-coincidence shape that tend to be the
ones actually lacking any other connectivity.

## Conclusion (per the plan's explicit stop condition)

**WS-2 (repair) is not being built.** The plan stated: "if confident matches turn out to be rare, the
honest conclusion may be 'not safely automatable,' and WS-2 stops here with an updated report, not a
forced repair." The confident count (453) isn't rare in absolute terms, but its measured impact on
the metric that actually matters (isolated-lane count) is zero — spending WS-2's real engineering
effort (new `<connection>`/`<laneLink>` construction, contactPoint handling, the
`regenerate_lane_links()` scoping fix already flagged during plan review) would not move the
drivability needle at all on this map.

Per the plan, whether to wire this checker as a permanent soft-info gate in `run_gates()`/
`build_map_acceptance()` was deferred to post-WS-1 review: **not wiring it** — as a purely diagnostic
checker whose CONFIDENT bucket doesn't correlate with real drivability impact, it would be pipeline
surface area without ongoing value. The module and its tests remain in the repo as a documented,
tested, reusable diagnostic tool for any future investigation into the AMBIGUOUS bucket (e.g. an
approach using lane-count/width compatibility or turn-topology reasoning to disambiguate coincident
candidates, which is a materially harder problem than this workstream scoped for).

## What would be needed to actually fix the 27 isolated lanes

Disambiguating the AMBIGUOUS bucket requires signal beyond position+heading at a single point —
candidates along the WS-H report's original "future investigation" line (lane-count/width matching,
turn-class/topology reasoning, or tracing which pipeline/converter stage decides connection
membership in the first place). Not scoped or started in this pass.
