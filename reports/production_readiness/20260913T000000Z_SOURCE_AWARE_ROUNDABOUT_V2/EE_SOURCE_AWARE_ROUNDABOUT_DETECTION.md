# EE Source-Aware Roundabout V2 Detection

## Scope

This offline probe evaluated a copy of the governed Ingolstadt map. It did not
start CARLA, write the source map, promote a candidate, or enable Roundabout V2
in a release profile.

The detector starts from explicit source OSM `junction=roundabout` and
`junction=circular` ways. It projects their geometry into the XODR local frame,
then reuses the correspondence engine's cached 25 m grid and canonical
OpenDRIVE geometry samples. A source way becomes an `OSM_SPATIAL` candidate
only when at least two XODR roads have at least 70% sample coverage within 5 m,
mean sample distance no greater than 4 m, membership in a junction cluster,
and aggregate source coverage of at least 75% within 8 m. All other source
ways are excluded with a reason.

## Governed Inputs

| Input | SHA-256 |
| --- | --- |
| copied Ingolstadt XODR | `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798` |
| authoritative Ingolstadt OSM | `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f` |

## Result

The source contained 135 explicit roundabout ways. Projection completed for
all 135. The fail-closed detector accepted 97 `OSM_SPATIAL` candidates and
excluded 38: 19 `insufficient_supported_roads`, 15
`no_spatial_road_support`, and 4 `insufficient_source_coverage`.

The complete deterministic record, including every source way, candidate road
set, junction cluster, evidence values, and thresholds, is in
`EE_SOURCE_AWARE_ROUNDABOUT_DETECTION.json`.

V2 model analysis classified 90 candidates as `PRESERVED_VALID`, four as
`PRESERVE_ORIGINAL`, and three as `RECONSTRUCT_GEOMETRY`. This is not a
production acceptance result: the top-level V2 transactional API presently
produces diagnostics on an XML clone but does not apply the proposed
reconstruction. Consequently the acceptance delta is `NOT_RUN`, and no
pipeline wiring was performed.

## Performance And Safety

On the governed copy, source-aware detection took 17.244919 s; model analysis
took 4.068715 s; and transactional diagnostics took 6.446319 s. The source XML
tree digest was identical before and after probing. Live CARLA status is
`NOT_RUN`.

The full offline suite completed on this clean candidate worktree with 5,914
passed and 82 skipped tests in 398.64 seconds; there were no failures. The
captured stdout log SHA-256 is
`97bac53f41b12b5226a6e89070ad21b4fe35a4510a9a4ce5eded012ecd86146a`.

## Review Boundary

This commit fixes the prior zero-detection evidence gap. It does not establish
that any of the three proposed reconstructions should be applied. A future
integration task must first make top-level reconstruction materialize a fully
validated candidate map and compare pre/post structural acceptance metrics.
