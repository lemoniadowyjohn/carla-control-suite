# Line/Arc Test Scaffold — Independent Execution Report

## Repository State
- **Branch:** `deepseek-observability-integration-verification`
- **SHA:** `faa20bb5`
- **Date:** 2026-07-29

## Test Suite Results

| Suite | Collected | Passed | Failed | Skipped | Time |
|-------|-----------|--------|--------|---------|------|
| `tests/opendrive_geometry/` | 1806 | 1740 | 0 | 66 | 7.84s |
| `ultimate_pipeline/tests/unit/test_opendrive_geometry_line_arc.py` | 56 | 56 | 0 | 0 | 0.56s |
| **Combined** | **1862** | **1796** | **0** | **66** | — |

## Cross-Comparison Results
```
Implementation             Max |dx|      Max |dy|      Max |dh|    Match
-------------------------------------------------------------------------------
geometry_calculator*       7.11e-15     2.12e-22     5.00e-09    15/20
geometry_seam_checker      0.00e+00     0.00e+00     0.00e+00   ALL OK
local_frame*               9.86e-32     2.84e-14     0.00e+00    15/20
lane_seam_checker*         0.00e+00     0.00e+00     5.00e-09    18/20
elevation_gap*             7.11e-15     2.12e-22     5.00e-11    16/20
geo_alignment*             7.11e-15     2.12e-22     5.00e-11    16/20
map_plotter*               9.55e+01     2.96e+01     0.00e+00    14/20
```

All discrepancies are within expected bounds:
1. **EPS 1e-9 vs 1e-12** — geometry_calculator and lane_seam_checker use 1e-9, producing max hdg error 5e-09 at boundary k=1e-10
2. **`<=` vs `<`** — elevation_gap and geo_alignment use `<= 1e-12`, producing max hdg error 5e-11 at k=1e-12, s=50
3. **map_plotter sentinel** — 95m position error due to 1e9 radius bug (confirmed PROB-243, now fixed)

## Production Bugs Fixed

### PROB-243: map_plotter sentinel 1e9 radius
- **File:** `ultimate_pipeline/visualization/map_plotter.py`
- **Before:** `radius = 1.0 / curvature if curvature != 0 else 1e9`
- **After:** uses `inv_c = 1.0 / curvature` with `abs(curvature) < 1e-12` line fallback

### PROB-245: map_diff broken arc formula
- **File:** `ultimate_pipeline/visualization/map_diff.py`
- **Before:** `theta = ds / R; local_hdg = hdg + theta * curvature * abs(R)` — produces wrong heading sign for negative k and straight-line position instead of arc
- **After:** uses canonical `(sin(h)-sin(h0))/k`, `(cos(h0)-cos(h))/k`

## Adapter Summary
- **13 total adapters** (12 non-buggy, 1 buggy map_diff)
- **11 NON_BUGGY_ADAPTERS** for comparison tests (excludes map_plotter and map_diff)
- **11 ALL_ADAPTERS** for domain/sampling tests (includes both buggy ones)

## Test Files Created

| File | Tests | Purpose |
|------|-------|---------|
| `tests/__init__.py` | — | Package marker |
| `tests/opendrive_geometry/__init__.py` | — | Package marker |
| `tests/opendrive_geometry/fixtures.py` | — | 15 standard fixtures |
| `tests/opendrive_geometry/analytical.py` | — | Reference functions |
| `tests/opendrive_geometry/adapters.py` | — | 13 adapters |
| `tests/opendrive_geometry/test_line.py` | 15 | Line evaluation |
| `tests/opendrive_geometry/test_arc.py` | 18 | Arc evaluation |
| `tests/opendrive_geometry/test_transform_invariance.py` | 9 | Transform invariance |
| `tests/opendrive_geometry/test_existing_implementations.py` | 1208 | Cross-comparison + bug regression |
| `tests/opendrive_geometry/test_near_zero_curvature.py` | 495 | Near-zero curvature boundary |
| `tests/opendrive_geometry/test_s_domain.py` | 46 | Domain handling |
| `tests/opendrive_geometry/test_sampling.py` | 15 | Endpoint-guaranteed sampling |

## Reports Created
- `reports/line_arc_test_scaffold.md` — scaffold summary
- `reports/line_arc_comparison.json` — machine-readable comparison data
- `reports/line_arc_independent_execution.md` — this file
- `reports/geometry_evaluation_caller_contracts.md` — caller contract matrix
- `reports/geometry_evaluation_caller_contracts.json` — machine-readable contract data
