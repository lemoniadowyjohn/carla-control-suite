# H — Semantic enrichment (signals/controllers)

- run_id: `20260804T050000Z`
- verdict: **PHASE_H_SIGNAL_ENRICHMENT_PASS**
- CRS contract: `OSM2ODR_NATIVE_VERIFIED`
- output: `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\reports\post_audit_hardening\20260804T050000Z\candidate_h_signal_enrichment.xodr`

## H6 counters

| bucket | value |
|---|---|
| ambiguous | 1671 |
| legacy_speed_removed | 52071 |
| matched | 2589 |
| matched_roads | 4314 |
| requested.controller | 0 |
| requested.speed_limit | 4333 |
| requested.turn_lanes | 333 |
| requested.zone_sign | 318 |
| speed_limits.conflicts_rejected | 40 |
| speed_limits.roads_updated | 3309 |
| speed_limits.signals_inserted | 3309 |
| speed_limits.skipped_existing | 0 |
| speed_limits.speeds_inserted | 3771 |
| turn_lanes.rejected_lane_mismatch | 29 |
| turn_lanes.roads_updated | 212 |
| turn_lanes.skipped_existing | 11 |
| unmapped | 724 |
| zone_signs.roads_updated | 158 |
| zone_signs.signals_inserted | 158 |
| zone_signs.skipped_duplicate | 2 |
| zone_signs.skipped_existing | 0 |
| zone_signs.skipped_unprovenanced | 0 |
| zone_signs.speeds_inserted | 57 |

## Fixtures

| fixture | result |
|---|---|
| fixture_clean_speed_idempotent | PASS |
| fixture_zone_sign | PASS |
| fixture_turn_lanes | PASS |
| fixture_turn_mismatch_rejected | PASS |
| fixture_integrity_negatives | PASS |

idempotent: **True**

## Integrity (H5)

- duplicate_ids: 0
- out_of_s: 0
- out_of_t: 0
- unknown_type: 0
- unknown_subtype: 0
- invalid_validity: 0
- unresolved_refs: 0
- duplicate_spatial: 0
- missing_provenance: 0
- non_governed_prefix: 0

## Identity freeze

- planview_hash: PASS
- road_length_hash: PASS
- elevation_profile_hash: PASS
- road_link_hash: PASS
- junction_structure_hash: PASS
- connector_geometry_hash: PASS
- contactpoint_hash: PASS

- G4 lane continuity on enriched file: PHASE_G_LANE_CONTINUITY_PASS

Controllers: the authoritative OSM contains no traffic_signals / stop / give_way nodes; requested=0 and reported N/A with evidence.

The enriched candidate enters Phase I (tiling strategy) with the protected identity hashes identical to the G0 baseline.