# CARLA Perception Recording - PowerShell Runbook

Windows-safe commands for thesis perception recording with CARLA 0.9.16.

## 1. Find and Kill Existing CARLA Processes

```powershell
# Find processes using port 2000
$carlaPort = 2000
$conn = netstat -ano | Select-String ":$carlaPort\s+.*LISTENING"
if ($conn) {
    $pidMatch = $conn -match '\s+(\d+)\s*$'
    if ($pidMatch) {
        $procId = $Matches[1]
        Write-Host "Found process $procId on port $carlaPort"
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Write-Host "Killed process $procId"
    }
}

# Or kill all CarlaUE4 processes directly
Get-Process -Name "CarlaUE4*" -ErrorAction SilentlyContinue | Stop-Process -Force
```

## 2. Start CARLA

```powershell
# Main exe (full quality)
$carlaExe = "E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"

# Alternative: Shipping exe (lower quality, faster startup)
# $carlaExe = "E:\CARLA\CARLA_0.9.16\CarlaUE4\Binaries\Win64\CarlaUE4-Win64-Shipping.exe"

Start-Process -FilePath $carlaExe
Write-Host "Started CARLA, waiting for startup..."
Start-Sleep -Seconds 15
```

## 3. Harden XODR Before Loading

```powershell
$xodrIn = "path\to\your\map.xodr"
$xodrOut = "path\to\your\map_hardened.xodr"
$reportJson = "path\to\hardener_report.json"

python -m ultimate_pipeline.tools.xodr_carla_hardener `
    --in $xodrIn `
    --out $xodrOut `
    --report-json $reportJson `
    --fix-roadmarks `
    --fix-laneoffset-junctions `
    --clamp-s-endpoints `
    --parampoly3-sanity `
    --repair-parampoly3-to-line `
    --auto-repair-connectivity

# Check report
Get-Content $reportJson | ConvertFrom-Json | Format-List
```

## 4. Probe CARLA Readiness

```powershell
$carlaHost = "127.0.0.1"
$carlaPort = 2000

# Use probe tool
python -m ultimate_pipeline.tools.probe_carla --host $carlaHost --port $carlaPort

# With town load test
python -m ultimate_pipeline.tools.probe_carla --host $carlaHost --port $carlaPort --town Grid0821 --list-maps
```

## 5. Smoke Recording (5 seconds)

**Note:** The `--host` and `--port` flags are used for both CARLA world connection
AND TrafficManager setup. If using a non-default port, ensure both are accessible.

```powershell
$calibFile = "calib_data.json"
$outDir = "recordings"

# Grid0821 smoke test
python -m ultimate_pipeline.perception.record_route `
    --town Grid0821 `
    --calib $calibFile `
    --out-dir "$outDir\smoke_grid0821" `
    --spawn-index 0 `
    --seed 0 `
    --fps 10 `
    --duration 5

# Grid0828 smoke test
python -m ultimate_pipeline.perception.record_route `
    --town Grid0828 `
    --calib $calibFile `
    --out-dir "$outDir\smoke_grid0828" `
    --spawn-index 0 `
    --seed 0 `
    --fps 10 `
    --duration 5
```

## 6. Full Recording with Hardened XODR

```powershell
python -m ultimate_pipeline.perception.record_route `
    --xodr $xodrOut `
    --calib $calibFile `
    --out-dir "$outDir\xodr_run" `
    --spawn-index 0 `
    --seed 42 `
    --fps 20 `
    --duration 60 `
    --harden-xodr
