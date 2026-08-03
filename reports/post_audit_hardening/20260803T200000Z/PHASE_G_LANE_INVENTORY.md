# G1 — lane inventory and schema normalization

- run_id: `20260803T200000Z`
- verdict: **PHASE_G_LANE_INVENTORY_PASS**

## Counts (counting ambiguity resolved)

| metric | value |
|---|---|
| roads | 32710 |
| lane sections | 32710 |
| lane records | 84781 |
| unique lane keys (road,section_s,lane) | 84781 |
| driving lane records | 34674 |
| driving lane length (m) | 1723120.739 |
| roads with driving lanes | 32652 |

## Schema checks

- duplicate_lane_section_s: PASS
- lane_sections_ordered: PASS
- center_lane_present: PASS
- duplicate_lane_ids_within_section: PASS
- no_invalid_center_lane_id_zero_usage: PASS
- lane_types_valid: PASS

A unique lane key is the triple (road_id, laneSection start s, lane_id).  Lane type inventory per road/section is recorded in the JSON evidence (`per_road_summary`).