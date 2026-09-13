# Roundabout V2 Real-Map Validation

## Scope

This is an offline, advisory-only validation of the opt-in V2 candidate.  It
does not alter the map-of-record, enable a pipeline feature, or contact CARLA.

| Input | SHA-256 |
| --- | --- |
| Governed Ingolstadt OpenDRIVE copy | `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798` |
| Governed Ingolstadt source OSM | `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f` |
| Machine-readable result | `02a1f8579bb0a1f9419b3140eb45fac6025dc9fb189aa3974015e2dd53cb1294` |

## Call Sequence

`roundabout_v2_real_map_probe` parses a copy of the XODR, calls
`RoundaboutV2Reconstructor.analyze(root)`, then calls
`reconstruct_transactional(root)` and hashes the original XML tree before and
after.  The latter API only clones and diagnoses the root; it does not apply a
reconstruction.  This is intentional for the current opt-in candidate.

## Results

The source OSM contains 135 ways tagged `junction=roundabout` out of 17,250
ways.  The converted XODR has 32,267 roads and 3,561 junctions, but V2 found
zero candidates, produced zero diagnostics, and therefore reconstructed zero
roundabouts.  The copied XODR file SHA and the source-tree SHA were unchanged.

V2's current detector requires either a V2-specific `userData` junction marker
or at least three arc/spiral roads attached to a junction.  No compatible
marker, arc, or spiral geometry appears in this map.  Thus this is a source
correspondence/detection coverage gap, not evidence that 135 real
roundabouts are absent.

`measure_candidate_acceptance.py` was not run: there is no V2-modified map to
compare.  Running an acceptance comparison on an unchanged clone would create
a misleading zero-delta result.

## Decision

V2 remains **NOT_WIRED**.  It is not appropriate to add an advisory pipeline
switch when its real-map detector is currently a no-op.  The next engineering
change must be source-aware, spatially matched OSM-to-XODR roundabout detection
with real-map coverage and fail-closed ambiguity handling; it must not enable
the present detector by default.

TASK_1_DRIVER_BUILT: PASS -- `analyze` followed by non-mutating `reconstruct_transactional`

TASK_2_REAL_MAP_RESULTS: 0 candidates / 0 reconstructed / 0 rejected; no diagnostics because detection found none

TASK_3_ACCEPTANCE_DELTA: not reached -- no reconstructable candidates

TASK_4_WIRING_DECISION: NOT_WIRED -- 135 source OSM roundabouts but zero V2 candidates in the converted XODR

TASK_5_FULL_OFFLINE_TESTS: pending this branch's full-suite run

MAP_OF_RECORD_MUTATED: NO

LIVE_CARLA: NOT_RUN