```

## 7. Verify Output

```powershell
# Check meta.json
Get-ChildItem -Path $outDir -Recurse -Filter "meta.json" | ForEach-Object {
    Write-Host "=== $($_.FullName) ==="
    Get-Content $_.FullName | ConvertFrom-Json | Format-List
}
```

## Error Scenarios

| Symptom | Likely Cause | Action |
|---------|--------------|--------|
| Port 2000 closed | CARLA not running | Start CARLA |
| RPC timeout | CARLA starting/hung | Wait or restart |
| EXCEPTION_ACCESS_VIOLATION | XODR crash | Use hardener |
| Town* fallback | Map load failed | Check UP_THESIS_STRICT |

### record_route.py CLI Reference

| Argument | Default | Description |
|----------|---------|-------------|
| `--xodr` | (mutex) | Path to OpenDRIVE map file |
| `--town` | (mutex) | CARLA world name (Grid0821, Grid0828) |
| `--calib` | (required) | Path to calib_data.json |
| `--out-dir` | (required) | Base output folder |
| `--host` | 127.0.0.1 | CARLA host (also used for TrafficManager) |
| `--port` | 2000 | CARLA port (also used for TrafficManager) |
| `--tm-port` | 8000 | TrafficManager port |
| `--seed` | 42 | TM random seed for determinism |
| `--spawn-index` | 0 | Exact spawn point index |
| `--fps` | 20 | Recording FPS |
| `--duration` | 60 | Duration in seconds |

**Important:** `--host` and `--port` are used for both CARLA client connection and
TrafficManager setup. The TM is configured via a fresh `carla.Client(host, port)` call.

## 8. Perception Pair Experiment (Thesis Domain Gap)

Two-arm experiment runner for thesis domain-gap analysis. Records comparable
datasets from manual maps (Grid0821/Grid0828) and auto-generated XODR maps.

### Prerequisites

- CARLA running and ready (see sections 1-4)
- Manual map loaded (Grid0821 or Grid0828)
- Auto-generated XODR from pipeline (e.g., `ultimate_pipeline_out/run_001/08_final_tile_001.xodr`)
- Calibration file (`calib_data.json`)

### Run Paired Recording

```powershell
$calibFile = "calib_data.json"
$xodrAuto = "ultimate_pipeline_out\run_001\08_final_tile_001.xodr"
$outRoot = "recordings\pairs"

# Run two-arm experiment: Arm A = manual map, Arm B = auto XODR
python -m ultimate_pipeline.tools.run_perception_pair `
    --manual-town Grid0821 `
    --xodr-in $xodrAuto `
    --calib $calibFile `
    --out-root $outRoot `
    --spawn-index 0 `
    --fps 10 `
    --duration 5 `
    --seed 42 `
    --strict
```

### Output Structure

```
recordings/pairs/pair_Grid0821_20260111_120000/
├── pair_manifest.json    # Experiment config + results
├── arm_A_manual/         # Manual map recordings
│   └── route_*/
│       ├── meta.json
│       ├── rgb/
│       └── lidar/
└── arm_B_auto/           # Auto XODR recordings
    └── route_*/
        ├── meta.json
        ├── rgb/
        └── lidar/
```

### Offline Gap Analysis

After recording, run offline domain-gap analysis:

```powershell
$manifest = "recordings\pairs\pair_Grid0821_20260111_120000\pair_manifest.json"

# Basic analysis (no manual XODR for geometry comparison)
python -m ultimate_pipeline.tools.run_offline_gaps_from_pair `
    --manifest $manifest

# Full analysis with manual XODR for geometry/curvature/intersection gaps
python -m ultimate_pipeline.tools.run_offline_gaps_from_pair `
    --manifest $manifest `
    --manual-xodr "manual_maps\Grid0821.xodr" `
    --compute-composite

# Fast mode (skip Hausdorff for large maps)
python -m ultimate_pipeline.tools.run_offline_gaps_from_pair `
    --manifest $manifest `
    --manual-xodr "manual_maps\Grid0821.xodr" `
    --skip-hausdorff
