# Codex — PROMPT BB: root-cause the F1 CRS blocker on structure-elevation

## Context

`structure-elevation-v1-20260907` (real, tested, now merged into
`integration/session-batch1-20260912`) added a Stage-5 quality gate
(`check_structure_elevation_plausibility.py`) that checks bridges/elevated roads stay above terrain
and tunnels stay below, using DEM sampling. Its own evidence file is explicit that the pinned
Ingolstadt measurement is `INCOMPLETE`: `verify_crs_contract()` (in
`ultimate_pipeline/dem/dem_crs_contract.py:343`) returns `verdict=UNRESOLVED,
reason=no_frame_matches_osm_source` before structure classification or DEM sampling can even begin.

Read `verify_crs_contract()` directly: it checks TWO candidate frames -- the XODR's own claimed
`geoReference` CRS, and the "osm2odr native" CRS -- against OSM ground-truth bounds. If NEITHER
frame's transformed bbox falls inside the expected OSM area, it fails closed with exactly this
reason.

Found what looks like the exact, already-documented explanation, sitting in a comment in
`ultimate_pipeline/topology/sumo_repair.py:55-62`:

```
# F1 CRS contract: keep geometry in the Osm2Odr-native global tmerc(0,0)
# frame. By default netconvert normalizes node positions to a local origin
# (offset ~832671, ~5458671 for Ingolstadt), silently moving geometry off
# the frame the downstream DEM sampler requires -> it then fails closed
# (no_frame_matches_osm_source) and no elevation can be imported. Disable
# normalization so the round-trip preserves the input frame.
if bool(getattr(SETTINGS, "SUMO_REPAIR_PRESERVE_FRAME", True)):
    cmd += ["--offset.disable-normalization", "true"]
```

`SUMO_REPAIR_PRESERVE_FRAME` defaults to `True`, meaning this fix should already be active. Yet the
pinned map still fails the SAME check with the SAME reason string. Also notable: `test_dem_f1.py`'s
own unit tests (`TestResolveSamplingCrs::test_resolves_to_osm2odr_native_for_pinned_candidate`, etc.)
ALL PASS in isolation (verified this session, 13/13) -- meaning the CRS-resolution *logic* itself is
correct against its own test fixtures. The contradiction (logic tests pass, but the real map fails)
was not resolved this session -- that is exactly the gap this prompt exists to close.

## PROMPT BB

```text
Repository: lemoniadowyjohn/carla-control-suite. Base branch: integration/session-batch1-20260912
(NOT fix/post-audit-phase-e-junctions-roundabouts-20260803 -- this branch has the structure-elevation
code already merged, use it as your starting point). Isolated branch:
feature/structure-elevation-crs-blocker-v1-<date>.

TASK 1: reproduce the blocker fresh. Run verify_crs_contract() directly against the real pinned
map-of-record (campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr)
and its real OSM source (campaigns/ingolstadt_cooked_perception_v1/source/). Print every intermediate
value the function computes on the way to its verdict: header_bounds_raw, bounds_source (header vs
planView), header_offset, header_bounds (with offset applied), geometry_bounds_with_offset, osm_bounds,
the expanded plausibility box, claimed_crs + claimed_wgs84 + claimed_plausible, native_crs +
native_wgs84 + native_plausible. Confirm the verdict is still UNRESOLVED/no_frame_matches_osm_source
on the CURRENT map -- do not assume the evidence file from 2026-09-07/09-11 is still accurate, verify
fresh.

TASK 2: explain the numbers from Task 1. Specifically determine: does the pinned map's actual
geometry sit at the netconvert-normalized LOCAL origin sumo_repair.py's comment warns about
(~832671, ~5458671 for Ingolstadt), or somewhere else entirely? Was SUMO_REPAIR_PRESERVE_FRAME=True
actually in effect when this specific pinned map was generated/last regenerated -- check the map's own
generation provenance/report if one exists, don't just assume. If the frame genuinely was preserved
and it STILL doesn't resolve, the sumo_repair.py comment's explanation is incomplete and you need to
find the real second cause (e.g. a later pipeline stage that re-normalizes, or the OSM bounds
computation itself being wrong for this specific source file).

TASK 3: reconcile with test_dem_f1.py's passing tests. Confirm whether those tests exercise
verify_crs_contract() with synthetic/mocked bounds (making them validate the LOGIC correctly, but not
representative of the real map's real numbers) or with the real pinned files. State plainly which is
true -- this determines whether "the unit tests pass" was ever meaningful evidence that the real map
would resolve.

TASK 4: fix the real root cause you find in Task 2, OR if it turns out to be a genuine, structural
data gap that can't be fixed without regenerating the map from scratch (e.g. the map-of-record was
built before SUMO_REPAIR_PRESERVE_FRAME existed), say so explicitly and do not force a workaround that
just changes the CRS contract's tolerance to paper over it -- that would defeat the fail-closed design
this session has repeatedly protected elsewhere (G3's repair_road_lengths margin, G6's transactional
repair, etc.). A genuine "this needs a fresh regen with the fix already active" conclusion is an
acceptable, honest outcome.

TASK 5: if fixed, re-run check_structure_elevation_plausibility.py's real gate against the pinned map
and report its actual verdict (structure count checked, any implausible bridges/tunnels found) --
this is the number the original branch's evidence file explicitly could not produce.

Do not mutate the map-of-record or any frozen evidence. Run the full offline test suite before and
after.

End with:
TASK_1_REPRODUCED: <verdict + all intermediate values>
TASK_2_ROOT_CAUSE: <exact explanation, with the real numbers, not a guess>
TASK_3_TEST_RECONCILIATION: <synthetic vs real, stated plainly>
TASK_4_DISPOSITION: FIXED | GENUINE_DATA_GAP_NEEDS_REGEN (with reasoning either way)
TASK_5_REAL_GATE_RESULT: <verdict, or "not reached" if Task 4 is GENUINE_DATA_GAP_NEEDS_REGEN>
FULL_OFFLINE_TESTS: PASS | FAIL
MAP_OF_RECORD_MUTATED: NO
```
