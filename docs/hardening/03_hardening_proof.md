# Hardening Proof: Unsafe Operations Disabled

## 1. PlanView Mutations (Stage 6) — All Gated

**File:** `ultimate_pipeline/pipeline_stages/stage_06_links.py`

Guard function (lines 20-22):
```python
def _unsafe_planview_mutations_enabled(settings_obj) -> bool:
    from ultimate_pipeline.contracts.release_profile import unsafe_planview_mutations_enabled
    return unsafe_planview_mutations_enabled(settings_obj)
```

| Operation | Line | Guard | Status |
|---|---|---|---|
| `smooth_heading_jumps` | 46 | `if unsafe:` (line 42, guard = line 33) | **GATED** |
| `merge_small_geometries` | 54 | `if unsafe:` (line 42) | **GATED** |
| `merge_short_segments` | 62 | `if unsafe:` (line 42) | **GATED** |
| `recompute_geometry_starts` | 72 | `if unsafe:` (line 42) + `ENABLE_GEOMETRY_START_RECOMPUTE` (line 71, default False) | **GATED** (3 layers) |
| `merge_small_geometries` | 192 | `if unsafe:` (line 189, micro-prune) | **GATED** |
| `merge_short_segments` | 195 | `if unsafe:` (line 189) | **GATED** |
| `recompute_geometry_starts` | 197 | `if unsafe:` (line 189) | **GATED** |
| `recompute_geometry_starts` | 240 | `if unsafe:` (line 236, added Phase 7) | **GATED** ✅ |

## 2. AND Policy (release_profile.py)

```python
def unsafe_planview_mutations_enabled(settings_obj) -> bool:
    settings_requested = bool(getattr(settings_obj, "ENABLE_UNSAFE_PLANVIEW_MUTATIONS", False))
    env_requested = parse_optional_bool_env("UP_ENABLE_UNSAFE_PLANVIEW_MUTATIONS")
    requested = env_requested if env_requested is not None else settings_requested
    if not requested:
        return False                                    # ← feature NOT requested → fail closed
    return resolve_experimental_unsafe(profile_name)     # ← profile must permit unsafe
```

Returns `True` only when **both**:
1. User explicitly set `ENABLE_UNSAFE_PLANVIEW_MUTATIONS=True` or env `UP_ENABLE_UNSAFE_PLANVIEW_MUTATIONS=true`
2. `RELEASE_PROFILE` is `"debug"` (the only profile with `experimental_unsafe=True`)

## 3. LaneLink Regeneration (Stage 8) — Same AND Pattern

**Files:** `stage_08_integrity.py:424-426`, `stage_08_final_integrity.py:22-24`

Both delegate to shared helper:
```python
def _unsafe_lanelink_regen_enabled(settings_obj) -> bool:
    from ultimate_pipeline.contracts.release_profile import unsafe_lanelink_regen_enabled
    return unsafe_lanelink_regen_enabled(settings_obj)
```

Same AND policy: `ENABLE_LANELINK_REGEN=True` (or env) **AND** `RELEASE_PROFILE=debug`.

## 4. Enrichment (Stage 4) — Defaults Changed to False

| Setting | Old Default | New Default | Env Override |
|---|---|---|---|
| `ENABLE_ROUNDABOUT_RECONSTRUCTION` | True | **False** | `UP_ENABLE_ROUNDABOUT_RECONSTRUCTION` |
| `ENABLE_TRAFFIC_LIGHTS` | True | **False** | `UP_ENABLE_TRAFFIC_LIGHTS` |

## 5. Release Profile Hardening

| Profile | experimental_unsafe | strict_quality_gates |
|---|---|---|
| `structural_release` | **False** | True |
| `visual_build` | **False** | True |
| `scenario_augmentation` | **False** | False |
| `debug` | **True** | False |

In the default `structural_release` profile:
- `unsafe_planview_mutations_enabled()` → **False**
- `unsafe_lanelink_regen_enabled()` → **False**
- `resolve_strict_quality_gates()` → **True** (fail-closed on QA checks)

## 6. Stage Gate Fail-Closed Behavior

`_stage_gate()` in `main_pipeline.py` raises `RuntimeError` when:
- `UP_STRICT_QUALITY_GATES` env is truthy, OR
- The active release profile's `strict_quality_gates` is `True`

This applies to all quality gates throughout the pipeline: junction integrity, geometric continuity, elevation variance/stddev/continuity, lane width continuity, origin sanity, elevation seams, post-tiling integrity, etc.
