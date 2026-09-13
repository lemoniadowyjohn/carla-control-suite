# Structure-Elevation CRS Blocker Resolution

## Scope and Inputs

This investigation and probe are offline and read-only.  They neither modify
the governed XODR nor invoke CARLA.

| Input | SHA-256 |
| --- | --- |
| Ingolstadt governed OpenDRIVE | `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798` |
| Authoritative Ingolstadt OSM | `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f` |
| Ingolstadt DEM | `3cfa665dde3782a015502beaf457854db2f639d01008a386c925d171e41f4ff8` |
| Probe evidence | `2550ced006cbc61204cf319ebdc7c6f1c55f27f9b2fac6b4d8839b3ab2bd2e75` |

## Root Cause

The map's planView is local (`x=-0.815..13267.063`,
`y=-1.963..14072.621`), while its header bounds are already global
(`west=832671.61`, `east=845938.74`, `south=5458670.93`,
`north=5472743.72`).  Its header offset is `x=832671.676`,
`y=5458671.104`.  Applying that offset to the planView gives the global
header extent within sampling tolerance.

The prior F1 verifier unconditionally also applied the header offset to the
already-global header bounds, yielding a false coordinate range near
`x=1,665,343..1,678,610`, `y=10,917,342..10,931,415`.  Neither CRS could then
match OSM and it returned `UNRESOLVED/no_frame_matches_osm_source`.

The fix selects an effective frame from the internal header/planView/offset
relationship.  It uses the raw header when it matches local planView plus one
offset, and preserves the prior header-plus-offset path only when the header
itself is local.  It also passes the known OSM source through Stage 5 and
applies the header offset exactly once for spatial structure classification.

`SUMO_REPAIR_PRESERVE_FRAME=True` cannot prove what happened during this
historical map's generation.  Existing provenance describes both a global
netconvert policy and a later local, CARLA-friendly rebase.  The previous
SUMO comment treated local coordinates as inherently invalid; it has been
corrected.  Local planView plus a consistent global header offset is a valid
F1 representation.

## Test Reconciliation

The prior `test_dem_f1.py` “pinned” tests constructed synthetic headers and
used an incorrect repository-root calculation.  They did not read the
governed map or its OSM source.  The tests now use a local-planView/global-
header regression fixture, use temporary files, and explicitly exercise the
governed artifact when it is materialized.

## Fresh Real-Map Result

The repaired contract is `AMBIGUOUS` with
`both_frames_plausible;prefer_claimed_with_warning`.  Both transformations map
the effective global bounds to the OSM plausibility extent because the claimed
header is only `+proj=tmerc`, equivalent for this map to the native tmerc
frame.  This is a supported warning state, not an unresolved frame.

The gate now reaches data evaluation.  Structure classification covered 32,267
roads: 10 bridge, 164 elevated, 64 tunnel, 43 underpass, and 2 covered roads
(other classes are in the JSON evidence).  The gate evaluated 238 applicable
roads and returned `INCOMPLETE`, with 53 PASS, 88 FAIL, and 97 INCOMPLETE.
The incomplete result is intentional fail-closed behavior caused by missing
enough evaluable interior samples; the 88 failures are real recorded
bridge/elevated/tunnel plausibility findings and were not waived.

## Disposition

The false CRS blocker is fixed.  The governed map is **not** certified for
structure elevation: its genuine `INCOMPLETE` result and 88 failures require
separate map-quality investigation.  No threshold was relaxed and no map was
regenerated or promoted.

TASK_1_REPRODUCED: PASS -- prior false `UNRESOLVED/no_frame_matches_osm_source` reproduced from double-offset bounds; repaired run is `AMBIGUOUS`

TASK_2_ROOT_CAUSE: PASS -- global header bounds were offset a second time while local planView required exactly one offset

TASK_3_TEST_RECONCILIATION: PASS -- prior tests were synthetic, not governed-artifact coverage

TASK_4_DISPOSITION: FIXED -- frame selection and explicit OSM propagation corrected; no tolerance change

TASK_5_REAL_GATE_RESULT: INCOMPLETE -- 238 checked, 53 PASS, 88 FAIL, 97 INCOMPLETE

FULL_OFFLINE_TESTS: pending this branch's full-suite run

MAP_OF_RECORD_MUTATED: NO

LIVE_CARLA: NOT_RUN
