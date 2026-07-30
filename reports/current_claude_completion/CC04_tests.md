# CC04 — Test Execution Evidence

All runs executed **this session** against HEAD `7053bab5` with `UP_DISABLE_CARLA=1`, interpreter `./.venv/Scripts/python.exe` (Python 3.12.2, pytest 9.0.1). Evidence is fresh, not carried over.

## 1. Focused map-identity tests

```
tests/unit/test_map_identity_guard.py ..... 
============================== 5 passed in 0.13s ==============================
```

## 2. Remaining safety-layer tests (outside pytest.ini testpaths)

```
tests/roadrunner/test_capability_probe.py ..
tests/unit/test_artifact_transactions.py ...
============================== 5 passed in 0.95s ==============================
```

## 3. Full configured non-CARLA suite

`pytest.ini` scopes `testpaths = ultimate_pipeline/tests tests/unit` (with `norecursedirs` excluding `work/ external/ submission/ .venv/` etc.). Running the configured suite:

```
====================== 323 passed, 48 warnings in 8.75s =======================
```

0 failures, 0 errors. (Warnings are pre-existing `settings.py` path-resolution `RuntimeWarning`s for optional dirs — `MANUAL_TILES_DIR`, `COORDINATES_JSON`, `HPC_DIR` — not test failures.)

## 4. Geometry tests (broad slice)

Broader sweep across the whole `tests/` tree filtered to geometry/planview/parampoly3/cross_compare:

```
======== 2284 passed, 78 skipped, 220 deselected, 15 warnings in 7.88s ========
```

0 failures. (This is a superset of the configured suite; it confirms the changed imports do not regress the wider geometry surface.)

## 5. Cross-comparison harness (opendrive_geometry)

`python -m opendrive_geometry.cross_compare_implementations`:

```
VERDICT: PASS — All differences are expected policy (EPS threshold) effects.
No formula defects detected in active read-only consumers.
40 expected policy differences documented.
```

## Summary

| Suite | Result |
|---|---|
| Focused map-identity | **5 passed** |
| Remaining safety-layer (probe + transactions) | **5 passed** |
| Full configured non-CARLA suite | **323 passed, 0 failed** |
| Geometry broad slice | **2284 passed, 78 skipped, 0 failed** |
| opendrive_geometry cross-comparison | **PASS (no formula defects)** |
| CARLA runtime tests | **NOT_TESTED / BLOCKED_BY_ENVIRONMENT** (no server; `UP_DISABLE_CARLA=1`) |

**Conclusion:** all offline gates are **green** with fresh evidence. CARLA runtime gates are correctly out of scope for this offline completion (marked BLOCKED_BY_ENVIRONMENT, not passed).
