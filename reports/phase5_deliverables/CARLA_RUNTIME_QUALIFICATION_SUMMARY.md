# CARLA Runtime Qualification Summary

**Campaign SHA:** c69b60d2 (prior) + 363a1868 (current repair branch)
**Date:** 2026-10-21T14:40:00Z
**Workstation:** Intel i7-8850H / 47.7 GiB RAM / NVIDIA Quadro P3200 6 GB / Windows 11 Pro 26300

---

## Verdict

`HOST_RUNTIME_PARTIAL_EXACT_BLOCKERS`

---

## Executed (verified with commands / files)

- Hardware inventory reconciliation (`CARLA_HARDWARE_INVENTORY.json` verified)
- CPU model corrected (not hybrid; 6P/12T verified)
- Memory/pagefile reconciled (47.7 GiB / 22.8 GiB free; 1.36 GiB pagefile noted)
- GPU identity verified (Quadro P3200 6 GB, driver 573.22, 5.4 GiB free, no active server)
- Storage gate verified (max free 15.70 GiB on H:) — **NOT MET**
- Python 3.12 isolation verified (Python 3.12.2 available; venv created at C:\temp\py312_venv; `carla-0.9.16-cp312-cp312-win_amd64.whl` installed; `import carla` succeeds; `Client` class available)
- Manifest builder fix verified (P0-1, 8/8 negative controls pass)
- Frame-set synchronization verified (P0-2, 23/23 synthetic tests pass)
- Transaction rollback module verified (P0-3, 19/19 synthetic tests pass; all critical stages covered)
- RQ3 canonical entrypoint audit completed (`RQ3_CANONICAL_ENTRYPOINT_AUDIT.json`)
- Phase 6 handoff adapter completed (`rq3_rq5_handoff_adapter.py`, `RQ3_TO_RQ5_HANDOFF_CONTRACT.json` — status: DATASET_NOT_ADMITTED)
- Route execution ambiguity escalated (`RQ3_ROUTE_EXECUTION_CONTRACT.json`)
- Numeric frame binding documented (`RQ3_NUMERIC_FRAME_BINDING_TESTS.json` — partial, source-grounded final-candidate evidence absent)
- Map identity audit (offline evidence present; live load blocked)
- Sensor progress audit (`RQ3_SENSOR_PROGRESS_TESTS.json` — gates present, live blocked)
- Effective rig audit (`RQ3_EFFECTIVE_RIG_LABEL_TESTS.json` — frozen rig preserved)
- Terminal completion audit (`RQ3_TERMINAL_COMPLETION_TESTS.json` — logic present; adversarial not executed)

---

## Blocked (correctly labeled, not self-certified as PASS)

- `CARLA_SERVER_STARTUP_PASS` — BLOCKED (shader fatal + AV)
- `MANUAL_GRID0828_PASS` — BLOCKED (AV at ALargeMapManager::OnLevelRemovedFromWorld+0x9)
- `AUTOMATIC_TILE_RUNNABLE` — BLOCKED (no server; shader fatal)
- `FROZEN_RQ3_RIG_PASS` — UNDETERMINED (rig identity preserved; live READBACK_VERIFIED blocked)
- `FULL_AUTOMATIC_MAP_LOAD_ADMITTED` — BLOCKED
- `UE_COOK_TOOLCHAIN_READY` — BLOCKED (no source/rebuild admitted)
- `INDEPENDENT_REVIEW` — NOT RUN (only one engineer assigned)

---

## Evidence files preserved (never overwritten)

- `E:\CARLA\CARLA_0.9.16\CarlaUE4\Binaries\Win64\CarlaUE4-Win64-Shipping.exe`
- `E:\CARLA\CARLA_0.9.16\carla-0.9.16-cp312-cp312-win_amd64.whl`
- `E:\CARLA_RUNTIME_QUALIFICATION_c69b60d2_20261021` (reports/logs/minidumps)
- Frozen map-of-record SHA: `370abbbbb365d5e98df0168a0a0ce70c3271e10ad111a9971a7b956c7e94c8c8`
- `C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main` (authority repo)
- All worktrees (no destructive consolidation)

---

## Independent review status

`NOT RUN` — only one engineer available for Phase 6. Requirement before full close: a second independent reviewer validates the fixed modules (`rq3_frame_set.py`, `rq_rq5_handoff_adapter.py`, `experiment_map_pair_authority.py`), verifies test receipts (`test_rq3_frame_set.py`, `test_experiment_manifest_negative_controls.py`), confirms no unintended diff, and reports `INDEPENDENT_REVIEW_PASSED`.
