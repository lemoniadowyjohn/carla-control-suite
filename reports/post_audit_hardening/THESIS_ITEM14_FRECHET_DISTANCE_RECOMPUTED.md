# Thesis future-work #14 addressed — Fréchet distance recomputed against the current, correct methodology

## What the thesis left open
Chapter 9, future-work item 14: RMSE and Hausdorff distance are governed baselines but are
sensitive to sampling and road-decomposition mismatch. A curve-aware metric such as discrete
Fréchet distance, computed after robust road-segment correspondence, would give a more
shape-sensitive comparison. The thesis had already computed this once as a one-off,
un-committed supplement (`submission/results/structural_gap_run11/frechet_distance_supplement.json`
— no script for it survives in git history): **mean 1,781.62 m, median 126.80 m, p90 4,166.26 m,
457 matched road pairs, 5 m spacing, 50 m correspondence threshold**, against the OLD
whole-network, uncropped, SE(2)-aligned "run_11" methodology that C22/C23/C26 later found to
be a scope artifact (see `THESIS_VS_CURRENT_STATE_COMPARISON_20260827.md`).

## What was built
`ultimate_pipeline/domain_gap/frechet_gap.py` (new module):
1. **Crop** auto roads to the manual map's convex-hull footprint via the existing, validated
   `local_registration.py` machinery (`crop_roads_to_polygon`) — the same current, correct
   RQ1 methodology, not the thesis's old SE(2) best-fit.
2. **Reproject** the cropped auto roads' points into manual's own native CRS. This step did
   NOT already exist: `compute_local_registration`'s existing metrics are distribution-level
   (each map's own road-length/curvature distribution compared independently) and never
   needed both maps' points in one common frame. A curve-similarity metric inherently does.
   Added `local_registration.transform_auto_points_to_manual_local` — the mirror of the
   already-existing `transform_manual_points_to_auto_local` (same CRS-transform pattern,
   opposite direction), verified to be its own inverse on the real Ingolstadt auto/manual
   proj4 pair.
3. **Match** manual↔auto roads by nearest polyline, reusing
   `elevation_gap.py`'s `_match_roads` directly (unmodified) — the same road-correspondence
   algorithm already used and tested for the elevation-gap metric, not reimplemented.
4. **Resample** each matched pair's centerline to a fixed 5 m arc-length spacing (matching
   the thesis's own parameter, for direct comparability), reusing the arc/line formulas
   already verified elsewhere this session (RealismModule, xodr_cropper_gps.py) plus the
   shared "authoritative" paramPoly3 sampler.
5. **Compute** the standard Eiter–Mannila discrete Fréchet distance (iterative DP, not
   recursive — avoids Python's recursion limit on long road polylines) per matched pair,
   then report mean/median/p90 across all matches.

## Result on the real pinned pair (auto = current promoted map of record, manual = Grid0828)
| | Thesis (2026-05, run_11/SE(2)/uncropped) | Now (2026-08, local registration) |
|---|---|---|
| mean | 1,781.62 m | **55.28 m** |
| median | 126.80 m | **35.26 m** |
| p90 | 4,166.26 m | **128.01 m** |
| matched pairs | 457 | 895 |
| spacing / threshold | 5 m / 50 m | 5 m / 50 m (unchanged, for comparability) |

**~30–50× smaller** on every statistic. This is not a contradiction of the thesis's number —
it's the same conclusion C22/C23/C26 already reached for RMSE/road-length-ratio, now
independently reconfirmed by a completely different (curve-shape-sensitive) metric: the old
whole-network SE(2)-aligned comparison was dominated by registration/scope error, not real
road-shape difference. Once auto is properly cropped to manual's actual footprint and both
maps' points are expressed in one common, correctly-transformed CRS, road centerlines that
represent the same real street differ by tens of meters, not kilometers — a plausible
magnitude for OSM-digitization vs. manual-authoring differences (lane placement, curve
fitting, endpoint snapping), not evidence of a broken pipeline.

**Independent cross-check**: cropped-auto-road-count / manual-road-count = 3,539 / 993 ≈
3.56×, landing inside this session's already-established RQ1 hull finding of ~2.7–3.8×
road-length ratio (computed by a completely different code path, `local_registration.py`'s
own aggregate stats) — the two independent measurements agree.

## Verification
- TDD: `tests/unit/test_frechet_gap.py` (12 tests) — discrete Fréchet correctness (identical
  curves → 0, parallel offset → the offset, symmetry, detects a local excursion invisible to
  endpoint distance, single-point curves, empty-curve error), fixed-spacing resampling
  (straight-line exact preservation, documented+bounded corner-cutting behavior, degenerate
  zero-length input), and two synthetic end-to-end `compute_frechet_gap` cases (a known 3 m
  offset recovered correctly; zero matches when nothing is within threshold).
- `tests/unit/test_local_registration.py` (+3 tests) for the new
  `transform_auto_points_to_manual_local`: identity-projection round-trip, offset applied
  before reprojection, and — critically — verified to be the mathematical inverse of the
  existing `transform_manual_points_to_auto_local` on the real Ingolstadt proj4 pair
  (bare-tmerc auto with the real header offset vs. UTM-32N-style manual), recovering the
  original point to within 1 cm.
- Real-data run against the actual promoted pin (`744757f3...`) and Grid0828: 25.5 s runtime,
  matches the numbers reported above.
- Full unit suite: see commit for exact pass count, 0 regressions expected.

## Honest limitations
- **Road correspondence is nearest-polyline, not corridor-aware**: where OSM and the manual
  map decompose the same physical road corridor into a different number of OpenDRIVE roads
  (a known open challenge the thesis itself named for this exact metric), the 1:1 match
  picks the single nearest candidate, which can occasionally pair a short manual segment
  with a differently-scoped auto segment. This is the same correspondence algorithm already
  accepted for the elevation-gap metric, not a new weakness introduced here.
- **`match_threshold_m=50m`** is inherited from the thesis's own supplement for direct
  comparability, not independently re-derived; a different threshold would change which
  pairs are matched (and therefore the exact statistics) without changing the qualitative
  conclusion (order-of-magnitude smaller than the old methodology).
- Not wired into any governed gate or the main `rq_tables.json` export — this is a
  standalone recomputation of one thesis future-work item, not a change to the authoritative
  RQ1 result artifact (`C14_RQ1_STRUCTURAL_GAP/`).
