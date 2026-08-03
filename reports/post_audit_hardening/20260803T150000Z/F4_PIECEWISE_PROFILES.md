# F4 — piecewise elevation profiles from DEM chains

- run_id: `20260803T150000Z`
- verdict: **F4_PIECEWISE_PROFILES_PASS**
- scipy available: True

## Stats

- roads total: 32710
- profiles replaced (piecewise cubic): 32710
- profiles deferred (fail-closed): 0
- cubic segments emitted: 418243
- DEM samples collected: 450953

## Checks

- crs_contract_verified: PASS
- candidate_source_unchanged: PASS
- road_count_preserved: PASS
- all_roads_have_profiles: PASS
- no_deferrals: PASS
- candidate_source_bytes_untouched: PASS


Each road's planView centreline was densified and sampled at 5.0 m from the COP30 DEM; a C0 piecewise cubic spline (C1 via scipy CubicSpline where available) was fitted per road.  No values were invented: roads with fewer than 2 DEM samples would be deferred.  The input candidate is byte-untouched — a new candidate file is produced and only elevationProfile content changes.