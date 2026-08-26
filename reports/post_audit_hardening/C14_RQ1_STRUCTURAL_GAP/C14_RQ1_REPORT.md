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
| curvature_wasserstein | **0.074** | range-robust companion metric over absolute-curvature distributions, normalized by 0.2 1/m |
| road_type_coverage | 0.00 | manual road types ⊆ auto |

## Claim boundaries (mandatory — carried per the thesis contract)
1. **full_network_metrics ≠ local_registration_quality** — these are whole-map stat differences, not registered local geometry error.
2. **Construction artifacts, not domain gap:** road_length / traffic_light / building gaps reflect that the auto map is a full OSM+DEM+enrichment extraction while Grid0828 is a hand-modeled subset. Report WITH this caveat.
3. **curvature gap — FIXED (was a measurement artifact).** The old 1.0 came from `XODRMapStatsExtractor` collecting curvature from `<arc>` only, while both maps store curves as `<paramPoly3>` (auto had 0 arcs → empty samples). Fixed to sample paramPoly3 (+spiral) curvature at interior arc-length fractions and to drop non-physical degenerate spikes (|κ|>1.0 1/m); auto now yields 104k samples, manual 23k. New histogram-L1 gap **0.093** (native, |κ|≤1.0) plus Wasserstein absolute-curvature gap **0.074**. **Caveat:** the histogram-L1 metric is *range-sensitive* (0.093 at |κ|≤1.0, 0.25 at |κ|≤0.5) — treat it as "moderate," not a precise scalar; use the Wasserstein metric and distributional summary as the range-robust companion.
4. **Frame difference** (auto local-tmerc rebased vs manual UTM-32N) does not affect these stats (counts/lengths are frame-invariant); positional registration is a separate deferred step.

## Honest RQ1 answer
Where directly comparable (lane width), auto and manual **agree** (gap 0.04). The large gaps are **scope + construction method**, not a domain difference. A meaningful structural domain-gap number requires either (a) restricting the auto map to the manual map's drivable subset before comparison, or (b) reporting per-aspect with these boundaries — done here.

## Local registration (RQ1 refinement — crop auto to Grid0828 footprint, 2026-08-21; hardened 2026-08-26, C26)
The whole-map scores are dominated by **scope** (auto = full OSM 32,297 roads over ~13×14 km; manual = curated
~4.4×2.9 km patch). To measure a *local* structural gap, the auto map is cropped to Grid0828's geographic footprint
via CRS registration (auto bare-`+proj=tmerc` + header offset ↔ manual UTM-32N, through WGS84 lat/lon;
`ultimate_pipeline/domain_gap/local_registration.py`, TDD `tests/unit/test_local_registration.py`, 19 tests).

**C26 update (2026-08-26): footprint tightened from bounding-box to convex hull.** The original (2026-08-21)
footprint was the axis-aligned bounding box of Grid0828's planView geometry — always ≥ the true footprint in area,
since Grid0828 is not rectangular. The footprint now defaults to the **convex hull** of that same geometry (hull
area ≤ bbox area for any point set, so this can only shrink or keep-equal the cropped road/building set — never
grow it). Both are reported below side-by-side, since the hull crop changes the ratios **materially**.

**Footprint comparison — hull (default) vs. bbox (legacy):**
| metric | hull (tighter) | bbox (legacy) | reading |
|---|---|---|---|
| auto roads kept | 3,539 / 32,297 (10.96%) | 6,079 / 32,297 (18.82%) | hull excludes ~42% of the roads bbox kept |
| road_length ratio (auto/manual) | **2.69×** (144.1 km vs 53.5 km) | **4.5×** (240.8 km vs 53.5 km) | **materially lower under hull** |
| junction ratio (auto/manual) | **3.78×** (450 vs 119) | **6.05×** (720 vs 119) | **materially lower under hull** |
| road_count ratio (auto/manual) | **3.57×** (3,539 vs 993) | **6.12×** (6,079 vs 993) | **materially lower under hull** |
| lane_width_gap | 0.0415 | 0.0415 | unchanged (construction-choice metric, footprint-insensitive) |
| curvature_gap | 0.2192 | 0.2239 | ~unchanged |
| curvature_wasserstein_gap | 0.0747 | 0.074 | range-robust companion (C24); consistent with whole-map 0.074, footprint-insensitive |

