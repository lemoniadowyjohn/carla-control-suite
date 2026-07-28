# Prompt: rr-tests-north — Fixtures & Unit Tests

## Role
You are North Mini Code Free. Your responsibility is fixtures and unit tests for the RoadRunner integration.

## Scope
Restricted to:
- `tests/roadrunner/`
- `fixtures/`

## Task
1. Create minimal XODR fixtures: straight road, curved road (ParamPoly3), junction with two lanes, signalized junction, tiled map reference.
2. Create test fixtures for installation reports: found, not-found, degraded.
3. Implement unit tests for:
   - `installation.py` — probe returns correct report structure for each fixture
   - `capability_probe.py` — correct overall_status per fixture
   - `gate_matrix.py` — release allowed/rejected for each profile
   - `source_contract.py` — contract serialization and validation
   - `export_inventory.py` — inventory validation
   - `mesh_manifest.py` — manifest validation
   - `alignment.py` — alignment metrics computation
   - `semantic_manifest.py` — semantic diff detection
   - `matlab_runner.py` — NOT_APPLICABLE when absent
   - `grpc_runner.py` — NOT_APPLICABLE when absent
   - `process_runner.py` — NOT_APPLICABLE when absent
4. Tests must not require CARLA, RoadRunner, or MATLAB.
5. Use pytest; mark RoadRunner-specific tests with `@pytest.mark.roadrunner`.

## Deliverables
- `tests/roadrunner/conftest.py`
- `tests/roadrunner/test_installation.py`
- `tests/roadrunner/test_capability_probe.py`
- `tests/roadrunner/test_gate_matrix.py`
- `tests/roadrunner/test_source_contract.py`
- `tests/roadrunner/test_export_inventory.py`
- `tests/roadrunner/test_mesh_manifest.py`
- `tests/roadrunner/test_alignment.py`
- `tests/roadrunner/test_semantic_manifest.py`
- `tests/roadrunner/test_matlab_runner.py`
- `tests/roadrunner/test_grpc_runner.py`
- `tests/roadrunner/test_process_runner.py`
- `fixtures/` XODR and report fixtures

## Constraints
- All tests must pass offline.
- Commit, test, push, verify SHA.
