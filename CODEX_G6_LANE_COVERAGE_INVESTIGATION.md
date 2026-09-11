# G6 Lane-Coverage Investigation

## Result

The current map-of-record has **135** G6 `missing_driving_from_coverage`
gaps and zero missing `to` coverage gaps. Of the acceptance graph's 27
singleton driving lanes, **26** are actual G6 coverage gaps. The only
unexplained singleton is `51767:0:-2`.

On a copy only, G6 added 126 junction laneLinks, resolved all G6 audit
defects, and changed the acceptance graph as follows:

| Metric | Source | G6 copy |
|---|---:|---:|
| Driving lanes | 34,291 | 34,291 |
| Components | 35 | 4 |
| Isolated lane components | 27 | 1 |
| Largest component fraction | 0.996734 | 0.998104 |
| Unmatched cross links | 0 | 0 |

This directly falsifies the earlier assumption that the existing G6 technique
could not affect the 27 singleton components. The earlier conclusion was
based on a different repair mechanism; it is not rewritten or discarded.

## Five Structural Inspections

Five repaired singleton-lane cases were inspected manually from the original
laneLink topology and evaluated planView endpoint poses. Each adds an outer
lane to a connector path already used by its adjacent lane. Endpoint gaps are
at most `6.14e-07 m`, normalized heading differences are zero to floating
point tolerance, and both the uncovered and adjacent lanes have 3.5 m widths.

The inspected incoming roads are `46778`, `46783`, `46891`, `46923`, and
`47062`; full road/junction/connector details are in the JSON evidence.

This is a **PASS_OFFLINE_STRUCTURAL** sanity check, not live CARLA validation
and not proof that all 126 additions encode intended real-world turns.

## Boundary

No pipeline stage was wired. The pinned map-of-record was SHA-256 verified
unchanged before and after the experiment. The repaired XODR exists only in
the external candidate directory identified and hashed in the JSON evidence.
No CARLA process, RPC, vehicle, or sensor was used.

## Recommendation

Request an independent adversarial review of the 126-link candidate, including
the 121 repairs not represented by the five inspected examples. That review
should decide whether a future implementation must be component-targeted;
until then, do not wire G6 into a production profile or promote the candidate.

CURRENT_MAP_COVERAGE_GAPS: 135 missing_driving_from_coverage, 0 missing_driving_to_coverage

GAP_TO_ISOLATED_ROAD_OVERLAP: 26 of 27 isolated lane nodes are explained by a G6-class gap

REPAIR_ISOLATED_COUNT_DELTA: 27 -> 1, on a copy only

SEMANTIC_SANITY_CHECK: PASS_OFFLINE_STRUCTURAL -- five endpoint/tangent/width and existing-neighbour-route inspections passed

RECOMMENDATION: independent adversarial review of the 126-link candidate; do not wire or promote it

FULL_OFFLINE_TESTS: UNVERIFIED