**Does the 4.5–6× road-network finding still hold? Partially — direction yes, magnitude no.** Under the tighter
hull footprint the ratios drop to **~2.7–3.8×** (from 4.5–6.1× under bbox). The *qualitative* finding is unchanged
and, if anything, more defensible: even in the geometrically-tightest footprint that actually contains Grid0828,
the auto map still has **~2.7–3.8× the road length/junctions/road-count** — a genuine road-network-completeness gap,
not a bbox-corner artifact (the bbox's corner regions, which the hull rightly excludes, were padding the auto-side
counts with roads outside Grid0828's real extent). The magnitude claim in the original 2026-08-21 report ("4.5–6×")
should be read as the **bbox-footprint number**; the hull-footprint number (**~2.7–3.8×**) is now the primary,
more accurate figure. Both are retained in `local_registration.json` (`hull` / `bbox` top-level blocks) rather than
overwriting one with the other.

**Finding (updated):** even within the *tightest defensible same-area footprint* the auto map has **~2.7–3.8× the
road length/junctions/road-count** of Grid0828 — a genuine **road-network-completeness** domain gap: OSM captures
every service road/driveway/footway, while the hand-modeled Grid0828 contains only the *drivable* network. This
remains the real RQ1 structural gap the whole-map view obscured as a 28× scope artifact; the hull crop shows the
earlier 4.5–6× figure was itself inflated by ~35-45% from bbox over-inclusion, not that the gap is an artifact.
Lane widths still agree (0.04); curvature differs more locally (0.22, footprint-insensitive between hull/bbox).

**Buildings — C26 update: RECOVERABLE and now included (previously excluded).** The 2026-08-21 report excluded
buildings because the auto map's 5,686 buildings are all attached to one *container* road at s=0/t=0, so a
road-centroid crop always zeroed them out. Investigation (C26) found each building `<object>` carries a full
absolute-position `<outline><cornerGlobal x y z/></outline>` polygon — independent of the s=0/t=0 road attachment —
so buildings ARE spatially croppable once collected map-wide instead of per-container-road
(`collect_building_objects`, `building_global_centroid`, `crop_buildings_to_polygon` in `local_registration.py`).

A second, independent bug was found and fixed while wiring this up: the auto map's building `cornerGlobal` points
are NOT in the same local frame as its road planView geometry, despite both notionally being "local meters".
`ultimate_pipeline/enrichment/osm_polygon_loader.py` projects OSM building lon/lat via
`+proj=tmerc +lat_0=<OSM bbox lat_min> +lon_0=<OSM bbox lon_min> +x_0=0 +y_0=0`, a *different* tmerc origin than
the road network's bare-`+proj=tmerc` (lat_0=lon_0=0) + header `<offset>` frame — on the pinned pair the two origins
are offset by **(+6547.4, +6368.8) m**. Without correcting for this, every building's centroid lands far outside
any real footprint and 100% get cropped out regardless of footprint shape (verified: this was the actual behavior
before the fix — 0/5,686 kept under both hull and bbox). `building_frame_shift_to_auto_local()` recovers the
correction by projecting the OSM bbox's `(lon_min, lat_min)` through the auto map's own bare-tmerc + offset
pipeline (mirrors how the manual-map footprint is itself registered); `compute_local_registration(...,
building_frame_shift="auto")` resolves it from `ultimate_pipeline.config.settings.SETTINGS.load_gps_bounds()` by
default. This coordinate-frame bug lives in the building-enrichment step (`osm_polygon_loader.py` /
`building_extruder.py`), not in the crop logic itself — flagged here as a real, previously-undetected defect,
out of scope to fix at the source for this task (RQ1 measurement, not enrichment-pipeline surgery).

**Building density, in-footprint (frame-corrected):**
| metric | hull | bbox |
|---|---|---|
| auto buildings kept | 3,779 / 5,686 (66.5%) | 5,232 / 5,686 (92.0%) |
| manual (Grid0828) buildings | 993 | 993 |
| auto buildings / km | 26.23 | 21.72 |
| manual buildings / km | 18.55 | 18.55 |
| `building_density_gap` | 0.414 | 0.171 |

**Finding:** both maps now show comparable, plausible building density once correctly cropped and frame-aligned
(auto ~1.2–1.4× manual per km) — a real, moderate density difference rather than the artificial 1.0-cap "excluded"
placeholder from the 2026-08-21 report. Reported here as `building_density_comparison`, not excluded.

**Excluded (construction layer, not road structure): traffic-lights only.** Grid0828 does not model traffic lights
at all (0, whole-map), so there is nothing in-footprint to compare against — this is a modeling-choice difference,
independent of croppability (auto models 2,194 in-footprint under hull / 3,920 under bbox). Reported at whole-map
level.

**Claim boundary:** the *ratios* are the interpretable signal; the raw `DomainGapScores` road_length/tl gaps cap at
1.0 and conflate construction with structure. Crop rule = road/building kept if its (frame-corrected) centroid is
inside the footprint polygon (boundary roads balance out). Machine-readable: `local_registration.json` (now has
`hull` and `bbox` top-level blocks, both populated, plus `source_files` sha256 provenance).

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
The Wasserstein absolute-curvature gap is **0.074**, which is the range-robust scalar cited beside
the legacy histogram-L1 value.

Machine-readable: `curvature_recompute.json`.

## Method note (defect fixed)
`DomainGapAnalyzer.compare_xodr_to_xodr` was an unimplemented `pass` stub (returned None → `ManualAutoComparator.compare_maps` crashed). Implemented via TDD (`tests/unit/test_gap_analyzer_xodr_to_xodr.py`), mirroring `.compare` with reference=ground-truth. RQ1 could not have been computed before this.

Machine-readable: `C14_RQ1_STRUCTURAL_GAP.json`, `manual_vs_auto.json`.
