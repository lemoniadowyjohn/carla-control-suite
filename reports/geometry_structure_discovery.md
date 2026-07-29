# Geometry Structure Discovery Report

**Date:** 2026-07-29
**Repository:** `carla_-main` (GitHub: `lemoniadowyjohn/carla-control-suite.git`)
**Commit:** `faa20bb5` on `deepseek-observability-integration-verification`

## 1. Executive Result Classification

**`C. MULTIPLE_CONFLICTING_STRUCTURES`**

The repository has three independent geometry evaluation structures with different conventions, none of which is wired as the sole authority:

| Structure | Location | Convention | Active Production Path? | Tests? |
|-----------|----------|------------|------------------------|--------|
| Canonical evaluator | `opendrive_geometry/` | OpenDRIVE standard (x,y,hdg) | **No** | **Yes** (56 tests) |
| Production evaluator | `ultimate_pipeline/quality/check_geometric_continuity.py` | OpenDRIVE standard (Pose with x,y,hdg) | **Yes** | **No** |
| Local-frame model | `ultimate_pipeline/opendrive_geometry/` | Local frame (s∈[0,1], h field) | **No** | **No** |

Additionally, 22+ inline implementations across 14 files duplicate the same formulas with different epsilon thresholds, one sentinel-radius bug, and one dimensionally wrong formula.

---

## 2. Active Implementation Call Graph

```
main_pipeline.py (entry point)
├── stage_06_links.py
│   └── check_geometric_continuity.py  ← MOST COMPLETE EVAL (ALL 5 primitives)
│       ├── _pose_line()               ← line
│       ├── _pose_arc()                ← arc (local-frame formula)
│       ├── _pose_spiral_numeric()     ← spiral (Euler integration, ds=0.2)
│       ├── _pose_poly3()              ← poly3 (cubic, road-frame)
│       ├── _param_poly_eval()         ← paramPoly3 (uv-frame)
│       └── _pose_param_poly3()        ← paramPoly3 dispatch
├── stage_09_tiling.py
│   ├── check_geometric_continuity.py (same)
│   └── check_post_tiling_integrity.py
│       └── check_geometric_continuity.py (same)
├── quality_gate_manager.py
│   └── check_geometric_continuity.py (same)
├── domain_gap/
│   ├── elevation_gap.py  ← inline line/arc eval (EPS=1e-12)
│   │   └── geometry_math.py ← paramPoly3 sampling only
│   ├── geo_alignment.py  ← inline line/arc eval (EPS=1e-12)
│   │   └── geometry_math.py ← paramPoly3 sampling only
│   └── curvature_gap.py  ← arc/paramPoly3 curvature extraction
├── topology/junction_connector_rebuild.py ← inline arc eval
├── tile_validation/geometry_seam_checker.py ← inline arc eval
├── geometry/lane_seam_checker.py ← inline arc eval (sampling)
├── quality/check_dem_full_coverage.py ← inline arc eval (EPS=1e-9)
├── visualization/
│   ├── map_plotter.py ← inline arc eval (SENTINEL BUG)
│   ├── map_diff.py ← inline arc eval (BROKEN FORMULA)
│   ├── lane_overlay.py ← inline arc eval
│   └── heatmap_generator.py ← inline arc eval
└── NOT CONNECTED:
    └── opendrive_geometry/primitives.py ← canonical (ACTIVE_CANONICAL but not in path)
    └── ultimate_pipeline/opendrive_geometry/ ← local-frame model (INACTIVE)
```

---

## 3. All Line/Arc Evaluators

