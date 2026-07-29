# FV02 Map Quality Baseline

Generated: 2026-07-29T22:08:06.986665+00:00

Reviewed source SHA: `6d11a973202ed9039e21b4d93e914bce0632ec18`

No map-changing repair was executed by this verification. Metrics below compare recovered external artifacts only.

## Structural Metrics

| metric | p2_parent | p3_accepted |
| --- | --- | --- |
| road_count | 5399 | 4999 |
| junction_count | 672 | 645 |
| laneLink_count | 3859 | 3658 |
| invalid_junction_refs | 3 | 0 |
| invalid_road_refs | 0 | 0 |
| zero_length_planview | 0 | 0 |
| position_seams_over_5cm | 4447 | 0 |

Interpretation: p3 removes invalid junction references and planView position seams, but also loses 400 roads, 27 junctions, and 201 LaneLinks relative to p2. This is not counted as an unqualified current-code improvement.
