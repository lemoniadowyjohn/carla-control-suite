# CARLA Ops Studio - Release Manifest

**Release:** Phase 1 Offline Release  
**Date:** 2026-10-15  
**Source SHA:** `c69b60d2fe4ac018136ea0fa26e435a09c15dd73`  
**Branch:** `integration/carla-gui-integration-20261015`  
**Status:** `OFFLINE_RELEASE_VERIFIED`  
**Worktree:** `F:\wt\carla-gui-integration-20261015`

---

## Package Contents

### Core Package: `ultimate_pipeline`

| Module | Lines | Purpose |
|--------|-------|---------|
| `ultimate_pipeline/__init__.py` | 12 | Version export |
| `ultimate_pipeline/cli.py` | 1,200+ | `up` CLI entry point (unchanged) |
| `ultimate_pipeline/gui/__init__.py` | 8 | GUI package marker |
| `ultimate_pipeline/gui/cli.py` | 120 | `carla-ops` entry point |
| `ultimate_pipeline/gui/shell/main_window.py` | 304 | Qt application shell |
| `ultimate_pipeline/gui/shell/services.py` | 149 | Service registry (DI) |
| `ultimate_pipeline/gui/shell/navigation.py` | 206 | 17-route registry |
| `ultimate_pipeline/gui/shell/preferences.py` | 146 | Atomic non-secret preferences |
| `ultimate_pipeline/gui/shell/workers.py` | 169 | Bounded workers, cancellation |
| `ultimate_pipeline/gui/shell/pages/base.py` | 185 | Base page, ControlRow |
| `ultimate_pipeline/gui/shell/pages/core.py` | 271 | 6 Task 13 screens |
| `ultimate_pipeline/gui/shell/pages/runtime.py` | 169 | 10 Task 14 screens |
| `ultimate_pipeline/gui/shell/viewmodels.py` | 398 | 10 runtime view models |
| `ultimate_pipeline/security/__init__.py` | 312 | XXE, archive, path, atomic write |

### Task Deliverables (Tests)

| Test File | Tests | Scope |
|-----------|-------|-------|
| `test_gui_status_freshness_audit_mock.py` | 22 | Status, freshness, audit, mock |
| `test_gui_settings_registry_profiles.py` | 28 | 318 settings, profiles, ranges |
| `test_gui_session_tick_ownership.py` | 36 | Tick authority, actors, cleanup |
| `test_gui_runtime_connection_tm_weather.py` | 32 | Connection ladder, TM, weather |
| `test_gui_calibration_vectors.py` | 23 | 23 calibration vectors |
| `test_gui_maps_security_cook_gates.py` | 25 | XXE, cooking, map identity |
| `test_gui_perception_truth_gating.py` | 11 | Model gating, measurements |
| `test_gui_jobs_governance.py` | 25 | Jobs, locks, verdicts |
| `test_gui_fuzz_safety.py` | 27 | Safety contracts, budgets |
| `test_gui_fuzz_mutators_oracles.py` | 19 | 15 families, 12 oracles |
| `test_gui_fuzz_replay_shrink_corpus.py` | 26 | Replay, shrink, corpus |
| `test_gui_qt_shell.py` | 48 | Qt shell, 17 routes, 7 blockers |
| `test_gui_qt_runtime_pages.py` | 37 | 10 runtime screens |
| `test_gui_security_hardening.py` | 21 | 11 security fixes |

**Total: 380 tests passing, 1 skipped**

### Documentation

| File | Purpose |
|------|---------|
| `USER_DOCUMENTATION.md` | End-user guide |
| `INSTALL_AND_VERIFY.py` | Clean-room installation script |
| `RELEASE_MANIFEST.md` | This file |
| `RELEASE_READINESS_REPORT.md` | Release gate assessment |
| `VERIFICATION_RECEIPT.json` | Machine-readable verification |

### Receipts (16 tasks)

| Task | Receipt | Verdict |
|------|---------|---------|
| 00 | `task_00_receipt.json` | PASS |
| 01 | `task_01_receipt.json` | PASS |
| 02 | `task_02_receipt.json` | PASS |
| 03 | `task_03_receipt.json` | PASS |
| 04 | `task_04_receipt.json` | PASS |
| 05 | `task_05_receipt.json` | PASS |
| 06 | `task_06_receipt.json` | PASS |
| 07 | `task_07_receipt.json` | PASS |
| 08 | `task_08_receipt.json` | PASS |
| 09 | `task_09_receipt.json` | PASS |
| 10 | `task_10_receipt.json` | PASS |
| 11 | `task_11_receipt.json` | PASS |
| 12 | `task_12_receipt.json` | PASS |
| 13 | `task_13_receipt.json` | PASS |
| 14 | `task_14_receipt.json` | PASS |
| 15 | `task_15_receipt.json` | PASS |

---

## GUI Contracts Summary

### Routes: 17 Total
- **Implemented:** 16 (all except Route 10)
- **Placeholders:** 1 (Route 10: Perception & Localization)