| # | File | Function/Class | Line | EPS | Formulas | Primitives | Tests | Status |
|---|------|----------------|------|-----|----------|------------|-------|--------|
| 1 | `opendrive_geometry/primitives.py` | `evaluate_line()` | 11-21 | 1e-12 | `x0 + s*cos(h)` | line, arc | 56 | **CANONICAL** |
| 2 | `opendrive_geometry/primitives.py` | `evaluate_arc()` | 24-38 | 1e-12 | `(sin(h)-sin(h0))*inv_c` | line, arc | 56 | **CANONICAL** |
| 3 | `opendrive_geometry/model.py` | `Pose2D` | 49 | — | data type | — | 56 | **CANONICAL** |
| 4 | `opendrive_geometry/evaluator.py` | `ReferenceLineEvaluator` | 5-24 | — | protocol (stub) | — | 0 | **STUB** |
| 5 | `geometry/geometry_math.py` | `GeometryCalculator._integrate_line()` | 102-105 | 1e-9 | `x + L*cos(h)` | line, arc | 0 | **DUPLICATE** |
| 6 | `geometry/geometry_math.py` | `GeometryCalculator._integrate_arc()` | 107-116 | 1e-9 | `(sin(h2)-sin(h))/k` | line, arc | 0 | **DUPLICATE** |
| 7 | `quality/check_geometric_continuity.py` | `_pose_line()` | 98-101 | 1e-12 | `x0 + s*cos(h)` | line, arc, spiral, poly3, paramPoly3 | 0 | **DUPLICATE** |
| 8 | `quality/check_geometric_continuity.py` | `_pose_arc()` | 104-117 | 1e-12 | local-frame `dx=sin(k*s)/k, dy=(1-cos(k*s))/k` | line, arc, spiral, poly3, paramPoly3 | 0 | **DUPLICATE** |
| 9 | `tile_validation/geometry_seam_checker.py` | `_geometry_endpoint()` | 28-55 | 1e-12 | R-based `x+=R*(sin(h0+θ)-sin(h0))` | line, arc | 0 | **DUPLICATE** |
| 10 | `geometry/lane_seam_checker.py` | `_sample_geometry()` | 25-61 | 1e-9 | R-based sampling | line, arc | 0 | **DUPLICATE** |
| 11 | `domain_gap/elevation_gap.py` | `_sample_line/_sample_arc()` | 133-161 | 1e-12 | canonical `(sin(θ)-sin(h))/k` | line, arc | 0 | **DUPLICATE** |
| 12 | `domain_gap/geo_alignment.py` | `_sample_transformed_geometry_points()` | 37-66 | 1e-12 | canonical | line, arc | 0 | **DUPLICATE** |
| 13 | `visualization/map_plotter.py` | `_sample_geometry()` | 32-85 | **1e9 sentinel** | R-based, NO line fallback | line, arc | 0 | **BUG** (PROB-243) |
| 14 | `quality/check_dem_full_coverage.py` | `_sample_line/_sample_arc()` | 13-34 | 1e-9 | canonical | line, arc | 0 | **DUPLICATE** |
| 15 | `topology/junction_connector_rebuild.py` | `_arc_endpoint()` | 225-239 | 1e-12 | local-frame | line, arc | 0 | **DUPLICATE** |
| 16 | `visualization/lane_overlay.py` | `_endpoint()` | 58-83 | implicit | canonical | line, arc | 0 | **DUPLICATE** |
| 17 | `visualization/heatmap_generator.py` | `_endpoint()` | 55-84 | implicit | canonical | line, arc | 0 | **DUPLICATE** |
| 18 | `visualization/map_diff.py` | `_sample_geometry()` | 47-66 | 1e-9 | **BROKEN** `theta*|k|` heading | line, arc | 0 | **BUG** (PROB-245) |
| 19 | `ultimate_pipeline/opendrive_geometry/model.py` | `ArcGeometry.point_at_s()` | 447-467 | 1e-12 | canonical (local frame, `h` field) | line, arc | 0 | **INACTIVE** |
| 20 | `submission/.../` | (all of above duplicated) | — | — | — | — | 0 | **MIRROR** |

---

## 4. All Related Tests and Fixtures

| Test file | Tests | Geometry scope | CARLA-free? | Active? | Assertions |
|-----------|-------|----------------|-------------|---------|------------|
| `tests/unit/test_opendrive_geometry_line_arc.py` | 56 | line + arc eval, sample, bounds | Yes | Yes | `pytest.approx` |
| `tests/unit/test_curvature_gap_parampoly3.py` | 3 | paramPoly3 curvature extraction | Yes | Yes | `==`, `> 0.0` |
| `tests/unit/test_elevation_gap.py` | 14 | elevation gap metric (uses line/arc indirectly) | Yes | Yes | `pytest.approx` |
| `tests/unit/test_connectivity_gap.py` | 14 | connectivity metric | Yes | Yes | `pytest.approx` |
| `tests/unit/test_geo_alignment_rigid_scale_lock.py` | 2 | geo alignment | Yes | Yes | `==`, `abs()` |
| `domain_gap/tests/test_geo_alignment.py` | 10 | geo alignment | Yes | Yes | `pytest.approx` |
| `tests/unit/test_tile_gap_evaluator.py` | 6 | tile IoU | Yes | Yes | `==` |
| `tests/unit/test_xodr_cropper_gps.py` | 1 | paramPoly3 road detection | Yes | Yes | `is True/False` |
| `tests/unit/test_junction_connector_rebuild.py` | 2 | connector rebuild (uses arc eval) | Yes | Yes | `math.isclose` |
| `tests/unit/test_verify_final_xodr.py` | 4 | XODR verification | Yes | Yes | `==` |
| `external/.../test_geometry_line.py` | 4 | line (Blender) | No (bpy) | Partial | `pytest.approx` |
| `external/.../test_geometry_arc.py` | 5 | arc (Blender) | No (bpy) | Partial | `pytest.approx` |
| `external/.../test_geometry_clothoid.py` | 1 | clothoid (Blender) | No (bpy) | Partial | `pytest.approx` |
| `external/.../test_geometry_parampoly3.py` | 1 | paramPoly3 (Blender) | No (bpy) | Partial | `pytest.approx` |