```

### Gap Report Output

```
recordings/pairs/pair_Grid0821_20260111_120000/
├── pair_manifest.json
├── gap_report.json       # Domain gap metrics
└── ...
```

### CLI Reference

**run_perception_pair.py**

| Argument | Default | Description |
|----------|---------|-------------|
| `--manual-town` | (required) | Grid0821 or Grid0828 |
| `--xodr-in` | (required) | Auto-generated XODR path |
| `--calib` | (required) | Calibration JSON |
| `--out-root` | (required) | Output directory |
| `--spawn-index` | 0 | Spawn point index |
| `--fps` | 10 | Recording FPS |
| `--duration` | 5 | Duration in seconds |
| `--seed` | 42 | TM random seed |
| `--strict/--no-strict` | true | UP_THESIS_STRICT mode |
| `--repair-parampoly3-to-line` | false | Repair bad paramPoly3 |

**run_offline_gaps_from_pair.py**

| Argument | Default | Description |
|----------|---------|-------------|
| `--manifest` | (required) | pair_manifest.json path |
| `--manual-xodr` | (none) | Manual map XODR for comparison |
| `--skip-hausdorff` | false | Skip Hausdorff (faster) |
| `--skip-geometry` | false | Skip geometry gap |
| `--skip-curvature` | false | Skip curvature gap |
| `--skip-intersection` | false | Skip intersection gap |
| `--compute-composite` | false | Compute composite score |
| `--out` | offline_gap_report.json | Output path |
| `--autostart-carla-exe` | (none) | Path to CarlaUE4.exe for auto-start |
| `--autostart-wait` | 90 | Max seconds to wait for CARLA startup |

### Arm Status Codes

The pair manifest uses machine-parseable status codes per arm:

| Status | Description |
|--------|-------------|
| `SUCCESS` | Recording completed successfully |
| `CARLA_NOT_REACHABLE` | CARLA was not running and auto-start not configured |
| `CARLA_CRASHED_DURING_LOAD_OR_RECORD` | CARLA crashed (port closed after attempt) |
| `STRICT_MAP_IDENTITY_FAIL` | UP_THESIS_STRICT blocked Town* fallback |
| `RECORD_ROUTE_FAILED` | Generic recording failure |

## 9. One-Button Experiment (Full Pipeline)

Complete end-to-end experiment with auto-start CARLA, paired recording, and offline gap analysis.

```powershell
# Configuration
$carlaExe = "E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"
$calibFile = "calib_data.json"
$xodrAuto = "ultimate_pipeline_out\run_001\08_final_tile_001.xodr"
$outRoot = "recordings\pairs"

# Step 1: Run paired experiment with auto-start
python -m ultimate_pipeline.tools.run_perception_pair `
    --manual-town Grid0821 `
    --xodr-in $xodrAuto `
    --calib $calibFile `
    --out-root $outRoot `
    --spawn-index 0 `
    --fps 10 `
    --duration 5 `
    --seed 42 `
    --strict `
    --autostart-carla-exe $carlaExe

# Step 2: Find the latest manifest
$latestPair = Get-ChildItem -Path $outRoot -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
$manifest = Join-Path $latestPair.FullName "pair_manifest.json"
Write-Host "Using manifest: $manifest"

# Step 3: Run offline gap analysis (without manual XODR - gaps will be skipped)
python -m ultimate_pipeline.tools.run_offline_gaps_from_pair `
    --manifest $manifest

# Step 4: Check results
$report = Join-Path $latestPair.FullName "offline_gap_report.json"
Get-Content $report | ConvertFrom-Json | Format-List
```

### With Manual XODR for Full Gap Analysis

If you have an OpenDRIVE export of the manual map:

```powershell
# Same as above, but with manual XODR for gap computation
$manualXodr = "manual_maps\Grid0821.xodr"

python -m ultimate_pipeline.tools.run_offline_gaps_from_pair `
    --manifest $manifest `
    --manual-xodr $manualXodr `
    --compute-composite `
    --skip-hausdorff
```

### Example Output Structure

```
recordings/pairs/pair_Grid0821_20260111_120000/
├── pair_manifest.json          # Experiment manifest (schema_version: 2)
├── offline_gap_report.json     # Gap analysis report (schema_version: 2)
├── arm_A_manual/
│   └── route_20260111_120001/
│       ├── meta.json
│       ├── rgb/
│       └── lidar/
└── arm_B_auto/
    └── route_20260111_120030/
        ├── meta.json
        ├── rgb/
        └── lidar/
```

### Checking Experiment Status

```powershell
# Check pair manifest for arm statuses
$manifestContent = Get-Content $manifest | ConvertFrom-Json
Write-Host "Overall success: $($manifestContent.success)"
Write-Host "Arm A status: $($manifestContent.arms.A_manual.status)"
Write-Host "Arm B status: $($manifestContent.arms.B_auto.status)"

# Check for crashes
if ($manifestContent.arms.A_manual.crash_suspected -or $manifestContent.arms.B_auto.crash_suspected) {
    Write-Host "WARNING: CARLA crash suspected!"
}

# Check gap summary
$gapReport = Get-Content $report | ConvertFrom-Json
Write-Host "Gaps computed: $($gapReport.summary.computed)"
Write-Host "Gaps skipped: $($gapReport.summary.skipped)"
Write-Host "Gaps failed: $($gapReport.summary.failed)"
```

## 10. VRAM/OOM Mitigation

If you encounter "out of memory trying to allocate rendering resources" crashes, especially
when loading Grid0821 or complex XODR maps, use these mitigation strategies.

### Symptoms

