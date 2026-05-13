# thesis_env_preset.ps1 - Thesis experiment preset for Windows
# Source this file BEFORE running experiments:
#   . .\ultimate_pipeline\tools\thesis_env_preset.ps1 -Profile fast_offline
#   . .\ultimate_pipeline\tools\thesis_env_preset.ps1 -Profile full_evidence

param(
    [ValidateSet("fast_offline","full_evidence")]
    [string]$Profile = "fast_offline"
)
#
# MACHINE CONSTANTS (edit once per machine):
# =========================================

# CARLA server location
$env:CARLA_HOST = "127.0.0.1"
$env:CARLA_PORT = "2000"

# Paths (edit these for your machine)
$env:CARLA_EXE = "E:\CARLA\CARLA_0.9.16\CarlaUE4.exe"
$env:BLENDER_EXE = "E:\Program Files\Blender Foundation\Blender 4.3\blender.exe"
$env:OSM2WORLD_HOME = "$PSScriptRoot\..\..\OSM2World-latest-bin"

# Sensor calibration (Dominik rig)
$env:SENSOR_CALIB_JSON = "$PSScriptRoot\..\sensors\calib_data.json"

# ScenarioRunner root (external)
$env:UP_SCENARIORUNNER_ROOT = "$PSScriptRoot\..\..\external\scenario_runner-master"

# DEM directory
$env:UP_DEM_DIR = "$PSScriptRoot\..\cities\ingolstadt\dem"

# THESIS BBOX (MUST REMAIN CONSTANT):
# ===================================
$env:UP_LAT_MIN = "48.74935649548228"
$env:UP_LON_MIN = "11.422268084715878"
$env:UP_LAT_MAX = "48.77444431571603"
$env:UP_LON_MAX = "11.47882091528412"

# STABLE DEFAULTS (recommended for thesis):
# =========================================

# Enable CARLA isolation on Windows (subprocess crash containment)
$env:UP_CARLA_ISOLATION = "1"

# Perception settings
$env:UP_ENABLE_THESIS_PERCEPTION_CAPTURE = "0"   # Enable per-run with: $env:UP_ENABLE_THESIS_PERCEPTION_CAPTURE = "1"
$env:UP_MIN_FRAMES = "10"                         # Minimum frames for perception PASS (raise for strict)
$env:UP_THESIS_CAPTURE_SEG = "1"                  # Include semantic segmentation
$env:UP_THESIS_CAPTURE_SEG_CONVERTER = "cityscapes"

# ScenarioRunner (disabled by default)
$env:UP_ENABLE_SCENARIORUNNER = "0"               # Enable per-run with: $env:UP_ENABLE_SCENARIORUNNER = "1"
$env:UP_SCENARIORUNNER_TIMEOUT_S = "900"

# OSM2World / Blender (disabled by default - optional visual QA)
$env:ENABLE_OSM2WORLD = "0"
$env:ENABLE_BLENDER_FBX = "0"

# Determinism
$env:PYTHONHASHSEED = "42"

# PROFILE OVERRIDES:
# ==================
if ($Profile -eq "fast_offline") {
    $env:UP_DISABLE_CARLA = "1"
    $env:UP_SKIP_STEP10_TILE_QA = "1"
    $env:UP_SKIP_TILE_QA = "1"
    $env:UP_ENABLE_OSM2WORLD = "0"
    $env:ENABLE_OSM2WORLD = "0"
    $env:ENABLE_BLENDER_FBX = "0"
    $env:UP_ENABLE_DOMAIN_GAP = "0"
    $env:UP_ENABLE_THESIS_PERCEPTION_CAPTURE = "0"
    $env:UP_ENABLE_SCENARIORUNNER = "0"
}
if ($Profile -eq "full_evidence") {
    $env:UP_DISABLE_CARLA = "0"
    $env:UP_ENABLE_DOMAIN_GAP = "1"
    $env:UP_ENABLE_THESIS_PERCEPTION_CAPTURE = "1"
    $env:UP_ENABLE_SCENARIORUNNER = "1"
}

# OPTIONAL PER-RUN TOGGLES (uncomment as needed):
# ===============================================

# Strict perception (fail if fewer than N frames):
# $env:UP_STRICT_PERCEPTION = "1"
# $env:UP_MIN_FRAMES = "200"

# Enable domain gap analysis:
# $env:ENABLE_DOMAIN_GAP = "1"
# $env:MANUAL_MAP_XODR = "path/to/Grid0828.xodr"

# Force offline mode (skip all CARLA stages):
# $env:UP_DISABLE_CARLA = "1"

# VALIDATION - print key settings:
# ================================
Write-Host "=== Thesis Environment Preset Loaded ===" -ForegroundColor Green
Write-Host "Profile: $Profile"
Write-Host "CARLA: $env:CARLA_HOST`:$env:CARLA_PORT"
Write-Host "Isolation: $env:UP_CARLA_ISOLATION"
Write-Host "BBox: lat[$env:UP_LAT_MIN, $env:UP_LAT_MAX] lon[$env:UP_LON_MIN, $env:UP_LON_MAX]"
Write-Host "Calib: $env:SENSOR_CALIB_JSON"
Write-Host ""
Write-Host "To verify CARLA reachability:"
Write-Host "  python -m ultimate_pipeline.tools.carla_preflight --out .\preflight_test"
Write-Host ""