**No XODR fixtures exist** — all tests generate XODR programmatically via `xml.etree.ElementTree` or f-strings.

---

## 5. Duplicates and Contradictions

### Duplicates

| Root cause | Occurrences | Impact |
|------------|-------------|--------|
| Inline arc formula (canonical) | 8 files across 2 trees = 16 | Fix must be applied 16 times |
| Inline arc formula (local-frame) | 2 files × 2 trees = 4 | Different from canonical = confusion |
| Inline arc formula (R-based) | 3 files × 2 trees = 6 | Equivalent but different variable names |
| Integrate-only for non-arc | 6 files × 2 trees = 12 | Spiral/poly3 silently treated as line |
| `submission/` mirror | Entire `ultimate_pipeline/` copied | Every fix must be applied twice |

### Contradictions

| Issue | Source A | Source B | Resolution |
|-------|----------|----------|------------|
| EPS for arc zero-curvature | `primitives.py`: `1e-12` | `geometry_math.py`: `1e-9` | Policy choice — standardize to 1e-12 |
| Near-zero curvature behavior | `< 1e-12` (arc formula) | `<= 1e-12` (line formula) | `elevation_gap.py` uses `<=`, others use `<` |
| Pose field naming | `Pose2D.hdg` | `Pose.h` (local model) | OpenDRIVE standard is `hdg` |
| Arc formula for y | `(cos(h0)-cos(h))/k` | `-R*(cos(h0+θ)-cos(h0))` | Equivalent but different implementation |
| Formula sentinel | `primitives.py` line fallback | `map_plotter.py` 1e9 radius | map_plotter is **wrong** |

---

## 6. Missing Capabilities

| Capability | Needed by | Status |
|------------|-----------|--------|
| Spiral evaluator (Fresnel integrals) | All geometry consumers | **MISSING** — only numeric Euler integration exists |
| Poly3 evaluator (road-frame cubic) | All geometry consumers | **MISSING** — only `check_geometric_continuity.py` has it |
| ParamPoly3 evaluator (uv-frame cubic) | All geometry consumers | **MISSING** — 10,290 instances in generated XODR |
| Point projection (nearest s on geometry) | Lane-center, object placement | **MISSING** — protocol defined but not implemented |
| Curvature derivative (dk/ds) | Smoothness metrics, seam detection | **MISSING** |
| Sampling with guaranteed endpoint | Tile seam checking | **MISSING** — most samplers don't guarantee endpoint |
| Analytical curvature at arbitrary s | Quality gates, curvature gap | **MISSING** for line/arc (trivial but not exposed) |
| Geometry bounds for curve | Tiling, culling | **MISSING** for spiral/poly3/paramPoly3 |
| Cross-module conformance test | Regression prevention | **MISSING** — only `cross_compare_implementations.py` exists |

---

## 7. Recommended Structure to Reuse

### Adopt: `opendrive_geometry/` (canonical)

The `opendrive_geometry/` package at repo root is the correct foundation:

- **`opendrive_geometry/model.py`** — `Pose2D`, `Vec2`, `Bounds2D`, `GeometrySegment`, `ProjectionResult`. Data types are correct, frozen, and have useful helper methods (`transformed`, `direction`, `bounds.contains`, `bounds.from_points`).
- **`opendrive_geometry/primitives.py`** — `evaluate_line()`, `evaluate_arc()`, `sample_line()`, `sample_arc()`, `line_bounds()`, `arc_bounds()`. Clean, well-tested, authoritative.
- **`opendrive_geometry/evaluator.py`** — `ReferenceLineEvaluator` protocol. Needs concrete implementation.
- **`ultimate_pipeline/tests/unit/test_opendrive_geometry_line_arc.py`** — 56 analytical tests, all passing, CARLA-free, using `pytest.approx`.

### DO NOT use: `ultimate_pipeline/opendrive_geometry/` (local-frame model)

The model at `ultimate_pipeline/opendrive_geometry/model.py` uses a **different coordinate convention** (local frame, `s` normalized to [0,1], field named `h` instead of `hdg`). This conflicts with every other implementation. It has zero callers and zero tests.

---

## 8. Files That Must Not Be Used

