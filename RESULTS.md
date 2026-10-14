# RESULTS — CARLA 0.9.16 source server build/verify (2026-09-24)

## Verdict: INCOMPLETE — source checkout and UE4 source build NOT located

This session did NOT advance UE4_ENGINE_PASS to CARLA_SOURCE_RUNTIME_PASS.

## 1. Source checkout
- Only CARLA tree on disk: `E:\CARLA\CARLA_0.9.16` = packaged binary
  distribution (CarlaUE4.exe 191488 bytes; Engine/ = packaged engine;
  `CarlaUE4\CarlaUE4.uproject` exists, 2170 bytes).
- No Makefile, Build.sh, CarlaUE4.sh, or .git found there.
- CARLA git SHA: NOT_FOUND. Branch/tag: 0.9.16 inferred only.

## 2. Environment
- UE4_ROOT: UNRESOLVED. No CARLA-patched UE4.26 source clone with
  Setup.bat / GenerateProjectFiles.bat / source-built UE4Editor.exe found
  in any targeted check. Full-drive recursive searches timed out (120 s+)
  and are recorded as INCOMPLETE, not pass.
- Prior-claim evidence (Setup PASS, GenerateProjectFiles PASS, UE4Editor
  build exit 0, 25 s smoke) was NOT re-verified on disk. Per task order,
  no engine rebuild was attempted.

## 3. Build ladder
- `make PythonAPI`: NOT_RUN. `make launch`: NOT_RUN. No logs/exit codes.

## 4. Runtime / RPC
- No source server launched; RPC handshake NOT_RUN. Port-listening was
  never used as a gate. Packaged binary deliberately NOT launched.
- Source-level GAP-017 instrumentation (plugin init, rpc::server,
  bind/listen, worker threads, handler registration, get_server_version,
  asio loop, game-thread dispatch): NOT_STARTED — no source to instrument.

## 5. Packaged vs source comparison
- BLOCKED: no source build exists to compare against packaged 0.9.16
  binary. GAP-017 remains undetermined (packaged/env vs source-runtime).

## 6. Maps
- `get_available_maps()` NOT_RUN. Grid0828 availability in THIS source
  build: UNKNOWN. Cached Grid0828 data under
  `C:\Users\admin\carlaCache\0.9.16\Grid0828` is not runtime evidence.

## Acceptance
- CARLA_SOURCE_BUILD = FAIL_NOT_FOUND
- RPC_SERVER_VERSION = NOT_RUN
- AVAILABLE_MAPS_QUERY = NOT_RUN
- STOCK_WORLD_LOAD = NOT_RUN

## GAP-017 / GAP-018
- No state change. No new runtime evidence. Record stays as prior.

## Artifacts (this repo root)
- CARLA_SOURCE_BUILD_RECEIPT.json, RPC_HANDSHAKE_TRACE.json,
  AVAILABLE_MAPS.json, RESULTS.md (this file) — all report NOT_FOUND /
  NOT_RUN where applicable. No PASS fabricated.
