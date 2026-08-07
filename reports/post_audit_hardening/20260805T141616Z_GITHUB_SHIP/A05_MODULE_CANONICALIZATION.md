# A05 Module Canonicalization

## Selected Canonicalization Strategy
**`GENERATED_SUBMISSION_MIRROR`**

## Policy and Rationale
1. `ultimate_pipeline/` is designated as the primary canonical development root.
2. `submission/infrastructure/ultimate_pipeline/` is maintained as a generated mirror for submission and packaging compliance.
3. Automated drift tests (`tests/phase_q/test_duplicate_module_drift.py`) enforce exact hash equality for all critical runtime, loading, and validation modules between `ultimate_pipeline` and `submission/infrastructure/ultimate_pipeline`.

## Governed Mirrored Modules
- `core/carla_opendrive_loader.py`
- `core/xodr_hash_gate.py`
- `carla_tools/map_identity_guard.py`
- `quality/check_carla_opendrive_compat.py`
- `tools/load_final_into_carla.py`
