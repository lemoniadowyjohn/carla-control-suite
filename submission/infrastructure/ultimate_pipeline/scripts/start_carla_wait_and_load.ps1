<#
.SYNOPSIS
    Start CARLA, wait for readiness, and run smoke_load_xodr.

.DESCRIPTION
    Robust PowerShell helper for Windows CARLA 0.9.16 thesis experiments.
    - Finds CarlaUE4.exe via Settings or common candidates
    - Starts CARLA with correct RPC/streaming ports
    - Waits for RPC port (streaming is best-effort)
    - Calls smoke_load_xodr to load XODR and capture artifacts

.PARAMETER Xodr
    Required. Path to the .xodr file to load.

.PARAMETER Out
    Required. Output directory for artifacts.

.PARAMETER CarlaRoot
    Optional. CARLA installation root (default: E:\CARLA\CARLA_0.9.16)

.PARAMETER RpcPort
    Optional. CARLA RPC port (default: 2000 or from Settings)

.PARAMETER StreamPort
    Optional. CARLA streaming port (default: RpcPort+1)

.PARAMETER CarlaHost
    Optional. CARLA hostname (default: 127.0.0.1)

.PARAMETER Timeout
    Optional. Max seconds to wait for CARLA readiness (default: 120)

.EXAMPLE
    .\start_carla_wait_and_load.ps1 -Xodr "C:\maps\test.xodr" -Out "C:\out"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$Xodr,

    [Parameter(Mandatory=$true)]
    [string]$Out,

    [string]$CarlaRoot = "E:\CARLA\CARLA_0.9.16",

    [int]$RpcPort = 2000,

    [int]$StreamPort = 0,

    [string]$CarlaHost = "127.0.0.1",

    [int]$Timeout = 120
)

$ErrorActionPreference = "Stop"

# StreamPort defaults to RpcPort + 1
if ($StreamPort -eq 0) {
    $StreamPort = $RpcPort + 1
}

Write-Host "[start_carla_wait_and_load] Starting..."
Write-Host "  Xodr:       $Xodr"
Write-Host "  Out:        $Out"
Write-Host "  CarlaRoot:  $CarlaRoot"
Write-Host "  RpcPort:    $RpcPort"
Write-Host "  StreamPort: $StreamPort"

# -----------------------------------------------------------------------------
# Find CarlaUE4.exe
# -----------------------------------------------------------------------------
function Find-CarlaExe {
    param([string]$Root)

    # Priority 1: Environment variable
    $envExe = $env:CARLA_SERVER_PATH
    if ($envExe -and (Test-Path $envExe)) {
        return $envExe
    }

    # Priority 2: Search candidates under CarlaRoot
    $candidates = @(
        (Join-Path $Root "CarlaUE4.exe"),
        (Join-Path $Root "WindowsNoEditor\CarlaUE4.exe"),
        (Join-Path $Root "WindowsNoEditor\CarlaUE4\Binaries\Win64\CarlaUE4.exe"),
        (Join-Path $Root "Unreal\CarlaUE4\Binaries\Win64\CarlaUE4.exe")
    )

    foreach ($c in $candidates) {
        if (Test-Path $c) {
            return $c
        }
    }

    # Not found - throw with searched list
    $searchedList = $candidates -join "`n  "
    throw "CarlaUE4.exe not found. Searched:`n  $searchedList"
}

$CarlaExe = Find-CarlaExe -Root $CarlaRoot
Write-Host "[OK] Found CARLA executable: $CarlaExe"

# -----------------------------------------------------------------------------
# Wait for TCP port (bounded)
# -----------------------------------------------------------------------------
function Wait-TcpPort {
    param(
        [string]$HostName,
        [int]$Port,
        [int]$TimeoutSec,
        [bool]$Required = $true
    )

    $startTime = Get-Date
    $endTime = $startTime.AddSeconds($TimeoutSec)

    while ((Get-Date) -lt $endTime) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect($HostName, $Port)
            $tcp.Close()
            return $true
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    if ($Required) {
        throw "Port $Port on $HostName not reachable after ${TimeoutSec}s"
    }
    return $false
}

# -----------------------------------------------------------------------------
# Start CARLA
# -----------------------------------------------------------------------------
$carlaArgs = @(
    "-carla-rpc-port=$RpcPort",
    "-carla-streaming-port=$StreamPort",
    "-RenderOffScreen",
    "-nosound",
    "-quality-level=Low"
)

Write-Host "[CARLA] Starting: $CarlaExe $($carlaArgs -join ' ')"

$carlaProcess = Start-Process -FilePath $CarlaExe -ArgumentList $carlaArgs -PassThru -WindowStyle Hidden

if (-not $carlaProcess) {
    throw "Failed to start CARLA process"
}

Write-Host "[CARLA] Started with PID: $($carlaProcess.Id)"

# -----------------------------------------------------------------------------
# Wait for RPC port (required)
# -----------------------------------------------------------------------------
Write-Host "[WAIT] Waiting for RPC port $RpcPort (max ${Timeout}s)..."
try {
    $rpcOk = Wait-TcpPort -HostName $CarlaHost -Port $RpcPort -TimeoutSec $Timeout -Required $true
    Write-Host "[OK] RPC port $RpcPort is reachable"
} catch {
    Write-Host "[ERROR] RPC port wait failed: $_"
    if (-not $carlaProcess.HasExited) {
        Stop-Process -Id $carlaProcess.Id -Force -ErrorAction SilentlyContinue
    }
    exit 1
}

# Wait for streaming port (best-effort)
Write-Host "[WAIT] Checking streaming port $StreamPort (best-effort, 10s)..."
$streamOk = Wait-TcpPort -HostName $CarlaHost -Port $StreamPort -TimeoutSec 10 -Required $false
if ($streamOk) {
    Write-Host "[OK] Streaming port $StreamPort is reachable"
} else {
    Write-Host "[WARN] Streaming port $StreamPort not reachable (screenshot may fail)"
}

# Extra settling time
Start-Sleep -Seconds 3

# -----------------------------------------------------------------------------
# Call smoke_load_xodr
# -----------------------------------------------------------------------------
Write-Host "[SMOKE] Running smoke_load_xodr..."

$pythonCmd = "python"
$smokeArgs = @(
    "-m", "ultimate_pipeline.tools.smoke_load_xodr",
    "--xodr", $Xodr,
    "--out", $Out,
    "--host", $CarlaHost,
    "--port", $RpcPort
)

Write-Host "[SMOKE] Command: $pythonCmd $($smokeArgs -join ' ')"

$smokeResult = & $pythonCmd @smokeArgs
$smokeExitCode = $LASTEXITCODE

Write-Host "[SMOKE] Exit code: $smokeExitCode"

# -----------------------------------------------------------------------------
# Cleanup: stop CARLA
# -----------------------------------------------------------------------------
Write-Host "[CLEANUP] Stopping CARLA..."
if (-not $carlaProcess.HasExited) {
    Stop-Process -Id $carlaProcess.Id -Force -ErrorAction SilentlyContinue
    Write-Host "[CLEANUP] CARLA stopped"
} else {
    Write-Host "[CLEANUP] CARLA already exited"
}

# Return smoke exit code
exit $smokeExitCode
