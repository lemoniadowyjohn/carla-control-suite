# C14 — RQ1 structural domain gap (auto ↔ manual), pinned pair

**RQ1:** structural differences between the automatically generated map and the manually modeled Grid0828.

## Pinned pair
- auto: `campaigns/…/candidate/ingolstadt_perception_map_of_record_20260819_160350.xodr` (sha `69b1f520…`) — 32,297 roads, 3,568 junctions, 1,495 km, ~5,686 buildings, 21,171 traffic-light objects, avg lane 3.5 m.
- manual: `campaigns/…/source/manual/Grid0828.xodr` (sha `5eaece23…`, UTM-32N) — 993 roads, 119 junctions, 53.5 km, avg lane 3.65 m.

## Scores (`DomainGapAnalyzer.compare_xodr_to_xodr`, reference = manual)
| aspect | gap [0,1] | classification |
|---|---|---|
| lane_width | **0.042** | genuine, small — directly comparable, maps agree |
| road_length | 1.00 (cap) | **scope artifact** (auto = full OSM 32.3k roads; manual = curated 993) |
| traffic_light_density | 1.00 | construction artifact |
| building_density | 0.795 | construction artifact |
| curvature | 1.00 | **measurement artifact** — auto `curvature_samples` empty (not extracted); do NOT read as a real curvature difference |
| road_type_coverage | 0.00 | manual road types ⊆ auto |

## Claim boundaries (mandatory — carried per the thesis contract)
1. **full_network_metrics ≠ local_registration_quality** — these are whole-map stat differences, not registered local geometry error.
2. **Construction artifacts, not domain gap:** road_length / traffic_light / building gaps reflect that the auto map is a full OSM+DEM+enrichment extraction while Grid0828 is a hand-modeled subset. Report WITH this caveat.
3. **curvature gap is a measurement artifact** (auto curvature not sampled) — flagged, not a finding. Follow-up: fix `XODRMapStatsExtractor` curvature sampling for the auto map, then recompute.
4. **Frame difference** (auto local-tmerc rebased vs manual UTM-32N) does not affect these stats (counts/lengths are frame-invariant); positional registration is a separate deferred step.

## Honest RQ1 answer
Where directly comparable (lane width), auto and manual **agree** (gap 0.04). The large gaps are **scope + construction method**, not a domain difference. A meaningful structural domain-gap number requires either (a) restricting the auto map to the manual map's drivable subset before comparison, or (b) reporting per-aspect with these boundaries — done here.

## Method note (defect fixed)
`DomainGapAnalyzer.compare_xodr_to_xodr` was an unimplemented `pass` stub (returned None → `ManualAutoComparator.compare_maps` crashed). Implemented via TDD (`tests/unit/test_gap_analyzer_xodr_to_xodr.py`), mirroring `.compare` with reference=ground-truth. RQ1 could not have been computed before this.

Machine-readable: `C14_RQ1_STRUCTURAL_GAP.json`, `manual_vs_auto.json`.
