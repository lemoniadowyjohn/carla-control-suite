# Geometry Evaluation Caller Contracts

## Purpose
Document how each evaluation function handles out-of-range `s` (negative, beyond length) and what guarantees callers provide.

## Contract Types
- **STRICT_RANGE** — function raises error / asserts if `s` out of [0, length]
- **CLAMP_TO_SEGMENT** — function (or caller) clamps `s` to [0, length]
- **ALLOW_EXTRAPOLATION** — function silently accepts out-of-range `s`
- **Endpoints only** — function always evaluates at full geometry length (no variable `s`)

## Evaluator Contract Matrix

| # | File | Function | Contract | EPS | Details |
|---|------|----------|----------|-----|---------|
| 1 | `opendrive_geometry/primitives.py` | `evaluate_line` | **STRICT_RANGE** | 1e-12 | Raises `GeometryOutOfRangeError` |
| 2 | `opendrive_geometry/primitives.py` | `evaluate_arc` | **STRICT_RANGE** | 1e-12 | Raises `GeometryOutOfRangeError` |
| 3 | `geometry/geometry_math.py` | `_integrate_line` | **ALLOW_EXTRAPOLATION** | 1e-9 | No bounds check; `get_endpoint()` passes XML length |
| 4 | `geometry/geometry_math.py` | `_integrate_arc` | **ALLOW_EXTRAPOLATION** | 1e-9 | Same; endpoint always in range |
| 5 | `quality/check_geometric_continuity.py` | `_pose_line` | **CLAMP_TO_SEGMENT** | 1e-12 | Clamped by caller `_pose_at_s` before dispatch |
| 6 | `quality/check_geometric_continuity.py` | `_pose_arc` | **CLAMP_TO_SEGMENT** | 1e-12 | Same caller clamp |
| 7 | `tile_validation/geometry_seam_checker.py` | `_geometry_endpoint` | **Endpoints only** | 1e-12 | Always uses full geometry length |
| 8 | `geometry/lane_seam_checker.py` | `_sample_geometry` | **In-range by construction** | 1e-9 | Loops `i/n` fractions of length |
| 9 | `domain_gap/elevation_gap.py` | `_sample_line` | **ALLOW_EXTRAPOLATION** | 1e-12 | Accepts arbitrary `t_values`; callers pass (0.0, 0.5, 1.0) |
| 10 | `domain_gap/elevation_gap.py` | `_sample_arc` | **ALLOW_EXTRAPOLATION** | 1e-12 | Same |
| 11 | `domain_gap/geo_alignment.py` | `_sample_transformed_geometry_points` | **In-range by construction** | 1e-12 | Hard-coded t = (0.0, 0.5, 1.0) |
| 12 | `visualization/map_plotter.py` | `_sample_geometry` | **In-range by construction** | implicit | Loops `range(0, int(length)+1, int(step))` |
| 13 | `quality/check_dem_full_coverage.py` | `_sample_line` | **CLAMP_TO_SEGMENT (upper)** | 1e-9 | `s = min(length, i*step)` |
| 14 | `quality/check_dem_full_coverage.py` | `_sample_arc` | **CLAMP_TO_SEGMENT (upper)** | 1e-9 | Same |
| 15 | `topology/junction_connector_rebuild.py` | `_arc_endpoint` | **Endpoints only** | 1e-12 | Always uses computed arc length |
| 16 | `visualization/lane_overlay.py` | `_endpoint` | **Endpoints only** | implicit | Always uses XML length |
| 17 | `visualization/heatmap_generator.py` | `_endpoint` | **Endpoints only** | implicit | Same |
| 18 | `visualization/map_diff.py` | `_sample_geometry` | **In-range by construction** | 1e-9 | Loops `i/n` fractions of length |

## Key Findings
1. **Only canonical `primitives.py` uses STRICT_RANGE** — all production implementions either clamp, are in-range by construction, or silently extrapolate.
2. **6 functions are "endpoints only"** — they have no variable `s` parameter at all.
3. **5 sample_geometry variants** generate s internally via evenly-spaced steps; always in range.
4. **elevation_gap** silently accepts arbitrary t-values from callers; currently always (0.0, 0.5, 1.0) in practice.
5. **check_geometric_continuity.py** is the only caller-level clamp; `_pose_line`/`_pose_arc` rely on `_pose_at_s` for bounds.

## Implication for Near-Zero Curvature Boundary
At k=1e-12, the `<=` vs `<` EPS check affects only elevation_gap and geo_alignment. All other non-buggy implementations use `<` (canonical) or have no EPS branch (R-based/local-frame). The heading discrepancy is bounded by `abs(k)*s ≤ 1e-10` at s=100, negligible for all production callers.