- UE4 crash: "out of memory trying to allocate rendering resources"
- CARLA becomes unreachable during map load
- `CARLA_CRASHED_DURING_LOAD_OR_RECORD` status in pair manifest

### Solutions

#### Low-Memory Mode (Recommended)

Use `--low-mem` to reduce camera resolution to 800x600:

```powershell
# record_route.py with low-mem
python -m ultimate_pipeline.perception.record_route `
    --town Grid0821 `
    --calib $calibFile `
    --out-dir "$outDir\low_mem_test" `
    --spawn-index 0 `
    --fps 10 `
    --duration 5 `
    --low-mem

# run_perception_pair.py with low-mem
python -m ultimate_pipeline.tools.run_perception_pair `
    --manual-town Grid0821 `
    --xodr-in $xodrAuto `
    --calib $calibFile `
    --out-root $outRoot `
    --low-mem
```

The `--low-mem` flag:
- Sets all RGB cameras to 800x600 (vs. default calibration sizes)
- Reduces VRAM footprint significantly
- Recorded in `meta.json` as `low_mem: true` and `low_mem_resolution: [800, 600]`

#### Windowed Autostart (Alternative to RenderOffScreen)

`-RenderOffScreen` mode can use more VRAM than windowed mode on some systems:

```powershell
# Use windowed mode with small resolution
python -m ultimate_pipeline.tools.run_perception_pair `
    --manual-town Grid0821 `
    --xodr-in $xodrAuto `
    --calib $calibFile `
    --out-root $outRoot `
    --low-mem `
    --autostart-carla-exe $carlaExe `
    --autostart-windowed `
    --autostart-res-x 1024 `
    --autostart-res-y 768
```

#### Environment Variable Scale (Advanced)

For finer-grained control over camera resolution:

```powershell
$env:UP_CAMERA_SCALE = "0.5"  # 50% of calibration resolution
python -m ultimate_pipeline.perception.record_route ...
```

#### Camera Whitelist (Minimal Sensors)

Record with only specific cameras:

```powershell
$env:UP_CAMERA_WHITELIST = "front_left,front_right"
python -m ultimate_pipeline.perception.record_route ...
```

### GPU VRAM Guidelines

| VRAM | Recommendation |
|------|----------------|
| < 4GB | Use `--low-mem`, windowed mode, camera whitelist |
| 4-6GB | Use `--low-mem` |
| 6-8GB | Default settings usually work |
| > 8GB | Full resolution recommended |

### CLI Reference

**record_route.py VRAM options:**

| Argument | Description |
|----------|-------------|
| `--low-mem` | Reduce cameras to 800x600 |

**run_perception_pair.py VRAM options:**

| Argument | Default | Description |
|----------|---------|-------------|
| `--low-mem` | false | Forward to record_route |
| `--autostart-windowed` | false | Use windowed mode |
| `--autostart-res-x` | 1024 | Windowed width |
| `--autostart-res-y` | 768 | Windowed height |

## 11. Running on HPC / High-End GPUs

For HPC clusters, workstations, or high-end gaming GPUs, use explicit profile selection
for reproducibility across different machines.

### Scientific Reproducibility

The `--experiment-standard` mode (default) ensures:
- **No auto-increase** of resolution or FPS on high-end hardware
- **Auto-decrease only** on low-end hardware for safety
- Same experiment parameters across laptop, gaming PC, and HPC

```powershell
# Standard mode (default) - recommended for thesis experiments
python -m ultimate_pipeline.tools.run_perception_pair `
    --manual-town Grid0821 `
    --xodr-in $xodrAuto `
    --calib $calibFile `
    --out-root $outRoot `
    --profile research `
    --experiment-standard
```

### Hardware Profiles

| Profile | VRAM | Use Case |
|---------|------|----------|
| `research` | >=12GB | HPC / workstation (A100, RTX 4090, etc.) |
| `gaming` | 8-12GB | Gaming GPU (RTX 3080, etc.) |
| `laptop` | 4-8GB | Laptop / mobile GPU |
| `low_end` | <4GB | Integrated / low-end (auto-enables low-mem) |
| `auto` | detect | Auto-detect from WMI (default) |

### Explicit Profile Selection (Recommended for HPC)

```powershell
# Force research profile on HPC (no auto-detection)
python -m ultimate_pipeline.tools.run_perception_pair `
    --manual-town Grid0821 `
    --xodr-in $xodrAuto `
    --calib $calibFile `
    --out-root $outRoot `
    --profile research

# Force laptop profile for testing on high-end machine
python -m ultimate_pipeline.tools.run_perception_pair `
    --manual-town Grid0821 `
    --xodr-in $xodrAuto `
    --calib $calibFile `
    --out-root $outRoot `
    --profile laptop
