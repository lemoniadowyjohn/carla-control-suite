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
| curvature | **0.093** (0.09–0.27, range-sensitive) | **REAL, fixed** — was a 1.0 artifact (auto samples empty). Now paramPoly3-sampled; maps broadly agree on curvature scale/tail (see Curvature note) |
| road_type_coverage | 0.00 | manual road types ⊆ auto |

## Claim boundaries (mandatory — carried per the thesis contract)
1. **full_network_metrics ≠ local_registration_quality** — these are whole-map stat differences, not registered local geometry error.
2. **Construction artifacts, not domain gap:** road_length / traffic_light / building gaps reflect that the auto map is a full OSM+DEM+enrichment extraction while Grid0828 is a hand-modeled subset. Report WITH this caveat.
3. **curvature gap — FIXED (was a measurement artifact).** The old 1.0 came from `XODRMapStatsExtractor` collecting curvature from `<arc>` only, while both maps store curves as `<paramPoly3>` (auto had 0 arcs → empty samples). Fixed to sample paramPoly3 (+spiral) curvature at interior arc-length fractions and to drop non-physical degenerate spikes (|κ|>1.0 1/m); auto now yields 104k samples, manual 23k. New gap **0.093** (native, |κ|≤1.0). **Caveat:** the histogram-L1 metric is *range-sensitive* (0.093 at |κ|≤1.0, 0.25 at |κ|≤0.5) — treat as "moderate," not a precise scalar; the robust comparison is the distributional summary below.
4. **Frame difference** (auto local-tmerc rebased vs manual UTM-32N) does not affect these stats (counts/lengths are frame-invariant); positional registration is a separate deferred step.

## Honest RQ1 answer
Where directly comparable (lane width), auto and manual **agree** (gap 0.04). The large gaps are **scope + construction method**, not a domain difference. A meaningful structural domain-gap number requires either (a) restricting the auto map to the manual map's drivable subset before comparison, or (b) reporting per-aspect with these boundaries — done here.

## Curvature (RQ1 refinement — paramPoly3 sampling fix, 2026-08-21)
`XODRMapStatsExtractor._collect_curvatures` previously read `<arc>` only; both maps store curves
as `<paramPoly3>`, so the auto map yielded 0 samples and the gap capped at 1.0. Fixed via TDD
(`tests/unit/test_map_stats_curvature.py`, 7 tests) to sample paramPoly3+spiral curvature at
interior arc-length fractions (0.25/0.5/0.75) and to exclude non-physical degenerate segments
(|κ|>1.0 1/m, radius <1 m; 0.1% of auto samples — a single κ=37 spike otherwise collapses the
histogram range and fakes a ~0 gap).

**Distributional summary (|κ|, 1/m — the range-robust comparison):**
| stat | manual Grid0828 | auto 69b1f520 |
|---|---|---|
| samples | 22,959 | 104,007 |
| median | 0.0150 | 0.0045 |
| mean | 0.0360 | 0.0271 |
| p95 | 0.121 | 0.142 |
| max | 0.646 | 0.996 |

**Finding:** both maps are low-curvature-dominated and agree on curvature *scale and tail*
(mean/p95 close). The auto map has a lower *median* curvature because Osm2Odr subdivides
near-straight roads into many low-curvature paramPoly3 segments, so its bulk sits nearer 0. A
genuine, interpretable structural nuance — consistent with the lane-width agreement (0.04), not a
domain gap. The scalar histogram-L1 gap (0.09–0.27, range-sensitive) is reported as "moderate"
with this distributional detail rather than as a precise number, per claim-boundary discipline.

Machine-readable: `curvature_recompute.json`.

## Method note (defect fixed)
`DomainGapAnalyzer.compare_xodr_to_xodr` was an unimplemented `pass` stub (returned None → `ManualAutoComparator.compare_maps` crashed). Implemented via TDD (`tests/unit/test_gap_analyzer_xodr_to_xodr.py`), mirroring `.compare` with reference=ground-truth. RQ1 could not have been computed before this.

Machine-readable: `C14_RQ1_STRUCTURAL_GAP.json`, `manual_vs_auto.json`.
