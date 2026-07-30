# CC02 — Safety-Layer File Inventory & Classification

**Safety commit:** `7053bab56de4ba1680c4fb73bf85a5dc9b911694`
**Author / date:** Michal / 2026-07-30 18:54:00 +0200
**Subject:** `feat(safety): land map-repair safety layer on integration branch`
**Scope:** 14 files, +1215 insertions, atomic (source + tests together).

## Classification

| File | Class | Notes |
|---|---|---|
| `ultimate_pipeline/artifacts/__init__.py` | required source | Artifact-transaction package surface |
| `ultimate_pipeline/artifacts/errors.py` | required source | Typed transaction/promotion errors |
| `ultimate_pipeline/artifacts/model.py` | required source | Artifact identity/metadata model |
| `ultimate_pipeline/artifacts/promotion.py` | required source | Candidate→promotion gating |
| `ultimate_pipeline/artifacts/recovery.py` | required source | Recovery/rollback |
| `ultimate_pipeline/artifacts/semantic_diff.py` | required source | Semantic diff for artifact changes |
| `ultimate_pipeline/artifacts/store.py` | required source | Content-addressed store (largest, 225 LOC) |
| `ultimate_pipeline/artifacts/transaction.py` | required source | Transactional write discipline |
| `ultimate_pipeline/carla_tools/map_identity_guard.py` | required source | **Map-identity guard** (`validate_world_map`, `is_town_fallback`, `save_map_identity`) — SHA-256 `B64A59909B9C5D0E9C99A45D051A20E615385C3E822DA15C8A72C5DF9558BE37` |
| `ultimate_pipeline/carla_tools/session.py` | required source | `CarlaSession.validate_map_identity` (+16 lines) — SHA-256 `9CC310779AE132E065AA60D302B9C37A6382785CC2DE90E75C92B45E875DE376` |
| `ultimate_pipeline/roadrunner/capability_probe.py` | required source | RoadRunner capability probe |
| `tests/roadrunner/test_capability_probe.py` | required test | Probe unit tests (2) |
| `tests/unit/test_artifact_transactions.py` | required test | Transaction tests (3), in `testpaths` |
| `tests/unit/test_map_identity_guard.py` | required test | Map-identity tests (5), in `testpaths` |

**Required source:** 11 · **Required test:** 3 · **Generated / junk / unrelated staged:** 0

## Excluded (correctly NOT committed)

The following remain untracked and were kept out of the commit: `nul`, `vehicle.`, `.idea/`, `carla_governed/`, `external/`, `__pycache__/`, `.pytest_cache/`, and all `reports/*` working artifacts. None of these entered the safety commit.

**Conclusion:** the map-repair safety layer is fully **TRACKED** and committed at `7053bab5`; every staged file is required source or required test; zero junk/generated/large-artifact files were included.
