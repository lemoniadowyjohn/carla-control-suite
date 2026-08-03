# F2 — strict fallback policy evidence

- run_id: `20260803T120000Z`  - status: **PASS**
- policy mode: `lenient` (default strict; invented values raise)

## Candidate DEM pass (collect-only, candidate untouched)

- roads sampled: 32710
- nodata road starts: 0
- roads with any fallback kind: 0
  - KD-tree NN extrapolated: 0
  - graph propagated: 0
  - median/hardcoded: 0
- seam suspects (>30 m): 0
- sampler frame: `projected` (source `osm2odr_native_verified`, F1 verdict `OSM2ODR_NATIVE_VERIFIED`)

## Fallback sites (code audit)

- `direct_dem`: **allowed** — apply_dem direct start-anchor sampling. DEM-derived; neighborhood eps=2.0 m around anchor only
- `direct_dem`: **allowed** — apply_dem endpoint linear-grade sampling. DEM-derived start/end anchors; slope from DEM only
- `flat`: **FORBIDDEN** — stage_05 flat sampler (_flat_sampler_or_raise). FAIL_ON_FLAT_ELEVATION=True raises in strict; F2 gate also flags flat sampler
- `nearest_neighbour`: **FORBIDDEN** — apply_dem KD-tree NN extrapolation (UP_ELEV_EXTRAPOLATION_MAX_DIST_M). invented z from up to 2000 m away; F2 forbidden
- `graph_propagation`: **FORBIDDEN** — apply_dem road-graph BFS propagation (5 hops). copies neighbour z; F2 forbidden
- `median`: **FORBIDDEN** — apply_dem global median fallback. median of all valid samples; F2 forbidden
- `hardcoded`: **FORBIDDEN** — apply_dem hardcoded 375.0 m constant. hardcoded Ingolstadt z; F2 forbidden

Strict policy: `UP_ELEVATION_FALLBACK_POLICY` defaults to `strict`; any forbidden fallback raises RuntimeError with the road ids.  The candidate pass above produced zero invented elevation values.