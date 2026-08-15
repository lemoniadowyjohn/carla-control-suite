# C0 Clean Regen Status

Verdict: `PARTIAL_CANDIDATE_PRODUCED_NOT_PINNED`

## Summary

C0 produced a fresh offline-regenerated auto candidate from the tracked authoritative OSM and DEM, then repaired the G19 length invariant with the governed C3 repair rule. The candidate is crash-safe and offline-preflight clean, but it is not eligible for C1 pinning because geometric continuity fails and signal enrichment is absent.

## Candidate

- Repaired output: `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_clean_regen_crashsafe_20260815.xodr`
- Repaired output sha256: `83418373f1996c6707293c5571b2798f9cf7c06a5b243e8d049848efdc73080e`
- Pre-repair parent: `C:\tmp\c0_clean_regen_offline_lanes_20260815\pipeline_out\C0_CLEAN_REGEN_OFFLINE_LANES\08_final_C0_CLEAN_REGEN_OFFLINE_LANES_laneSectionFixed_lane_successor_fixed.xodr`
- Pre-repair parent sha256: `53bcf5ec5281bb7a1427d841f021e79e9f7865ee959f67a252491f81e3799b7a`
- Candidate artifact is intentionally not committed.

## Inputs

- OSM: `campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm`
- OSM sha256: `b9e074656f744c31e6aabb0a16e6b2246824ca74e202ea2c316ff7f22364f24f`
- DEM: `cities/ingolstadt/dem/dem_ing.tif`
- DEM sha256: `3cfa665dde3782a015502beaf457854db2f639d01008a386c925d171e41f4ff8`
- Seed XODR sha256: `f02fe381a2c9be9db81b3c7dc0fdf094d8f8225e2b3413c0fe97f2ce6b382075`
- Manual CRS reference sha256: `5eaece230e02f6c1b2075db851894870790e86ac64710abb3465bcfc533e9b0c`
- Pipeline commit used by the run manifest: `3085e522d61d4e425580384999dc2ba619257b3a`

## Passing Evidence

| Check | Result |
| --- | --- |
| Roads | `32297` |
| Junctions | `3568` |
| Objects | `46112` |
| Non-positive geometries | `0` |
| Driving lane widths | `n=34316`, min/median/mean/max `3.5/3.5/3.5/3.5 m`, six-metre count `0` |
| Sidewalk widths | `n=19390`, min/median/mean/max `2.0/2.0/2.0/2.0 m` |
| Elevation records | `32297`, all non-zero |
| Elevation range | `361.85043..408.671165 m` |
| G19 length invariant | `867 -> 0` violations after C3 repair |
| Lane successor invariant | `10565 -> 0` unresolved after autofix |
| Offline preflight | `status=ok`, `0` errors, `134` warnings |
| Strict validator | `0` errors in crash-safe repair report |
| Elevation seams | `ok=true`, p95 jump `0.163555 m`, max jump `2.464225 m` |

## Blocking Evidence

| Blocker | Evidence | Impact |
| --- | --- | --- |
| Geometric continuity fails | `27193` offending segments; seam p95 `288.7118704883217 m`; seam max `4666.076853696104 m`; heading p95 `2.773059480574232 rad`; heading max approximately pi | C1 pinning must fail closed until root cause is repaired or the checker is proven invalid for this stage. |
| Post-tiling integrity fails | `09_tiling__geometric_continuity.json`, `09_tiling__geometric_continuity_tiles.json`, and `09_tiling__post_tiling_integrity.json` all report `ok=false` | Downstream B4/cook must not consume this as the map of record. |
| Signal enrichment absent | `signals=0`, `signal_references=0` | Does not satisfy the enriched-map target and is not comparable to prior enriched candidates with thousands of signals. |
| Widths fixed but not varied | All driving lanes are `3.5 m`; six-metre placeholder is gone, but road-class variation is not present in the final artifact | C5 is materially improved, but the width-fidelity story is still weaker than the policy intent. |
| Preflight warnings remain | `134` warnings, all `road_length_mismatch` | Crash-safe and preflight-ok, but warning-clean status is not achieved. |
| Run did not complete naturally | Wrapper was stopped in the optional `domain_gap` stage; `run_status.json` still says `running`; no `c0_provenance.json` was written | Provenance must be completed before any pinning attempt. |

## Acceptance Wiring Finding

The run's original `map_acceptance.json` said `valid_for_experiments=true`, but it only consumed origin and elevation reports. After this finding, `map_acceptance` was patched to consume geometric-continuity decision reports and lane-successor autofix reports. Rebuilding acceptance from the C0 artifacts now correctly produces:

- `valid_for_experiments=false`
- `failed_gates=["geometric_continuity"]`
- reason: `27193 offending segments exceed continuity thresholds`

## Next Required Fixes

1. Repair or adjudicate geometric continuity before C1.
2. Restore/enforce signal enrichment in clean regeneration.
3. Produce a complete provenance artifact from a run that exits cleanly, not from a stopped optional stage.
4. Decide whether the constant `3.5 m` driving width is acceptable as a controlled policy or whether road-class variation must be preserved into the final XODR.

## Scope

- No certifier gate verdict was changed.
- No CARLA/live certification run was performed.
- No map artifact was committed.
- ESCALATE_TO_CLAUDE: geometric continuity root cause, missing signals, and whether this crash-safe repaired candidate can be used only as a diagnostic artifact.
