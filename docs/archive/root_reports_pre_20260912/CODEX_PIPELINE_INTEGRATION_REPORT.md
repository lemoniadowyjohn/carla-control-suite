# Production Map-Quality Integration Candidate

## Scope

This is an offline integration candidate based on release commit
`f195ba0b5d6df3f085573c5e996ff9d0f11a975f`, on branch
`integration/production-map-quality-v1-20260912`. It consolidates reviewed,
small-scope map-quality changes without changing a map artifact, the
map-of-record, frozen thesis evidence, release defaults, or any live CARLA
state.

This packet is not a production certificate and does not promote a candidate
map.

## Pipeline Wiring Verified

| Capability | Integration point | Runtime posture |
| --- | --- | --- |
| ParamPoly3 tangent-reversal repair | Stage 2 topology semantics | Transactional repair, enabled by its existing setting |
| High-confidence spatial OSM/XODR correspondence | Stage 4 enrichment | Positioned metadata is fail-closed for ambiguous/unmatched roads |
| OSM access metadata | Stage 4 enrichment | Metadata only; no invented access semantics |
| Connector pose diagnostics and snap | Stage 5 geometry | Diagnostics live; snap requires `UP_ENABLE_JUNCTION_CONNECTOR_SNAP=1` |
| OSM lane provenance and turn/cycle lane support | Stage 7 lanes | Spatially associated exact/high records now reach `LaneGenerator` |
| Cross-road lane-link validation and hardened dormant repair | Stage 8 integrity | Validation is live; repair remains opt-in |
| G6 lane-coverage repair | Stage 8 hygiene | Transactional and advisory-first; requires `UP_ENABLE_G6_LANE_COVERAGE_REPAIR=1` |
| OSM2World visual/collision QA | After structural freeze | Optional and reported as `NOT_RUN`/`BLOCKED_EXTERNAL` when unavailable |

The Stage 7 integration was verified after merge: positioned metadata is
extracted from source OSM, associated through the spatial correspondence
engine, passed as `structural_osm_meta`, and written to
`structural_osm_lane_correspondence.json` and `lane_provenance_report.json` in
a future generated candidate. Existing map lanes are only annotated when every
lane section exactly matches the sourced directional count; this integration
does not rewrite the pinned map's lane topology.

## Included Changes

The following are the direct integration and reconciliation commits, in
dependency order:

`f89baaa9`, `48520912`, `06e58bf5`, `f0383ec3`, `786ed7a7`, `9d7f9317`,
`9d8ffae2`, `358edb5c`, `fc7abcc0`, `4f5b896d`, `caec649f`, `58f066fb`,
`6f7b1c5b`, `c872a0e4`, `0ac39037`, `e6b2dd0d`, `52b589a9`, `240f41ff`,
`f54107e0`, `35b79eb1`, `44121aba`, `82d49e32`, `91ca93e4`, `713b5401`,
`395d0170`, `55cf6358`, `56add080`, `0593e4ce`, and `8421f845`.

The branch also inherits the reviewed source commits from the linear dependency
stack. The complete ordered provenance is the Git range
`f195ba0b5d6df3f085573c5e996ff9d0f11a975f..793adb5b3061a33e5ab3214c16aca4225d365ce7`
at the time this report was committed; it contains 91 commits.

They cover the canonical geometry kernel, connector validation, geometry-aware
junction lane links, spatial OSM correspondence, OSM lane provenance,
turn/cycle lanes, turn restrictions, connector/micro-stub diagnostics, G6
advisory coverage repair, semantic and junction quality checks, tangent repair,
cross-section/roadmark diagnostics, Phase-J ordering, and Stage-I test
isolation.

## Test Evidence

Focused suites executed after their respective integrations passed. The final
Stage-I isolation suite passed **14 tests** in 59.41 seconds. It now reruns the
historical crosswalk producer into a temporary output directory and asserts
that both the governed candidate XODR and historical `N10` receipt are
unchanged.

The final complete offline suite passed after the isolation and portability
fixes: **5,853 passed, 82 skipped, 0 failed** in 441.10 seconds. It collected
5,935 tests. The skipped tests remain environment/governed-artifact skips, not
passed runtime evidence. The suite emitted 133 warnings, including absent local
manual-tile, coordinate, and HPC paths plus third-party deprecations.

Two required clean-worktree repetitions also passed without source changes in
between: **5,853 passed, 82 skipped, 0 failed** in 408.24 seconds and 426.97
seconds respectively. This verifies that no test-order-dependent process or
evidence-state leakage remained in the integrated candidate.

Package smoke also passed: `python -m build` produced
`ultimate_pipeline-0.1.0-py3-none-any.whl` and
`ultimate_pipeline-0.1.0.tar.gz`. A no-system-site-packages temporary
environment installed the wheel non-editably, imported all required
`ultimate_pipeline` subpackages from its own `site-packages`, and reported
`No broken requirements found` from `pip check`. The offline smoke copied the
already-tested dependency distributions because package-index TLS validation is
unavailable in this environment; it did not import the source checkout.

## Deliberate Non-Activation

The following are intentionally not enabled by this candidate:

* Connector-pose snap. Its governed probe reduced known diagnostics but has not
  been regenerated and certified as a new map candidate.
* G6 lane-coverage repair. Its governed evidence reduced 27 isolated lane
  components to one, but the median lateral convergence was 3.5 m and the
  maximum was 7.125 m; promotion requires an explicit policy decision.
* Native signal enrichment. Its current CRS/frame relationship is unverified.
* Roundabout V2. It lacks pinned-map integration validation and independent
  review; V1/V2 defaults remain unchanged.
* Elevation graph relaxation. Its current-data comparison did not establish a
  production benefit.

## Remaining Production Blockers

`INCOMPLETE` is the correct production-candidate status. The integration does
not satisfy the approved production contract because it has no governed full
map regeneration, no unified production certificate, no second-city result,
and no required external static/runtime validation. Live CARLA is `NOT_RUN`.

The structure/elevation branch remains blocked by CRS frame alignment. Bicycle
and parking lane insertion is not implemented: source OSM data exists, but the
external OSM-to-SUMO-to-OpenDRIVE conversion did not create the lanes and a
correct repository-side insertion needs lane-section, continuity, and junction
mapping work. Semantic stages also still precede the complete target
post-structural-freeze architecture, so that broader stage migration remains
open.

## Evidence Integrity

No map-of-record or frozen evidence changes are included in the integration
commits. During full-suite verification, an existing Stage-I idempotency test
attempted to rewrite a historical report path. The change was reverted before
commit and the test was redesigned to use `UP_STAGE_I_OUTPUT_DIR`; the test
now proves the historical receipt remains unchanged.

## Review Verdict

`CONDITIONAL_FOR_INDEPENDENT_REVIEW`: the code is wired into the candidate
pipeline with destructive repairs gated off, but a release or production-map
promotion would be unsupported. The next admissible action is an independent
review followed by governed candidate generation and certification, not
activation of any opt-in repair.