```

### Max-Performance Mode (Advanced)

For exploratory runs where you want the highest quality on high-end hardware:

```powershell
# Allow higher settings on high-end (NOT recommended for reproducible experiments)
python -m ultimate_pipeline.tools.run_perception_pair `
    --manual-town Grid0821 `
    --xodr-in $xodrAuto `
    --calib $calibFile `
    --out-root $outRoot `
    --profile research `
    --max-performance `
    --no-experiment-standard
```

### Manifest Policy Traceability

The pair manifest (v3) records:
- `hardware_detection`: detected VRAM, GPU name, profile
- `policy_decisions`: effective profile, low_mem_enabled, policy_reason, auto_adjusted
- `config.low_mem_explicit`: user-provided --low-mem flag
- `config.low_mem_enabled`: effective low-mem after policy

Example manifest excerpt:
```json
{
  "schema_version": 3,
  "hardware_detection": {
    "vram_gb": 24.0,
    "profile": "research",
    "gpu_name": "NVIDIA GeForce RTX 4090"
  },
  "policy_decisions": {
    "effective_profile": "research",
    "low_mem_enabled": false,
    "policy_reason": "explicit --profile research",
    "auto_adjusted": false
  }
}
```

### CLI Reference

**Experiment mode flags:**

| Argument | Default | Description |
|----------|---------|-------------|
| `--experiment-standard` | true | Never auto-increase on high-end |
| `--no-experiment-standard` | - | Disable standard mode |
| `--max-performance` | false | Allow higher settings on high-end |
| `--profile` | auto | Force hardware profile |

## 12. Smoke Test & Troubleshooting (Thesis Canonical Procedure)

Use this section to verify your environment before running experiments.

### Step 0: Locate calib_data.json

```powershell
# Find calib_data.json in repo
Get-ChildItem -Path . -Recurse -Filter "calib_data.json" -ErrorAction SilentlyContinue | Select-Object FullName

# Common locations
$calibCandidates = @(
    ".\calib_data.json",
    ".\ultimate_pipeline\sensors\calib_data.json",
    ".\config\calib_data.json"
)
$calibFile = $calibCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($calibFile) {
    Write-Host "Found calib: $calibFile"
} else {
    Write-Host "ERROR: calib_data.json not found. Create one or copy from sensor_configuration/"
}
```

### Step 1: No-CARLA Tests (Offline Validation)

These tests verify code without requiring CARLA:

```powershell
# Self-test for perception pair policy logic
$env:UP_SELFTEST = "1"
python -m ultimate_pipeline.tools.run_perception_pair
# Expected: "[SELFTEST] All tests passed!" and exit 0

# Pytest (if installed)
python -m pytest ultimate_pipeline/tests/test_perception_pair_args.py -v

# XODR hardener dry-run (no CARLA needed)
python -m ultimate_pipeline.tools.xodr_carla_hardener --help
```

### Step 2: carla_probe Expected Outputs

```powershell
python -m ultimate_pipeline.tools.probe_carla --host 127.0.0.1 --port 2000
```

| Output Pattern | Meaning | Action |
|----------------|---------|--------|
| `TCP port 2000: CLOSED` | CARLA not running | Start CARLA |
| `TCP port 2000: OPEN` + `RPC: FAILED` | CARLA starting or hung | Wait 30s, retry |
| `RPC: OK` + `Server version: 0.9.16` | CARLA ready | Proceed to Step 3 |
| `Timeout after 5.0s` | Network/firewall issue | Check firewall rules |

### Step 3: Minimal CARLA Recording (10s Low-Mem)

```powershell
$calibFile = ".\ultimate_pipeline\sensors\calib_data.json"  # Adjust path
$outDir = ".\recordings\smoke"

python -m ultimate_pipeline.perception.record_route `
    --town Grid0821 `
    --calib $calibFile `
    --out-dir $outDir `
    --spawn-index 0 `
    --fps 10 `
    --duration 10 `
    --low-mem

