# FOUNDATION-01A — Integration Proposal: OpenDRIVE Line & Arc Evaluator

## Deliverables

| Artifact | Path | Status |
|----------|------|--------|
| Data types (Pose2D, Vec2, Bounds2D, etc.) | `opendrive_geometry/model.py` | Done |
| Errors | `opendrive_geometry/errors.py` | Done |
| Line + Arc evaluators | `opendrive_geometry/primitives.py` | Done |
| ReferenceLineEvaluator Protocol | `opendrive_geometry/evaluator.py` | Done |
| Analytical tests (56 cases) | `tests/unit/test_opendrive_geometry_line_arc.py` | 56/56 pass |
| Cross-comparison benchmark | `opendrive_geometry/cross_compare_implementations.py` | Done |
| **This proposal** | `FOUNDATION-01A_INTEGRATION_PROPOSAL.md` | Done |

## Cross-Comparison Results

Against **7 existing implementations** across 20 diverse test cases:

| Implementation | EPS | Max Δx | Max Δy | Max Δh | Verdict |
|---|---|---|---|---|---|
| geometry_seam_checker | 1e-12 | 0 | 0 | 0 | **Full match** |
| local_frame (check_geometric_continuity) | 1e-12 | ~0 | ~1e-14 | 0 | **Floating-point match** |
| lane_seam_checker | 1e-9 | 0 | 0 | 5e-9 | EPS boundary diff |
| geometry_calculator (geometry_math) | 1e-9 | 7e-15 | ~0 | 5e-9 | EPS boundary diff |
| elevation_gap | 1e-12 (≤) | 7e-15 | ~0 | 5e-11 | `≤` vs `<` diff |
| geo_alignment | 1e-12 (≤) | 7e-15 | ~0 | 5e-11 | `≤` vs `<` diff |
| map_plotter | sentinel 1e9 | **95.5** | **29.6** | 0 | **Bug: k=0 returns start** |

### Key Findings

1. **All implementations use the same underlying math**. The canonical form `(sin(h)-sin(h0))/k` for x and `(cos(h0)-cos(h))/k` for y is universal.

2. **EPS threshold divergence**: Implementations use 1e-9, 1e-12, or 1e-12 with `<=`. Our evaluator uses `abs(curvature) < 1e-12` (strict `<`, tightest practical bound). When `|k|` falls between 1e-12 and 1e-9, implementations disagree about whether to use arc vs line fallback. These are differences of **policy, not mathematics**.

3. **Floating-point noise** (local_frame): The local-frame formula `dy_local = (1-cos(k*s))/k` vs canonical `(cos(h0)-cos(h0+k*s))/k` produces ~1e-14 differences in y for large arcs. Negligible for any practical purpose.

4. **Confirmed bug in map_plotter.py**: Using a sentinel radius (`R=1e9 when k=0`) instead of line fallback returns the start point unchanged for zero-curvature arcs. **Must be fixed** when integrating.

5. **map_diff.py** (not tested numerically) uses a fundamentally broken arc formula (`hdg += theta * curvature * abs(R)` is dimensionally wrong). Not included in benchmark as it's explicitly marked "very rough, visually ok".

## Integration Plan

### Phase 1: Adopt the authoritative evaluator

Replace all inline `_integrate_line`/`_integrate_arc` calls with calls to `opendrive_geometry.primitives`. Each file gets a single-line import:

```python
from opendrive_geometry.primitives import evaluate_line, evaluate_arc
```

Files to refactor (in priority order):

| Priority | File | Lines | Pattern |
|----------|------|-------|---------|
| HIGH | `geometry/geometry_math.py` | 80-116 | `GeometryCalculator` — the intended authoritative source, should delegate |
| HIGH | `tile_validation/geometry_seam_checker.py` | 28-55 | Inline formula, R-based |
| HIGH | `quality/check_geometric_continuity.py` | 98-117 | Local-frame formula |
| HIGH | `geometry/lane_seam_checker.py` | 25-61 | Inline formula, R-based |
| HIGH | `tile_validation/lane_seam_checker.py` | 70-107 | Inline formula, R-based |
| HIGH | `quality/autofix_postprune_elevation.py` | 81-97 | Local-frame, no heading |
| MEDIUM | `topology/junction_connector_rebuild.py` | 225-239 | Local-frame |
| MEDIUM | `domain_gap/elevation_gap.py` | 133-161 | Canonical |
| MEDIUM | `domain_gap/geo_alignment.py` | 37-66 | Canonical |
| MEDIUM | `quality/check_dem_full_coverage.py` | 13-34 | Canonical |
| LOW | `visualization/lane_overlay.py` | 58-83 | Endpoint only |
| LOW | `visualization/heatmap_generator.py` | 55-84 | Endpoint only |
| LOW | `visualization/map_plotter.py` | 32-61 | **BUGGY** sentinel radius |
| SKIP | `visualization/map_diff.py` | 47-66 | Broken by design, visual-only |

### Phase 2: Standardize EPS threshold

Unify all implementations to `EPS = 1e-12` (strict `<`). This matches the tightest existing bound (`geometry_seam_checker.py`) and avoids the 1e-9 vs 1e-12 ambiguity.

### Phase 3: Fix confirmed bugs

- **map_plotter.py**: Replace `R = 1.0/k if k != 0 else 1e9` with proper line fallback.
- **map_diff.py**: Either delegate to `evaluate_arc` or document as visual-only and skip.

### Phase 4: Extend evaluator (future batch)

Per lifecycle rules, this batch does NOT implement Spiral, Poly3, or ParamPoly3. The next batch (FOUNDATION-01B) should:

1. Add `evaluate_spiral(..., curv_start, curv_end)` — Fresnel integral
2. Add `evaluate_poly3(..., a, b, c, d)` — cubic polynomial in road frame
3. Add `evaluate_parampoly3(...)` — parametric cubic in uv frame
4. Implement `ReferenceLineEvaluator` dispatch `pose_at(segment, s)` → routes to correct primitive
5. Implement `project()` — Newton-Raphson lateral projection for all primitive types

## Regression Gates

Before merging any integration commit, run:

```bash
pytest ultimate_pipeline/tests/unit/test_opendrive_geometry_line_arc.py -v
# Expected: 56/56 pass

python opendrive_geometry/cross_compare_implementations.py
# Expected: no regressions against existing code
```

## Files NOT Modified (Lifecycle Compliance)

- Any `<junction>` or `<laneLink>` logic
- Elevation/height profile computation
- CARLA Python API interaction, tick ownership, sensor calibration
- Scientific metrics (domain gap, IoU, curvature gap)
- Visual assets or report generation
- `main_pipeline.py` or pipeline orchestration
