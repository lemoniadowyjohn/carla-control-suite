# Stage I - Packaged map evidence

## Verdict: `I_PACKAGED_MAP_EVIDENCE_PRODUCED`

## Package
- artifact: `candidate_g_semantic_enriched.xodr` (enriched semantic candidate)
- LF-text SHA-256: `d604ac393e12730ed276f5c865d0ef82c8a537b97bd8d79beeddd4c96863e470`
- raw-bytes SHA-256: `8b60d8f428c7cdaca9d907963dbf89665df3584168a74805f66af86e63ce8cf4`

## Semantic inventory (packaged)

| category | count |
| --- | --- |
| signals | 3467 |
| signal_references | 0 |
| controllers | 0 |
| objects | 0 |
| crosswalk_objects | 0 |
| speed_limits | 0 |
| road_types | 32710 |
| road_markings | 84781 |
| lane_change_permissions | 0 |
| turn_lane_semantics | 32040 |
| stop_yield_controls | 0 |
| sidewalks | 17392 |
| pedestrian_lanes | 0 |
| traffic_light_actor_bindings | 0 |
| semantic_material_classes | 0 |

## Equivalence
- packaged vs governed payload: **SEMANTIC_EQUIVALENCE_PASS**
- packaged vs repaired parent: SEMANTIC_EQUIVALENCE_FAIL (diffs = restored signal/speed/turn layer)

## Residual PERCEPTION_RELEASE gaps
- crosswalk_objects: OSM authority 174, packaged 0 — MISSING (blocker)
- pedestrian_lanes: OSM authority 78, packaged 0 — MISSING (blocker)

## Live runtime requirements unmet
- CARLA server binary not present in this environment; packed-map actor bindings and live perception sensor captures (L9/L10) cannot be produced until the server is available.