# Verify output
Get-ChildItem -Path $outDir -Recurse -Filter "meta.json"
```

Expected: `meta.json` created with `success: true`, `low_mem: true`.

### Step 4: HPC Minimal Run (Linux/Slurm)

For HPC clusters without display:

```bash
# Load modules (adjust for your cluster)
module load python/3.10 cuda/12.1

# Install deps in venv
python -m venv .venv && source .venv/bin/activate
pip install -r ultimate_pipeline/requirements-hpc.txt

# Self-test (no CARLA)
UP_SELFTEST=1 python -m ultimate_pipeline.tools.run_perception_pair
# Expected: All tests passed

# Note: Full CARLA recording requires X11 forwarding or VirtualGL
# Use --profile research to skip VRAM auto-detection on HPC
```

### Troubleshooting Common Errors

#### "Serialization Error: Corrupt data found"

**Symptom:** CARLA crashes at startup with serialization error.

**Causes:**
1. Stale OpenDRIVE cache from previous session
2. Incompatible map format loaded
3. Memory corruption from OOM

**Solutions:**
```powershell
# 1. Kill all CARLA processes and restart fresh
Get-Process -Name "CarlaUE4*" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 5

# 2. Delete CARLA cache (if exists)
$carlaCache = "$env:LOCALAPPDATA\CarlaUE4"
if (Test-Path $carlaCache) {
    Remove-Item -Path $carlaCache -Recurse -Force
    Write-Host "Deleted CARLA cache"
}

# 3. Start CARLA with clean state
Start-Process -FilePath $carlaExe
Start-Sleep -Seconds 20

# 4. Re-probe
python -m ultimate_pipeline.tools.probe_carla --host 127.0.0.1 --port 2000
```

#### "EXCEPTION_ACCESS_VIOLATION" on XODR Load

**Symptom:** CARLA crashes when loading OpenDRIVE map.

**Solutions:**
```powershell
# 1. Always use hardener before loading XODR
python -m ultimate_pipeline.tools.xodr_carla_hardener `
    --in $xodrIn --out $xodrOut `
    --fix-roadmarks --fix-laneoffset-junctions `
    --clamp-s-endpoints --parampoly3-sanity `
    --repair-parampoly3-to-line --auto-repair-connectivity

# 2. Check report for remaining issues
Get-Content hardener_report.json | ConvertFrom-Json | Select-Object -ExpandProperty summary
```

#### "out of memory trying to allocate rendering resources"

**Symptom:** UE4 OOM crash during map load or recording.

**Solutions:**
```powershell
# Use low-mem mode + windowed autostart
python -m ultimate_pipeline.tools.run_perception_pair `
    --manual-town Grid0821 `
    --xodr-in $xodrAuto `
    --calib $calibFile `
    --out-root $outRoot `
    --low-mem `
    --autostart-carla-exe $carlaExe `
    --autostart-windowed `
    --autostart-res-x 800 `
    --autostart-res-y 600
```

#### Placeholder Calib Path Errors

**Symptom:** `FileNotFoundError: --calib not found: 'path/to/calib_data.json'`

**Solution:** Use Step 0 to locate the actual calib file. Common valid paths:
- `.\ultimate_pipeline\sensors\calib_data.json`
- `.\calib_data.json`
- `.\config\calib_data.json`

#### UP_THESIS_STRICT Fallback Block

**Symptom:** `STRICT_MAP_IDENTITY_FAIL` status in manifest.

**Meaning:** CARLA loaded a Town* fallback instead of the requested map.

**Solutions:**
```powershell
# 1. Check map availability
python -m ultimate_pipeline.tools.probe_carla --list-maps

# 2. Ensure Grid0821/Grid0828 are installed in CARLA
# 3. Use --no-strict to allow fallback (not recommended for thesis)
```

### Quick Diagnostic Commands

```powershell
# Check CARLA process
Get-Process -Name "CarlaUE4*" | Format-Table Id, CPU, WorkingSet64

# Check port usage
netstat -ano | Select-String ":2000"

# Check GPU VRAM (requires nvidia-smi)
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv

# Validate calib JSON syntax
python -c "import json; json.load(open('$calibFile'))"
```

### Smoke Test Checklist

| Step | Command | Expected |
|------|---------|----------|
| 0 | Find calib | Path printed |
| 1 | `UP_SELFTEST=1` | "All tests passed" |
| 2 | probe_carla | "RPC: OK" |
| 3 | record_route 10s | meta.json created |
| 4 | Check manifest | success: true |
