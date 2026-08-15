# A4 CARLA tools honesty hardening - outcome

Date: 2026-08-15
Executor: Codex
Verdict: **CARLA_TOOLS_HARDENED_GREEN**

## Summary

`fixed_traffic_manager.py` no longer returns a silent mock when CARLA is unavailable. Under strict thesis mode it
fails closed. In dev mode, mock traffic management is available only with the explicit
`UP_ALLOW_MOCK_TRAFFIC_MANAGER=1` override, and every mock path emits `MOCK - NOT REAL EVIDENCE`.

`sensor_rig.py` remains deprecated for thesis experiments, but the inline rotation placeholder is now a named,
tested `rotation_matrix_to_carla_euler_degrees` helper with validation and strict failure on singular rotations.

## Proven By Tests

- `UP_THESIS_STRICT=1` plus no CARLA raises before any mock traffic manager is created.
- No CARLA without `UP_ALLOW_MOCK_TRAFFIC_MANAGER=1` raises and tells the developer which explicit flag is required.
- Explicit dev mock returns a marked mock object, returns zero spawned actors, and reports `evidence_valid=False`.
- Rotation extraction recovers known ZYX roll/pitch/yaw angles from a homogeneous matrix.
- Bad matrix shape raises under strict mode.

Targeted gate:

```text
tests/unit/test_carla_tools_honesty.py ..... [100%]
5 passed in 0.30s
```

Full-suite gate:

```text
688 passed, 49 warnings in 50.33s
```

## Boundaries

- No CARLA was run.
- No certifier or gate logic was changed.
- The canonical thesis rig remains `thesis_sensor_rig.py`; this hardening only prevents the deprecated
  `sensor_rig.py` placeholder from staying implicit.
