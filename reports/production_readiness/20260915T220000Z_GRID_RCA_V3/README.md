# Grid0821/Grid0828 Runtime RCA — V3 (Real)

## Status: BLOCKED — CARLA server not reachable

## Commands run and raw output

### 1. Map-of-record SHA256 verification
```
python -c "import hashlib; h=hashlib.sha256(open('campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr','rb').read()).hexdigest(); print(h)"
```
**Output:** `2ca342d8ae4bee39b46e4f96329ee8f3752289468c7e62ac6e5b290c5fde4798`
**Status:** CONFIRMED

### 2. KNOWN_UNSTABLE_MAPS check
```
grep -n KNOWN_UNSTABLE_MAPS ultimate_pipeline/tools/run_perception_safe.py
```
**Output:** `81: KNOWN_UNSTABLE_MAPS = frozenset({"grid0821", "grid0828"})`
**Status:** CONFIRMED — mitigation layer already implemented

### 3. CARLA server connection attempt
```
python -c "import socket; s=socket.socket(); s.settimeout(5); s.connect(('localhost',2000))"
```
**Output:** `ConnectionRefusedError: [WinError 10061] No connection could be made because the target machine actively refused it`
**Status:** BLOCKED — CARLA server not running

### 4. CARLA server log
```
cat E:/CARLA/CARLA_0.9.16/carla_stdout.log
```
**Output:**
```
INFO:  Listening at  0.0.0.0:2002
2026-09-14T13:59:23.373[E] GfnDllWrapper.cpp:38   Could not prepare temp directory for download
2026-09-14T13:59:23.374[E] GfnRunti  APP  TelemetryService.cpp:52   Could not get gfn.dll version: 0
```
**Status:** BLOCKED — Server crashed 2026-09-14, GFN download failures

### 5. Disk space
```
python -c "import shutil; t=shutil.disk_usage('E:/'); print(f'Free: {t.free/(1024**3):.1f}GB')"
```
**Output:** `Free: 13.1GB`
**Status:** CONFIRMED — 13.1GB free, insufficient for UE4 cooking

### 6. E2E test status
```
python -m ultimate_pipeline.cli test e2e
```
**Output:** `⊘ E2E tests skipped (set UP_ENABLE_CARLA_TESTS=1 to enable)`
**Status:** SKIPPED — requires UP_ENABLE_CARLA_TESTS=1

### 7. Offline mitigation tests
```
python -m pytest tests/unit/test_run_perception_safe_unstable_map_mitigations.py -q
```
**Output:** `27 passed`
**Status:** PASS — offline tests verified

## What would need to run once CARLA is reachable

1. Start CARLA server: `E:/CARLA/CARLA_0.9.16/CarlaUE4.exe`
2. Wait for RPC port 2000 to accept connections
3. Run: `python -m ultimate_pipeline.cli run --town grid0821 --use-current-world`
4. Run: `python -m ultimate_pipeline.cli run --town grid0828 --use-current-world`
5. Verify: non-zero frame counts in `recording_summary.json`
6. Verify: no GPU TDR events in Windows Event Viewer

## Prerequisites for live testing
- CARLA server process running and listening on port 2000
- Stable GPU driver (no TDR livelock)
- `UP_ENABLE_CARLA_TESTS=1` environment variable set
- At least 50GB free disk space recommended for large-map cooking

## Evidence written to
`reports/production_readiness/20260915T220000Z_GRID_RCA_V3/GRID_RCA_V3_EVIDENCE.json`
