# Fix Verification — Gemini 3.1 Pro Audit

## Verification Methodology

For each claimed hardening fix, independently verified:
1. **Code exists** — Is the guard/mutation present in the tracked file at the claimed commit?
2. **Default safe** — Does the feature default to disabled/False unless the `debug` profile is active?
3. **Runtime reachable** — Is the code on an active execution path from `main_pipeline.py::run()`?
4. **Tested** — Is there a dedicated unit or integration test covering this fix?

## Results

| # | Claimed Fix | File(s) | Code Exists | Default Safe | Reachable | Tested |
|---|---|---|---|---|---|---|
| 1 | Disable unsafe planView mutations | `stage_06_links.py`, `release_profile.py` | ✅ | ✅ | ✅ | ✅ |
| 2 | Reorder geometry authority (planView before elevation) | `stage_05_geometry.py` | ✅ | ✅ | ✅ | ❌ |
| 3 | Disable LaneLink regeneration + autofix defaults | `stage_08_integrity.py`, `release_profile.py` | ✅ | ✅ | ✅ | ✅ |
| 4 | Release profile policies (fail-closed, AND policy, unknown closed) | `release_profile.py`, `main_pipeline.py` | ✅ | ✅ | ✅ | ✅ |
| 5 | Ground enrichment defaults (roundabout=False, traffic_lights=False) | `stage_04_enrichment.py`, `settings.py` | ✅ | ✅ | ✅ | ❌ |
| 6 | Guard `recompute_geometry_starts` in seam fix path | `stage_06_links.py` | ✅ | ✅ | ✅ | ❌ |
| 7 | CumulativeGateRunner (tally-all, fail-at-end) | `gate_runner.py`, `main_pipeline.py` | ✅ | ✅ | ✅ | ~(indirect) |
| 8 | Geometry freeze hash + downstream verification | `stage_05_geometry.py`, `main_pipeline.py` | ✅ | ✅ | ✅ | ❌ |
| 9 | DrivableSurfaceScanner (Stage 8G) | `quality/drivable_surface_scanner.py` | ✅ | ✅ | ✅ | ❌ |
| 10 | FullMapMetricsScanner (Stage 8H) | `quality/full_map_metrics.py` | ✅ | ✅ | ✅ | ❌ |

**Legend**: ✅ = confirmed, ❌ = not present, ~ = partial

## Detailed Per-Fix Evidence

### 1. Unsafe planView mutations gated
- **Guard**: `_unsafe_planview_mutations_enabled(s)` at `stage_06_links.py:20`
- **Delegates to**: `release_profile.unsafe_planview_mutations_enabled(s)` at `release_profile.py:122`
- **AND policy**: `getattr(s, "ENABLE_UNSAFE_PLANVIEW_MUTATIONS", False)` AND `resolve_experimental_unsafe(profile_name)`
- **All 4 call sites gated**: `smooth_heading_jumps` (line 46), `merge_small_geometries` (line 54), `merge_short_segments` (line 62), `recompute_geometry_starts` (line 72, 240)
- **Tests**: 11 parametrized + 1 invalid-env test in `TestReleaseProfilePolicy`

### 2. Geometry reorder
- `_step5_geometry_elevation_continuity` at `stage_05_geometry.py:38` calls `_step6_planview_continuity` FIRST (line 55)
- Then freezes XY with `geometryFrozen="true"` header attribute (line 129)
- Then calls `_step5_dem_and_geometry` on frozen XY (line 163)
- **No test coverage** for this ordering invariant

### 3. LaneLink regen + autofix disabled
- Guard helper `_unsafe_lanelink_regen_enabled(s)` at `stage_08_integrity.py:424`, `stage_08_final_integrity.py:22`
- Delegates to `release_profile.unsafe_lanelink_regen_enabled(s)` with AND policy
- `UP_AUTOFIX_LANE_SUCCESSORS` default = `"0"` at `stage_08_integrity.py:587`
- `UP_AUTOFIX_MISSING_LANE_SUCCESSORS` default = `"0"` at `stage_08_integrity.py:684`
- **Tests**: 12 parametrized + 1 invalid-env test in `TestReleaseProfilePolicy`

### 4. Release profile policies
- Unknown profile fails closed: `release_profile.py:73-75` → returns `default=False`
- Env cannot bypass profile: env read at line 116 only affects feature *request*, profile check at line 119 unconditional
- AND policy: feature request AND profile permission both required (lines 117-119)
- `resolve_experimental_unsafe()` is NOT env-overridable (line 93-98)
- **Tests**: 9 parametrized for strict gates, 6 for experimental_unsafe, 3 for env parsing

### 5-10: Untested fixes
- Fixes 2, 5, 6, 8, 9, 10 have **zero dedicated test coverage**
- CumulativeGateRunner (fix 7) is exercised indirectly through pipeline gate calls but has no unit test
- All 6 untested fixes rely on runtime enforcement only