| File | Reason | Action |
|------|--------|--------|
| `ultimate_pipeline/opendrive_geometry/model.py` | Different coordinate convention (local frame, h field) | Deprecate or delete |
| `ultimate_pipeline/opendrive_geometry/evaluator.py` | Depends on the wrong model | Deprecate or delete |
| `submission/infrastructure/ultimate_pipeline/*` | Byte-for-byte copy of production code | Do not edit; let submission process handle |
| `ultimate_pipeline/visualization/map_diff.py` lines 47-66 | Broken arc formula (PROB-245) | Fix or quarantine |
| `ultimate_pipeline/visualization/map_plotter.py` lines 52-55 | Sentinel radius bug (PROB-243) | Fix before use |
| `external/blender-driving-scenario-creator/` | Separate codebase, requires Blender | Do not edit from this repo |

---

## 9. Recommended Next Bounded Task

### Make `opendrive_geometry/primitives.py` the sole authority for line and arc

**Objective:** Wire the canonical evaluator into the active production call path, replacing all inline line/arc implementations.

**Steps:**
1. Delegate `geometry_math.py:GeometryCalculator` to `evaluate_line`/`evaluate_arc` (adds `opendrive_geometry` dependency)
2. Replace inline formulas in `elevation_gap.py`, `geo_alignment.py`, `check_dem_full_coverage.py` with `opendrive_geometry` calls
3. Replace `check_geometric_continuity.py:_pose_line()`/`_pose_arc()` with `opendrive_geometry` calls (but keep spiral/poly3/paramPoly3 locals)
4. Fix `map_plotter.py` sentinel bug
5. Fix or quarantine `map_diff.py` broken formula
6. Replace R-based formulas in `geometry_seam_checker.py`, `lane_seam_checker.py`
7. Replace endpoint formulas in `lane_overlay.py`, `heatmap_generator.py`, `junction_connector_rebuild.py`
8. Standardize all EPS to 1e-12
9. Run cross-comparison benchmark to confirm all outputs match

**Verification:**
```bash
python opendrive_geometry/cross_compare_implementations.py  # ALL OK
pytest ultimate_pipeline/tests/unit/test_opendrive_geometry_line_arc.py -v  # 56/56
pytest ultimate_pipeline/tests/unit/ -q  # no regressions
```

---

## 10. Evidence

| Finding | File | Line | Evidence |
|---------|------|------|----------|
| Canonical line eval | `opendrive_geometry/primitives.py` | 11-21 | `evaluate_line()` — `x0 + s_clamped * math.cos(hdg0)` |
| Canonical arc eval | `opendrive_geometry/primitives.py` | 24-38 | `evaluate_arc()` — `(math.sin(hdg) - math.sin(hdg0)) * inv_c` |
| Production line eval | `quality/check_geometric_continuity.py` | 98-101 | `_pose_line()` — same formula |
| Production arc eval | `quality/check_geometric_continuity.py` | 104-117 | `_pose_arc()` — local-frame `dx_local = sin(k*s)/k` |
| GeometryCalculator arc | `geometry/geometry_math.py` | 107-116 | `_integrate_arc()` — `(sin(hdg_new)-sin(hdg))/k` |
| Seam checker arc | `tile_validation/geometry_seam_checker.py` | 43-55 | `_geometry_endpoint()` — R-based formula |
| Lane seam arc | `geometry/lane_seam_checker.py` | 43-61 | `_sample_geometry()` — R-based, EPS=1e-9 |
| Elevation gap arc | `domain_gap/elevation_gap.py` | 143-161 | `_sample_arc()` — canonical, EPS=1e-12 |
| map_plotter sentinel bug | `visualization/map_plotter.py` | 52-55 | `radius = 1.0 / curvature if curvature != 0 else 1e9` |
| map_diff broken formula | `visualization/map_diff.py` | 58-65 | `theta = ds / R; local_hdg = hdg + theta * curvature * abs(R)` |
| Local-frame model | `ultimate_pipeline/opendrive_geometry/model.py` | 80-131 | `Pose2D` with `h` field, local frame |
| Canonical Pose2D | `opendrive_geometry/model.py` | 49-68 | `Pose2D` with `hdg` field, global frame |
| Cross-comparison | `opendrive_geometry/cross_compare_implementations.py` | 1-284 | Benchmark script comparing 7 impls |
| Analytical tests | `tests/unit/test_opendrive_geometry_line_arc.py` | 1-341 | 56 tests, all passing |
| Compilation | `compileall` | — | All modules compile cleanly |
| Test collection | `pytest --collect-only` | — | 59 geometry tests collected, 0 errors |
| 10,290 paramPoly3 | `problems.md` | 483 | Generated XODR uses paramPoly3 as dominant primitive |
