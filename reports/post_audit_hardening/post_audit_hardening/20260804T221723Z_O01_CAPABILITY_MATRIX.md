# O01 Capability Matrix

## Existing Programs and Reuse Decisions

| Path | Purpose | Entry Point | Reuse Decision |
|------|---------|-------------|----------------|
| ultimate_pipeline/tools/start_carla_load_xodr.py | Start CARLA and load XODR | CLI --xodr | REUSE_WITH_CONFIGURATION |
| ultimate_pipeline/tools/load_final_into_carla.py | Load final XODR into CARLA | CLI argv[1] | REUSE_WITH_CONFIGURATION |
| ultimate_pipeline/tools/preflight_xodr_loadability.py | Preflight XODR loadability | CLI --xodr --out | REUSE_UNCHANGED |
| ultimate_pipeline/tools/smoke_load_xodr.py | Smoke test XODR loading | CLI | REUSE_WITH_CONFIGURATION |
| ultimate_pipeline/tools/carla_smoke_suite.py | CARLA smoke suite | CLI | REUSE_WITH_CONFIGURATION |
| ultimate_pipeline/tools/probe_carla.py | CARLA probe/health check | CLI | REUSE_UNCHANGED |
| ultimate_pipeline/tools/spawn_thesis_rig.py | Thesis spawn rig | CLI | REUSE_WITH_CONFIGURATION |
| submission/infrastructure/ultimate_pipeline/core/carla_opendrive_loader.py | Core OpenDRIVE loader | API | EXTEND - add identity gate |
| submission/infrastructure/ultimate_pipeline/core/carla_preflight.py | CARLA preflight | Subprocess | REUSE_UNCHANGED |
| submission/infrastructure/ultimate_pipeline/core/xodr_hash_gate.py | XODR hash gate | API | EXTEND - make enforcement active |
| submission/infrastructure/ultimate_pipeline/carla_tools/carla_server.py | CARLA server management | API | REUSE_UNCHANGED |
| submission/infrastructure/ultimate_pipeline/carla_tools/map_registry.py | Map registry | API | REUSE_UNCHANGED |
| submission/infrastructure/ultimate_pipeline/carla_tools/map_identity_guard.py | Map identity guard | API | EXTEND - make enforcement default-on |
| ultimate_pipeline/tools/carla_visual_smoke_gate.py | Visual smoke gate | CLI | REUSE_WITH_CONFIGURATION |

## Key Findings

1. **carla_opendrive_loader.py** has load_opendrive_world() and load_opendrive_world_from_file() - these are the authoritative loaders.
2. **map_identity_guard.py** has alidate_world_map() which detects Town fallback, but requires UP_THESIS_STRICT=1 to enforce.
3. **xodr_hash_gate.py** has hash verification but is record-only (no enforcement).
4. **start_carla_load_xodr.py** is the primary CLI entry point for loading XODR maps.
5. **No existing program** enforces runtime identity verification (source hash vs runtime hash comparison).
6. **No existing program** prevents fallback to Town10HD_Opt when OpenDRIVE generation fails.

## Missing Capabilities

1. Runtime identity gate (source hash vs runtime hash comparison)
2. Enforcement of no-fallback-to-Town policy
3. Active hash enforcement (not just record-only)
4. Full structural inventory comparison (road count, junction count, lane count, signal count)
5. Candidate lineage resolution
