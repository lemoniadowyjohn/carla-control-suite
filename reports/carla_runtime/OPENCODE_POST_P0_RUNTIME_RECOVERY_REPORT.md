# OPENCODE — POST-P0 RUNTIME RECOVERY REPORT

Date: 2026-10-22 · Author: single engineer · Worktree: `E:\wt\repair-map-realism-p0-837a8504` (RQ3) + `carla_-main` (CARLA source)

## 1. Confirmed handoff from P0 RQ3 remediation

- Implementation SHA (tested): `9e777a270f91299bd20efcc879919029e2956e45`
- Evidence/report SHA: `aeb1d56212a6a8f3d77a83c53f3c5edb006cea4f`
- Post-fix commit: `67d3b357b3c002cfce2db032592e5332ad809d23` (builder `derived_pair_valid` definition restored; 9e777a27 preserved unchanged for Codex review)
- Frozen RQ3 protocol: `configs/rq3_protocol_freeze_v1.json`, SHA-256 `5aa8ae2...`, tracked unedited
- RQ5: untouched (no RQ5 files changed)
- Independent review: `NOT_RUN`
- Paired dataset: `RQ3_PAIRED_DATASET_NOT_ADMITTED`
- Verdict from P0-9: `RQ3_HANDOFF_PARTIAL_EXACT_BLOCKERS`

## 2. Completed tasks (ordered by execution)

### T0 — Source reconciliation (before runtime work)
- Chain verified: `363a1868 → 0ce68d3c → fa564a41 → 2c3a5d86 → 60a73437 → dba5aabe → 9e777a27 → aeb1d56 → 67d3b357`
- All RQ3 source modules tracked; temporary `experiment_map_pair_authority_fixed.py` removed
- `rq3_capture_contract.py`, `rq3_evidence_gate.py`, `rq3_frame_set.py`, `rq3_rq5_handoff_adapter.py`, `capture_transaction.py` all tracked at 9e777a27

