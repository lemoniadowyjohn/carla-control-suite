# G4 — lane continuity

- run_id: `20260803T230000Z`
- verdict: **PHASE_G_LANE_CONTINUITY_PASS**

## Metrics

| metric | value |
|---|---|
| lane sections audited | 32710 |
| lane links audited | 64080 |
| missing lane-link targets | 0 |
| directionally wrong lane links | 0 |
| duplicate lane links | 0 |
| unlinked required driving lanes | 0 |
| type-incompatible lane links (advisory) | 7 |
| legitimate terminal lanes (advisory) | 11038 |

## Checks

- no_missing_lane_link_targets: PASS
- no_directionally_wrong_lane_links: PASS
- no_duplicate_lane_links: PASS
- no_unlinked_required_driving_lanes: PASS

Blocking checks: lane-link targets must resolve in the contacted lane section (contactPoint of the road-level link decides which section of the connected road is contacted), directions must respect section position, and driving lanes on non-terminal sections must declare continuation.  Per OpenDRIVE, explicit lane links override the implicit same-numbering rule, so differing lane counts at a joint are valid lane-add/drop encodings.  Junction LaneLinks are validated separately in G6; terminal driving lanes at map edges are legitimate.