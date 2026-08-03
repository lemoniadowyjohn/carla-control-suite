# F2 — strict fallback policy evidence

- run_id: `20260803T130000Z`  - verdict: **F2_STRICT_AND_AUDIT_PASS**
- strict mode is the default; `UP_ELEVATION_FALLBACK_POLICY` may set
  `strict` | `audit` | `lenient`.

## Modes

### `strict`  — **PASS**

- resolved policy: `strict`
- roads sampled: 32710
- nodata road starts: 0
- forbidden fallback total: 0
  - KD-tree NN extrapolated: 0
  - graph propagated: 0
  - median/hardcoded: 0
  - endpoint no-data: 0
- seam suspects (>30 m): 0
- candidate sha256 unchanged: True

### `audit`  — **PASS**

- resolved policy: `audit`
- roads sampled: 32710
- nodata road starts: 0
- forbidden fallback total: 0
  - KD-tree NN extrapolated: 0
  - graph propagated: 0
  - median/hardcoded: 0
  - endpoint no-data: 0
- seam suspects (>30 m): 0
- candidate sha256 unchanged: True

## Fallback sites (code audit)

- `direct_dem`: **allowed** — apply_dem direct start-anchor sampling. DEM-derived; neighborhood eps=2.0 m around anchor only
- `direct_dem`: **allowed** — apply_dem endpoint linear-grade sampling. DEM-derived start/end anchors; slope from DEM only
- `endpoint_nodata`: **FORBIDDEN** — apply_dem endpoint no-data (linear grade). endpoint cannot be sampled -> structured violation; no flat substitution
- `flat`: **FORBIDDEN** — stage_05 flat sampler (_flat_sampler_or_raise). FAIL_ON_FLAT_ELEVATION=True raises in strict; F2 gate also flags flat sampler
- `nearest_neighbour`: **FORBIDDEN** — apply_dem KD-tree NN extrapolation (UP_ELEV_EXTRAPOLATION_MAX_DIST_M). invented z from up to 2000 m away; F2 forbidden
- `graph_propagation`: **FORBIDDEN** — apply_dem road-graph BFS propagation (5 hops). copies neighbour z; F2 forbidden
- `median`: **FORBIDDEN** — apply_dem global median fallback. median of all valid samples; F2 forbidden
- `hardcoded`: **FORBIDDEN** — apply_dem hardcoded 375.0 m constant. hardcoded Ingolstadt z; F2 forbidden

In strict mode every unavailable DEM sample becomes a structured violation; no synthetic elevation is inserted and the run raises.  In audit mode every forbidden attempt is recorded without mutating the candidate.  `collect_qc` never bypasses the F2 gate (the gate runs before the QC return).