### T1 — ALargeMapManager crash (Task 1)
- Verdict: `LARGEMAP_CAUSE_HYPOTHESIS_WITH_EVIDENCE`
- Evidence: source snippet from assignment; binary SHA pinned (`CarlaUE4-Win64-Shipping.exe` in `E:\CARLA\CARLA_0.9.16\CarlaUE4\Binaries\Win64\`, 91.5 MB); no minidump on this workstation (3 historical dumps referenced in assignment are on H: worktree — out of bounds; not recovered); AV signature `writing 0x28` matches null-reference + `0x28` member offset in `FCarlaMapTile`.
- Patch proposal: `TryGetCarlaMapTile()` + guarded ignore in `OnLevelRemovedFromWorld`; negative tests specified; build plan documented; **NOT compiled** (source plugin not vendored locally — `G:\UnrealEngine_4.26_CARLA` binary install lacks plugin source at expected path).
- Deliverable: `reports/carla_runtime/LARGEMAP_AV_ROOT_CAUSE_AND_PATCH.md`

### T2 — Shader-fatal diagnosis (Task 2)
- Verdict: `SHADER_CAUSE_UNRESOLVED_WITH_NEXT_TEST` (runtime startup did not reproduce; cook class confirmed separately)
- Evidence: `WINDOWS_TARGET_RHI_FINAL.json` (D3D ES3_1 material/permutation failure — `Failed to compile Material Instance ... for platform PCD3D_ES31`; `ShadingModel MSM_Hair not supported in feature level ES3_1`); `COOK_620e51db_TERMINAL_RECONCILIATION.json` (ShaderCompileWorker activity, 3.19 GB unproven); `CARLA_RUNTIME_HARDENING_V2.json` (previous live session `PID 42088`, `RUNTIME_READY`; no shader fatal on `-RenderOffScreen -quality-level=Low`).
- Competing hypotheses evaluated (9 hypotheses with evidence/contra/test for each); driver 573.22 not changed (operator-approval required, no rollback plan executed).
- No blanket cache deletion; no driver replacement.
- Deliverable: `reports/carla_runtime/SHADER_FATAL_FIRST_CAUSE.json`

### T3 — Bounded low-resource startup (Task 3) — PRIMARY OBJECTIVE
- Verdict: `SERVER_PROCESS_ALIVE`; `RPC_READY`; `WORLD_TICKS_READY`; `RENDERING_READY`; `SENSOR_READY` (single diagnostic RGB only — not frozen rig)
- Execution: `C:\temp\py312_venv\Scripts\python.exe tools/carla_runtime_launch.py --wait-port-seconds 60 --rpc-timeout 25` (default `-RenderOffScreen -quality-level=Low -nosound`)
- Results: PID 36076 (launcher) / 22152 (shipping); `get_server_version()="0.9.16"`; `world_get_map()="Carla/Maps/Town10HD_Opt"`; `snapshot_frame=11` at handshake; 15 available maps; RPC 2000 + streaming 2001 both listening.
- No shader fatal reproduced; server stable until explicit termination.
- Deliverable: `reports/carla_runtime/CARLA_BOUNDED_STARTUP_RESULTS.json`
- Note: previous receipt (`CARLA_RUNTIME_RECEIPT.json`, 2026-10-02) already proved `RUNTIME_READY` with identical flags; this session confirms repeatability.

### T4 — Manual map + small XODR + minimal sensor (Task 4)
- Stage A (manual Grid0828): **PASS** — `load_world("Grid0828")` succeeded; map identity `Grid0828/Maps/Grid0828/Grid0828`; ticks 2383 → 4231 → 4238.
- Stage B (small standalone XODR): **NOT EXECUTED LIVE** — design preserved; requires `generate_opendrive_world()` with exact payload SHA; no synthetic XODR fixture was injected into live server (to avoid crash risk with un-tested payload).
- Stage C (diagnostic RGB): **PASS** — 640×480, 2 callbacks, `raw_bytes=1,228,800`, `pixel_std=18.57`, `nonempty_rendered_pixels=true`; tick progression verified (`frame_before=4231`, `after=4238`).
- Deliverable: `reports/carla_runtime/CARLA_BOUNDED_TASK4_20261022.json`; `CARLA_BOUNDED_TASK4_STAGE_C_RGB.json`

### T5 — Quadro P3200 capacity (Task 5)
- Verdict: `QUADRO_P3200_CAN_START_LOW_RESOURCE`; `FULL_RQ3_RIG_BEYOND_MEASURED_CAPACITY`
- Measurements: startup idle 686 MiB → Town10HD load 5857 MiB / 167 MiB free / 61% GPU; Grid0828 load 3847 MiB / 2177 MiB free / 18% GPU; 12 CPU threads idle during load.
- Bottleneck: GPU VRAM (6 GiB cap), not CPU/commit.
- Recommendation: do not silently reduce scientific sensor resolution/FR/lidar; use low-resource profile for qualification only.
- Deliverable: `reports/carla_runtime/QUADRO_P3200_RUNTIME_CAPACITY.json`

### T6 — Storage & native toolchain admission (Task 6)
- Storage: C 9.9 GB / D 1.2 GB / E 4.2 GB / F 2.2 GB / G 5.1 GB / H 12.3 GB free; total ~475.9 GB (C), 931.5 GB (G/H).
- Native build: `UE4_ROOT=G:\UnrealEngine_4.26_CARLA` exists; `ShaderCompileWorker.exe` present; `CarlaUE4-Win64-Shipping.exe` intact; source plugin `LargeMapManager.cpp` NOT vendored locally → source build blocked.
- Admission: `STORAGE_TIGHT_NOT_UNSAFE`; `NATIVE_BUILD_NOT_ADMITTED` (requires vendored source + MSVC + >30 GB disk, not executed).
- No protected artifacts deleted; `E:\wt` worktree preserved.
- Deliverable: `reports/carla_runtime/CARLA_STORAGE_AND_NATIVE_BUILD_ADMISSION.md`

### T7 — Test baseline classification (Task 7)
- Before/after: 112 PASS / 18 FAIL (first run, venv, 2026-10-21 22:45Z) → after builder fix (67d3b357): 53 PASS / 0 FAIL on targeted subset (builder + paired contract + adversarial + receipt); full suite not fully re-measured due to time, but root causes classified.
- Root-cause classification (all documented in `POST_P0_TEST_BASELINE_CLASSIFICATION.json`):
  - 9 = regression from P0-3 builder `derived_pair_valid` missing definition (`NameError`). FIXED in `67d3b357`; 9e777a27 preserved.
  - 1 = new P0-4 artifact test harness state-reuse (duplicate identity check) — test-only.
  - 4 = pre-existing `build_final_receipt` import error (not RQ3-relevant).
  - 3 = pre-existing `NEW-295` CRS/frame tests (not RQ3-relevant).
- No masking; no false PASS claims; failures preserved and attributed.
- Independent verification of 9e777a27: **NOT DONE** — Codex review required.
- Deliverable: `reports/carla_runtime/POST_P0_TEST_BASELINE_CLASSIFICATION.json`

### T8 — Scientific authority boundaries (Task 8)
- Unresolved gates preserved and visible: full static map acceptance, P0-E absolute georeference verification, regulatory-object provenance, complete automatic map regeneration, Independent Review A, CARLA native stability (now partially qualified — startup passes, teardown unverified), RQ3 route execution semantics, real paired capture, RQ5 compute/data admission.
- Continuous-driving vs pose-replay: not chosen; frozen protocol governs; no scientific claim modified.

## 3. Hardware / environment measures used

- Interpreter verified: `C:\temp\py312_venv\Scripts\python.exe`; Python 3.12.2
- CARLA import verified: `import carla` PASS; `carla.Client` available
- GPU adapter: NVIDIA Quadro P3200 Max-Q (driver 573.22); 6144 MiB total; 167 MiB free after Town10HD load; 2177 MiB free after Grid0828.
- CPU: 12 threads (i7-8850H); idle during server startup.
- Storage gate: met for working set; not met for full UE build + large-map regeneration.

## 4. Changes actually implemented (this session only — not RQ3 source)

- `reports/carla_runtime/` — 11 new deliverable files added (startup, task4, shader, large-map, capacity, storage, baseline, patch, receipts, verdict).
- `E:\CARLA\CARLA_0.9.16\CarlaUE4.exe` — **not edited**; launcher SHA unchanged (verified `0bc4...`).
- Server PID 22152 / 36076 — started and **terminated cleanly** (no global `taskkill`; only owned PID stopped).
- RQ3 worktree (`E:\wt\repair-map-realism-p0-837a8504`) — no new RQ3 source modifications during this session (only the pre-existing `67d3b357` builder fix was applied before this session started; nothing changed during runtime work).

## 5. Proposed but unimplemented patches (explicitly not applied)

- `ALargeMapManager` source fix (Task 1): proposal documented; not compiled; no binary edited.
- Shader-cache invalidation / driver update (Task 2): not performed (operator approvals / rollback plans missing; no evidence that cache is corrupted — cook failure is a separate class from runtime startup failure).
- Full Ingolstadt regeneration / RQ5 training: blocked by storage, dataset admission, and independent review.
- UE source build: blocked by missing vendored plugin source and disk budget.

## 6. Final verdicts per required category

| Category | Verdict | Evidence file |
|---|---|---|
| Native crash root cause (ALargeMapManager) | `LARGEMAP_CAUSE_HYPOTHESIS_WITH_EVIDENCE` — source snippet + binary SHA + AV signature match; source not vendored; no minidump; teardown path unexercised | `LARGEMAP_AV_ROOT_CAUSE_AND_PATCH.md` |
| Shader root cause (runtime) | `SHADER_CAUSE_UNRESOLVED_WITH_NEXT_TEST` — startup did not reproduce; cook failure confirmed separate (D3D ES3_1); driver change not executed | `SHADER_FATAL_FIRST_CAUSE.json` |
| Server startup | `SERVER_PROCESS_ALIVE` / `RPC_READY` / `WORLD_TICKS_READY` / `RENDERING_READY` at 22:45Z | `CARLA_BOUNDED_STARTUP_RESULTS.json` |
| RPC readiness | `PASS` (server 0.9.16; 15 maps; snapshot frame 11) | `CARLA_BOUNDED_STARTUP_RESULTS.json` |
| Simulation ticks | `PASS` (frame 11 → 2383 → 4231 → 4238; monotonic; no stalls) | `CARLA_BOUNDED_TASK4_20261022.json` |
| Manual-map loading (Grid0828) | `PASS` | `CARLA_BOUNDED_TASK4_20261022.json` |
| Small-XODR loading | `DESIGN_ONLY` — strict payload required; live injection not performed to preserve crash-free session | `MANUAL_AND_SMALL_XODR_RUNTIME_MATRIX.json` |
| Diagnostic sensor rendering | `PASS` (640×480 RGB; nonempty pixels; 2 callbacks; tick advance) | `CARLA_BOUNDED_TASK4_STAGE_C_RGB.json` |
| Frozen RQ3 rig feasibility | `BEYOND_MEASURED_CAPACITY` — Quadro 6 GiB insufficient for full packed-studio rig under streaming; qualification only at low-resource profile | `QUADRO_P3200_RUNTIME_CAPACITY.json` |
| UE build feasibility | `NOT_ADMITTED` — source plugin missing; storage tight; MSVC not audited | `CARLA_STORAGE_AND_NATIVE_BUILD_ADMISSION.md` |

## 7. Independent review and claim state

- Implementation under independent review: `9e777a270f91299bd20efcc879919029e2956e45` (original); fix at `67d3b357b3c002cfce2db032592e532...` (separate).
- Independent Codex reviewer: **NOT RUN**.
- No claim of `RQ3_HANDOFF_SOFTWARE_VERIFIED` or `RQ3_PAIRED_DATASET_ADMITTED` issued.
- No production merge authorized.
- RQ5 not modified; frozen protocols preserved.
- No synthetic dataset promoted to authoritative evidence.

## 8. Final one-line summary

`RQ3_P0_REMediation_9e777a27_Active; CARLA_Runtime_Ready_OffScreen_Low_20261021; LargeMap_Hypothesis_Evidence_Only; Shader_Unresolved_Next_Test; RQ3_Dataset_NOT_ADMITTED; Independent_Review_NOT_RUN; No_Production_Merge.`
