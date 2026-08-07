# Stage G - Perception-strict semantic completeness

## Verdict: `SEMANTIC_CONTENT_PARTIAL`

The repaired candidate had lost the accepted Phase H signal layer (0 signals).
Rather than pasting XML, the governed enrichment phase was replayed onto the
repaired parent using the same OSM authority, matcher, writers, integrity
audit, and idempotency gate.

## Replay result
- Parent: `campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_fixed_final.xodr`
- Output: `reports/post_audit_hardening/20260807T000000Z/candidate_g_semantic_enriched.xodr`
- Verdict: `PHASE_H_REPLAY_PASS` (idempotent, integrity clean)
- Signal restoration: 0 -> **3467** (exact ID-set match to accepted Phase H output; total difference = 0)

## Structure preservation (repaired parent vs replayed enriched)
| element | parent | enriched |
|---|---|---|
| road | 32710 | 32710 |
| junction | 3646 | 3646 |
| laneSection | 32710 | 32710 |
| lane | 84781 | 84781 |
| geometry | 80261 | 80261 |
| elevationProfile | 32710 | 32710 |
| elevation | 32710 | 32710 |
| roadMark | 84781 | 84781 |
| elevation hash | `ad7e38e1...` | `ad7e38e1...` (identical) |

## Semantic inventory (enriched candidate)
- signals: 3467 (3309 type-1, 158 zone type-2)
- speed elements: 3828 (governed <speed> records replacing legacy layer)
- turn-lane userData vectors: 212
- road_markings: 84781, sidewalks: 17392, road_types: 32710, turn_lane_semantics: 32040

## Authoritative OSM source evidence
- maxspeed ways: 4350; turn:lanes ways: 333; traffic_sign tagged ways: 529
- traffic_signal nodes: 0, stop nodes: 0, give_way nodes: 0 (authority-proven zero for controllers/stop-yield/traffic-lights)
- crosswalk footways: 174, sidewalk footways: 398, pedestrian ways: 78

## Remaining perception-release blockers
| category | source authority | current state | disposition |
|---|---|---|---|
| crosswalk_objects | 174 footway=crossing in OSM | 0 in XODR | SEMANTIC_CONTENT_MISSING (blocker) |
| pedestrian_lanes | 78 pedestrian ways in OSM | 0 in XODR | SEMANTIC_CONTENT_MISSING (blocker) |

## Profile verdicts
- STRUCTURAL_XODR -> FAIL (package-dependent categories are not validated late in structural profile; signals/structural content present)
- PACKAGED_MAP -> FAIL (crosswalk_objects, pedestrian_lanes missing)
- PERCEPTION_RELEASE -> FAIL (crosswalk_objects, pedestrian_lanes missing)

Crosswalks and pedestrian lanes require packaged-map actor/material binding
(Stage I packaged map) before PERCEPTION_RELEASE can pass.