### Controls: 116 Total (from CONTROL_CATALOG.csv)
| Status | Count | Description |
|--------|-------|-------------|
| `BOUND_AVAILABLE` | 44 | Backend contract exists and is verified |
| `DEFERRED_NO_TRUTHFUL_BACKEND` | 65 | No backend exists; explicitly disabled |
| `DISABLED_IN_CATALOGUE` | 7 | Catalogue marks as unavailable |
| **Dropped** | **0** | No controls silently removed |

### Settings: 318 Total (from settings registry)
- 307 annotated fields + 11 module globals/shims
- All validated against current source tree
- No invented defaults; ranges/enums = `UNVERIFIED` unless cited

### Calibration Vectors: 23 Implemented
- TV-01 to TV-23 from `VALIDATION_VECTORS.md`
- TV-06 is deliberate wrong-handedness failure
- All round-trip tests provisional pending owner approval

### Fuzzer: 15 Families / 12 Oracles
| Family Type | Count | Status |
|-------------|-------|--------|
| Config-bound | 3 | Offline executable |
| Map | 4 | Offline executable |
| Simulator-guarded | 8 | Built only; never executed |

### Quality Gates: 8 Offline Sections
All must PASS for `up health` offline release gate.

---

## Security Fixes (Task 15)

| # | Module | Fix | Verified |
|---|--------|-----|----------|
| 1 | `carla_probe_port.py` | Truthful TCP probe (no fake `rpc_ok`) | ✅ |
| 2 | `sensor_registry.py` | `stop()` before `destroy()` | ✅ |
| 3 | `train_yolo.py` | Raises error, no fabricated metrics | ✅ |
| 4 | `auto_scenario_generator.py` | Seeded RNG | ✅ |
| 5 | `resource_aware.py` | Fail-closed probes (`ResourceProbeUnavailable`) | ✅ |
| 6 | `experiments/registry.py` | No swallowed import errors | ✅ |
| 7 | `security/__init__.py` | XXE-safe XML parsing (`defusedxml`) | ✅ |
| 8 | `security/__init__.py` | Safe archive extraction (traversal/symlink block) | ✅ |
| 9 | `security/__init__.py` | Path validation (base confinement) | ✅ |
| 10 | `security/__init__.py` | Atomic write (mkstemp+fsync+replace) | ✅ |
| 11 | Actor.is_alive (Q21) | GUI adapter handles both method/attribute | ✅ |

---

## Outstanding Decision-Gated Items

| ID | Item | Blocking | Status |
|----|------|----------|--------|
| Q9 | Coordinate-frame branch merge | Calibration semantics | Operator decision |
| Q10 | Sensor timestamp skew threshold | No measurement exists | Owner calibration |
| Q11 | Drift tolerance | No measurement exists | Owner calibration |
| Q12 | Non-waivable gate taxonomy (GAP037) | Waiver can convert FAIL | Maintainer decision |
| Q13 | train_yolo fabricated metrics | **FIXED** (Task 15) | Removed fallback |
| Q20 | Duplicate removal | Hazardous if auto-deleted | Authorized phase required |
| Q22 | Isolated server lease (Q22) | Live fuzzing blocked | Operator decision |
| Q23 | Calibration threshold owner | Validation status stuck | Named owner required |

---

## Live Validation Blockers (G6, G7, G8)

| Blocker | Evidence | Required |
|---------|----------|----------|
| G6: Map pin | `RUNTIME_MAP_IDENTITY_AUTO.json` = `BLOCKED_COOK_REQUIRED` | UE4.26 cook |
| G7: Cooked content | `UE426_SOURCE_AUTHORITY.json` = `not_claimed` | Operator cook |
| G8: Tick authority | `TickAuthority` = `MISSING` | 6 writers need arbitration |

**No live validation can PASS until these are resolved.**

---

## Installation Verification

```powershell
# Clean-room install
python install_and_verify.py --gui --runtime

# Expected output:
# ✓ Virtual environment created
# ✓ Package installed with extras
# ✓ 380 tests passing
# ✓ GUI launches in offscreen mode
# ✓ carla-ops --verify-install reports all dependencies
```

---

## Rollback Instructions

| Artifact | Rollback |
|----------|----------|
| Preferences | Restore `carla_ops_gui.json.bak` from config directory |
| Virtual environment | Delete `.venv` and recreate |
| Package | `pip uninstall ultimate_pipeline` then reinstall previous version |
| Source | `git checkout <previous-tag>` in worktree |

---

## SHA-256 Checksums

| File | SHA-256 |
|------|---------|
| `carla_ops_studio_offline_release_20261015.zip` | *(computed at packaging)* |
| `RELEASE_MANIFEST.md` | *(computed at packaging)* |
| `VERIFICATION_RECEIPT.json` | *(computed at packaging)* |

---

*Generated from source SHA `c69b60d2fe4ac018136ea0fa26e435a09c15dd73`*