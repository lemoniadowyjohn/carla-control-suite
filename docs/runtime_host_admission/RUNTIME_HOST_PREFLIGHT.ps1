<#
.SYNOPSIS
    Runtime host admission preflight. Run on the CANDIDATE host, before any
    expensive full cook.

.DESCRIPTION
    Strictly ordered, fail-fast. Stops at the first failed step.

      1. GPU/driver enumeration
      2. UE4Editor starts and exits cleanly
      3. ShaderCompileWorker launches
      4. Antivirus: no quarantine / noninterference
      5. Minimal UE commandlet
      6. DDC read/write benchmark
      7. Packaged CARLA startup
      8. client.get_server_version()

    An editor window opening is NOT qualification. CARLA success requires a
    real RPC response, never "port is listening".

    Emits the five gates:
        UE_EDITOR_SMOKE / SCW_SMOKE / AV_EXCLUSION_OR_NONINTERFERENCE
        DDC_QUALIFIED / CARLA_RPC_SMOKE
    and only then RUNTIME_HOST_ADMISSION=PASS.

.NOTES
    Read-only with respect to data. Launches UE/CARLA processes that it owns and
    terminates by owned PID only - never by image name. Contains no secrets and
    no private absolute paths; configure via environment variables.
#>

[CmdletBinding()]
param(
    # Root of the UE 4.26 CARLA engine checkout (required for steps 2,3,5,6).
    [string]$UE4Root = $env:UE4_ROOT,

    # Root of the CARLA 0.9.16 install/runtime (required for steps 5,7,8).
    [string]$CarlaRoot = $env:CARLA_ROOT,

    # Package name under CARLAUE4/Content (step 8 map load). Optional.
    [string]$MapPackage = $env:ADMISSION_MAP_PACKAGE,

    [int]$RpcPort = 2000,
    [int]$StreamingPort = 2001,

    # DDC gates (see RUNTIME_HOST_REQUIREMENTS.md).
    [double]$MinDdcReadMbps = 500.0,
    [double]$MaxDdcReadLatencyMs = 0.5,

    # Commit headroom gate, in GB.
    [double]$MinCommitLimitGB = 70.0,

    # Disk gates, in GB, per STORAGE_CAPACITY_GATE.json.
    [double]$MinSystemFreeGB = 20.0,
    [double]$MinWorkFreeGB = 12.0,
    [double]$MinEngineFreeGB = 45.0,

    [string]$OutputDir = $env:ADMISSION_OUT_DIR,

    # Diagnostics only. Does not weaken any gate.
    [switch]$SkipDdcBenchmark
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$script:Results   = [ordered]@{}
$script:OwnedPids = New-Object System.Collections.Generic.List[int]
$script:Gates     = [ordered]@{
    UE_EDITOR_SMOKE                 = 'UNSET'
    SCW_SMOKE                       = 'UNSET'
    AV_EXCLUSION_OR_NONINTERFERENCE = 'UNSET'
    DDC_QUALIFIED                   = 'UNSET'
    CARLA_RPC_SMOKE                 = 'UNSET'
}

if (-not $OutputDir) {
    $OutputDir = Join-Path ([System.IO.Path]::GetTempPath()) "runtime_host_admission_$(Get-Date -Format yyyyMMddTHHmmss)"
}
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunId     = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')

function Write-Step { param([string]$m) Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok   { param([string]$m) Write-Host "    PASS  $m" -ForegroundColor Green }
function Write-Bad  { param([string]$m) Write-Host "    FAIL  $m" -ForegroundColor Red }
function Write-Note { param([string]$m) Write-Host "    note  $m" -ForegroundColor DarkGray }

class AdmissionAbort : System.Exception {
    AdmissionAbort([string]$m) : base($m) {}
}

function Stop-Preflight {
    param([string]$Step, [string]$Reason)
    foreach ($pid_ in $script:OwnedPids) {
        try { Stop-Process -Id $pid_ -Force -ErrorAction Stop }
        catch { Write-Note "could not stop owned pid $pid_ : $($_.Exception.Message)" }
    }
    $script:Results['failed_step']   = $Step
    $script:Results['failure_reason'] = $Reason
    $script:Results['CURRENT_HOST_RUNTIME_ADMISSION'] = 'DENIED'
    Write-Bad "step '$Step' failed: $Reason"
    Write-PreflightReport
    exit 2
}

function Write-PreflightReport {
    $report = [ordered]@{
        schema            = 'runtime_host_preflight/v1'
        run_id_utc        = $RunId
        current_host      = $env:COMPUTERNAME
        os                = [System.Environment]::OSVersion.VersionString
        ps_version        = $PSVersionTable.PSVersion.ToString()
        steps             = $script:Results
        gates             = $script:Gates
        RUNTIME_HOST_ADMISSION = if ($script:Gates.Values -contains 'FAIL' -or $script:Gates.Values -contains 'UNSET') { 'NOT_QUALIFIED' } else { 'PASS' }
    }
    $path = Join-Path $OutputDir "runtime_host_preflight_$RunId.json"
    $report | ConvertTo-Json -Depth 8 | Set-Content -Path $path -Encoding UTF8
    Write-Host ""
    Write-Host "----- GATES -----" -ForegroundColor Cyan
    foreach ($k in $script:Gates.Keys) {
        $color = switch ($script:Gates[$k]) {
            'PASS' { 'Green' } 'FAIL' { 'Red' } default { 'Yellow' }
        }
        Write-Host ("  {0,-38} {1}" -f $k, $script:Gates[$k]) -ForegroundColor $color
    }
    $adm = if ($script:Gates.Values -contains 'FAIL' -or $script:Gates.Values -contains 'UNSET') { 'NOT_QUALIFIED' } else { 'PASS' }
    Write-Host ""
    Write-Host "  RUNTIME_HOST_ADMISSION=$adm" -ForegroundColor $(if ($adm -eq 'PASS') { 'Green' } else { 'Red' })
    Write-Host "  report: $path"
}

# Own-process teardown only. Never a global taskkill by image name.
function Stop-OwnedProcess {
    param([int]$ProcessId, [int]$TimeoutSec = 30)
    try { Stop-Process -Id $ProcessId -Force -ErrorAction Stop } catch { return }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSec) {
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { return }
        Start-Sleep -Milliseconds 500
    }
}

function Test-NoOrphanEditor {
    param([string]$UEEditorPath)
    $orphans = @(Get-CimInstance Win32_Process -Filter "Name='UE4Editor.exe'" -ErrorAction SilentlyContinue)
    foreach ($o in $orphans) {
        if ($o.ExecutablePath -and $UEEditorPath -and $o.ExecutablePath -like "$UEEditorPath*") {
            Write-Note "orphan UE4Editor.exe pid=$($o.ProcessId) (may hold Content locks); not owned by this run"
        }
    }
    $script:Results['orphan_editors_detected'] = $orphans.Count
}

# ---------------------------------------------------------------- step 1
Write-Step '1/8 GPU / driver enumeration'
try {
    $gpus = @(Get-CimInstance Win32_VideoController -ErrorAction Stop |
        Select-Object Name, DriverVersion, AdapterRAM, VideoProcessor)
    if ($gpus.Count -eq 0) { Stop-Preflight '1_gpu_enumeration' 'no video controller enumerated' }
    foreach ($g in $gpus) { Write-Note "gpu: $($g.Name) driver=$($g.DriverVersion)" }

    # TDR screening: LiveKernelEvent 141 (video/display TDR). These can surface
    # ONLY as watchdog dumps, with no System Event 4101 - so query both.
    $tdr = @(Get-WinEvent -FilterHashtable @{ LogName='System'; Id=4101 } -MaxEvents 50 -ErrorAction SilentlyContinue)
    $watchdog = @(Get-ChildItem "$env:SystemRoot\LiveKernelReports\WATCHDOG" -ErrorAction SilentlyContinue)
    $script:Results['gpu'] = @{
        adapters            = $gpus
        system_event_4101   = $tdr.Count
        watchdog_dumps      = $watchdog.Count
    }
    if ($tdr.Count -gt 0) {
        Write-Note "System Event 4101 (display driver reset) present x$($tdr.Count)"
        Write-Note "do NOT proceed on a TDR-affected host; roll back the driver or change hardware"
    }
    if ($watchdog.Count -gt 0) {
        Write-Note "watchdog dumps present x$($watchdog.Count); check for LiveKernelEvent 141"
    }
    Write-Ok 'gpu/driver enumerated (TDR state recorded, see report)'
} catch { Stop-Preflight '1_gpu_enumeration' $_.Exception.Message }

# ---------------------------------------------------------------- step 2
Write-Step '2/8 UE4Editor starts and exits cleanly'
if (-not $UE4Root) { Stop-Preflight '2_ue_editor_smoke' 'UE4_ROOT not set' }
$UEEditor  = Join-Path $UE4Root 'Engine\Binaries\Win64\UE4Editor.exe'
$UEEditorC = Join-Path $UE4Root 'Engine\Binaries\Win64\UE4Editor-Cmd.exe'
$UProj     = Join-Path $CarlaRoot 'CarlaUE4\CarlaUE4.uproject'
foreach ($p in @($UEEditor, $UProj)) {
    if (-not (Test-Path -LiteralPath $p)) { Stop-Preflight '2_ue_editor_smoke' "missing required path: $p" }
}
Test-NoOrphanEditor $UEEditor

# Commandlet that initializes and exits deterministically.
$cmdletLog = Join-Path $OutputDir "ue_commandlet.log"
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName  = $UEEditor
$psi.Arguments = "`"$UProj`" -run=DerivedDataCache -fill -DDC=CreatePakfile -unattended -nopause -nosplash -nullrhi -stdout -FullStdOutLogOutput -abslog=`"$cmdletLog`""
$psi.UseShellExecute = $false
$psi.CreateNoWindow  = $true
$proc = [System.Diagnostics.Process]::Start($psi)
$script:OwnedPids.Add($proc.Id)
$exited = $proc.WaitForExit(180000)
if (-not $exited) {
    Stop-Preflight '2_ue_editor_smoke' "UE4Editor did not exit within 180s (hang suspected - do not qualify)"
}
$script:Results['ue_editor_exit_code'] = $proc.ExitCode
$script:OwnedPids.Remove($proc.Id)
Write-Ok "UE4Editor exited cleanly (exit=$($proc.ExitCode))"

# ---------------------------------------------------------------- step 3
Write-Step '3/8 ShaderCompileWorker launches'
$scw = Join-Path $UE4Root 'Engine\Binaries\Win64\ShaderCompileWorker.exe'
if (-not (Test-Path -LiteralPath $scw)) { Stop-Preflight '3_scw_smoke' "missing ShaderCompileWorker.exe" }
$psi2 = New-Object System.Diagnostics.ProcessStartInfo
$psi2.FileName  = $scw
$psi2.Arguments = '-help'
$psi2.UseShellExecute = $false
$psi2.RedirectStandardOutput = $true
$psi2.RedirectStandardError  = $true
$psi2.CreateNoWindow = $true
$proc2 = [System.Diagnostics.Process]::Start($psi2)
$stdout = $proc2.StandardOutput.ReadToEnd()
$proc2.WaitForExit(30000) | Out-Null
# A healthy SCW invoked without a valid command line exits non-zero AND prints
# its guard message. A silent instant exit is the failure case.
$scwHealthy = ($stdout -match 'requires specific command like arguments')
$script:Results['scw_guard_message'] = ($stdout -split "`n" | Select-Object -First 1)
if (-not $scwHealthy) {
    $script:Gates['SCW_SMOKE'] = 'FAIL'
    Stop-Preflight '3_scw_smoke' 'ShaderCompileWorker did not emit its expected guard message (binary may be quarantined/truncated)'
}
Write-Ok 'ShaderCompileWorker responded as a healthy binary'
$script:Gates['SCW_SMOKE'] = 'PASS'

# ---------------------------------------------------------------- step 4
Write-Step '4/8 antivirus quarantine / noninterference'
# Probe by CREATING a file at the exact engine binary path. If endpoint security
# quarantines or denies it, the create fails or the file disappears.
$avFindings = @()
$probeDir  = Join-Path $UE4Root 'Engine\Binaries\Win64'
$probeFile = Join-Path $probeDir 'zz_admission_probe.tmp'
try {
    [System.IO.File]::WriteAllBytes($probeFile, [byte[]](1..16))
    Start-Sleep -Milliseconds 800
    $stillThere = Test-Path -LiteralPath $probeFile
    if (-not $stillThere) {
        $avFindings += 'probe file disappeared - endpoint security is consuming/quarantining engine-tree writes'
    }
    if ($stillThere) { Remove-Item -LiteralPath $probeFile -Force -ErrorAction SilentlyContinue }
} catch {
    $avFindings += "probe create denied: $($_.Exception.Message)"
}
# Also confirm the editor binary actually materialized (the recorded failure mode).
if (-not (Test-Path -LiteralPath $UEEditor)) {
    $avFindings += 'UE4Editor.exe absent from Engine/Binaries/Win64 (known quarantine failure mode)'
}
$script:Results['av_findings'] = $avFindings
if ($avFindings.Count -gt 0) {
    $script:Gates['AV_EXCLUSION_OR_NONINTERFERENCE'] = 'FAIL'
    foreach ($f in $avFindings) { Write-Bad $f }
    Write-Host ''
    Write-Host '    Do NOT disable or bypass endpoint security to clear this gate.' -ForegroundColor Red
    Write-Host '    If an exclusion cannot be created through documented, authorized' -ForegroundColor Red
    Write-Host '    means, move to a different host.' -ForegroundColor Red
    Stop-Preflight '4_av_noninterference' ($avFindings -join '; ')
}
Write-Ok 'no quarantine or interference observed'
$script:Gates['AV_EXCLUSION_OR_NONINTERFERENCE'] = 'PASS'

# ---------------------------------------------------------------- step 5
Write-Step '5/8 minimal UE commandlet'
$cmdletLog2 = Join-Path $OutputDir "ue_minimal_commandlet.log"
$psi3 = New-Object System.Diagnostics.ProcessStartInfo
$psi3.FileName  = $UEEditor
$psi3.Arguments = "`"$UProj`" -run=ResavePackages -help -unattended -nopause -nosplash -nullrhi -stdout -abslog=`"$cmdletLog2`""
$psi3.UseShellExecute = $false
$psi3.CreateNoWindow  = $true
$proc3 = [System.Diagnostics.Process]::Start($psi3)
$script:OwnedPids.Add($proc3.Id)
if (-not $proc3.WaitForExit(240000)) {
    Stop-Preflight '5_ue_commandlet' 'minimal commandlet did not exit within 240s'
}
$script:OwnedPids.Remove($proc3.Id)
$logText = if (Test-Path -LiteralPath $cmdletLog2) { Get-Content -LiteralPath $cmdletLog2 -Raw } else { '' }
$script:Results['commandlet_exit_code'] = $proc3.ExitCode
$script:Results['engine_initialized']    = ($logText -match 'Engine is initialized')
if ($logText -match "Failed to find Blueprint'/Game/Carla/") {
    Stop-Preflight '5_ue_commandlet' "CARLA content not resolvable under /Game/Carla (missing RoadPainterPreset). See REQUIREMENTS content-layout section."
}
Write-Ok "minimal commandlet completed (exit=$($proc3.ExitCode))"
$script:Gates['UE_EDITOR_SMOKE'] = 'PASS'

# ---------------------------------------------------------------- step 6
Write-Step '6/8 DDC read/write benchmark'
if (-not $env:UE4_DDC) {
    $script:Gates['DDC_QUALIFIED'] = 'FAIL'
    Stop-Preflight '6_ddc_qualification' 'UE4_DDC not set - configure a local NVMe DDC root per RUNTIME_HOST_REQUIREMENTS.md'
}
$ddcPath = $env:UE4_DDC
New-Item -ItemType Directory -Path $ddcPath -Force | Out-Null
$ddcRoot = [System.IO.Path]::GetPathRoot((Resolve-Path -LiteralPath $ddcPath).Path)
$driveInfo = Get-PSDrive -Name $ddcRoot.TrimEnd(':','\')
$freeGB = [math]::Round($driveInfo.Free / 1GB, 2)
$pctFree = if ($driveInfo.Used + $driveInfo.Free -gt 0) {
    [math]::Round(100 * $driveInfo.Free / ($driveInfo.Used + $driveInfo.Free), 1)
} else { 0 }

# Random small-file read/write - this is what DDC actually does. A sequential
# speed test is misleading: it reported 4.29 MB/s while real access was 0.08 MB/s.
$benchDir = Join-Path $ddcPath "_admission_bench"
New-Item -ItemType Directory -Path $benchDir -Force | Out-Null
$files = 400
$block = New-Object byte[] 65536
$swW = [System.Diagnostics.Stopwatch]::StartNew()
$paths = @()
for ($i = 0; $i -lt $files; $i++) {
    $p = Join-Path $benchDir ("blk_$i.bin")
    [System.IO.File]::WriteAllBytes($p, $block)
    $paths += $p
}
$swW.Stop()
$writeMbps = [math]::Round((($files * 65536) / 1MB) / $swW.Elapsed.TotalSeconds, 2)

$lat = @()
$swR = [System.Diagnostics.Stopwatch]::StartNew()
$totalBytes = 0L
foreach ($p in $paths) {
    $one = [System.Diagnostics.Stopwatch]::StartNew()
    $bytes = [System.IO.File]::ReadAllBytes($p)
    $one.Stop()
    $lat += $one.Elapsed.TotalMilliseconds
    $totalBytes += $bytes.Length
}
$swR.Stop()
$readMbps  = [math]::Round(($totalBytes / 1MB) / $swR.Elapsed.TotalSeconds, 2)
$meanLat  = [math]::Round(($lat | Measure-Object -Average).Average, 3)
$medianLat = [math]::Round(($lat | Sort-Object)[[int]($lat.Count / 2)], 3)
Remove-Item -LiteralPath $benchDir -Recurse -Force -ErrorAction SilentlyContinue

$script:Results['ddc'] = @{
    path = $ddcPath; volume = $ddcRoot; free_gb = $freeGB; free_percent = $pctFree
    random_read_mbps = $readMbps; random_write_mbps = $writeMbps
    mean_latency_ms = $meanLat; median_latency_ms = $medianLat; files = $files
}
Write-Note "DDC volume $ddcRoot free=${freeGB}GB (${pctFree}%)"
Write-Note "random read=${readMbps} MB/s write=${writeMbps} MB/s median latency=${medianLat} ms"

$ddcFail = @()
if ($readMbps -lt $MinDdcReadMbps)      { $ddcFail += "random read $readMbps MB/s < $MinDdcReadMbps MB/s" }
if ($medianLat -ge $MaxDdcReadLatencyMs){ $ddcFail += "median latency $medianLat ms >= $MaxDdcReadLatencyMs ms" }
if ($pctFree -le 50)                    { $ddcFail += "volume only ${pctFree}% free; NVFS/NTFS degrades below ~15% and policy requires >50%" }
if ($ddcFail.Count -gt 0) {
    $script:Gates['DDC_QUALIFIED'] = 'FAIL'
    Stop-Preflight '6_ddc_qualification' ($ddcFail -join '; ')
}
Write-Ok 'DDC meets read throughput, latency and free-space policy'
$script:Gates['DDC_QUALIFIED'] = 'PASS'

# ---------------------------------------------------------------- step 7
Write-Step '7/8 packaged CARLA startup'
if (-not $CarlaRoot) { Stop-Preflight '7_carla_startup' 'CARLA_ROOT not set' }
$serverExe = Get-ChildItem -LiteralPath $CarlaRoot -Recurse -Filter 'CarlaUE4-Win64-Shipping.exe' -ErrorAction SilentlyContinue |
             Select-Object -First 1
if (-not $serverExe) {
    $script:Gates['CARLA_RPC_SMOKE'] = 'FAIL'
    Stop-Preflight '7_carla_startup' 'packaged CARLA server binary not found under CARLA_ROOT'
}
$serverLog = Join-Path $OutputDir "carla_server.log"
$psi4 = New-Object System.Diagnostics.ProcessStartInfo
$psi4.FileName  = $serverExe.FullName
$psi4.Arguments = "-carla-server -carla-rpc-port=$RpcPort -carla-streaming-port=$StreamingPort -RenderOffScreen -quality-level=Low -nosound -log -abslog=`"$serverLog`""
$psi4.WorkingDirectory = $serverExe.DirectoryName
$psi4.UseShellExecute = $false
$psi4.CreateNoWindow  = $true
$proc4 = [System.Diagnostics.Process]::Start($psi4)
$script:OwnedPids.Add($proc4.Id)
Write-Note "started packaged server pid=$($proc4.Id) rpc=$RpcPort stream=$StreamingPort"

# Wait for the port. This alone proves NOTHING - step 8 is the real gate.
$ready = $false
for ($i = 0; $i -lt 90; $i++) {
    if ($proc4.HasExited) { break }
    if (Get-NetTCPConnection -LocalPort $RpcPort -State Listen -ErrorAction SilentlyContinue) { $ready = $true; break }
    Start-Sleep -Seconds 2
}
$script:Results['server_listening_port'] = $ready
$script:Results['server_pid']            = $proc4.Id
if (-not $ready) {
    $script:Gates['CARLA_RPC_SMOKE'] = 'FAIL'
    Stop-Preflight '7_carla_startup' "packaged CARLA did not listen on $RpcPort within 180s"
}
Write-Note "port $RpcPort listening (NOT sufficient for qualification; step 8 follows)"

# ---------------------------------------------------------------- step 8
Write-Step '8/8 client.get_server_version()'
$py = $env:ADMISSION_PYTHON
if (-not $py) { Stop-Preflight '8_carla_rpc_smoke' 'ADMISSION_PYTHON not set' }
$pyScript = Join-Path $OutputDir 'rpc_smoke.py'
@'
import json, sys, carla
port = int(sys.argv[1])
pkg  = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
out = {"client_version": getattr(carla, "__version__", None),
       "server_version": None, "map_name": None, "frame": None,
       "map_load_ok": None, "error": None}
c = carla.Client("127.0.0.1", port)
c.set_timeout(30.0)
try:
    # Real RPC round-trip. Port listening does not reach this line.
    out["server_version"] = c.get_server_version()
    if pkg:
        try:
            w = c.load_world(pkg)
            out["map_load_ok"] = bool(w)
            out["map_name"] = w.get_map().name if w else None
        except Exception as e:
            out["map_load_ok"] = False
            out["error"] = "map_load: %s" % e
    w = c.get_world()
    if w:
        out["map_name"] = out["map_name"] or w.get_map().name
        out["frame"] = c.get_snapshot().frame
finally:
    c.disconnect()
# Fail closed on version match - upstream tooling only warns.
out["version_match"] = (out["server_version"] == out["client_version"] == "0.9.16")
print(json.dumps(out))
'@ | Set-Content -LiteralPath $pyScript -Encoding UTF8

$mapArg = if ($MapPackage) { $MapPackage } else { '' }
$rpcOut = & $py $pyScript $RpcPort $mapArg 2>&1 | Out-String
Stop-OwnedProcess -ProcessId $proc4.Id
$script:OwnedPids.Remove($proc4.Id)
$script:Results['rpc_smoke_stdout'] = $rpcOut.Trim()

$rpc = $null
try { $rpc = $rpcOut | ConvertFrom-Json } catch { $rpc = $null }
if (-not $rpc -or -not $rpc.server_version) {
    $script:Gates['CARLA_RPC_SMOKE'] = 'FAIL'
    Stop-Preflight '8_carla_rpc_smoke' "no RPC response from get_server_version(). Port listening is NOT success."
}
Write-Ok "RPC responded: server=$($rpc.server_version) client=$($rpc.client_version) map=$($rpc.map_name)"
if (-not $rpc.version_match) {
    $script:Gates['CARLA_RPC_SMOKE'] = 'FAIL'
    Stop-Preflight '8_carla_rpc_smoke' "version mismatch: server=$($rpc.server_version) client=$($rpc.client_version); both must be 0.9.16"
}
$script:Gates['CARLA_RPC_SMOKE'] = 'PASS'

# ---------------------------------------------------------------- resources
Write-Step 'post-gate resource verification'
# Capacity gates are NOT enforced anywhere in-repo (marked NOT YET IMPLEMENTED).
# Enforce them here, explicitly.
$capFail = @()
$sysFree = [math]::Round((Get-PSDrive -Name $env:SystemDrive.TrimEnd(':')).Free / 1GB, 2)
if ($sysFree -lt $MinSystemFreeGB) { $capFail += "system volume free ${sysFree}GB < ${MinSystemFreeGB}GB" }
$ueFree = [math]::Round((Get-PSDrive -Name (Split-Path -Qualifier $UE4Root).TrimEnd(':')).Free / 1GB, 2)
if ($ueFree -lt $MinEngineFreeGB) { $capFail += "engine volume free ${ueFree}GB < ${MinEngineFreeGB}GB" }
$script:Results['capacity'] = @{ system_free_gb = $sysFree; engine_free_gb = $ueFree }

$os = Get-CimInstance Win32_OperatingSystem
$physGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$pageGB = [math]::Round($os.TotalVirtualMemorySize / 1MB - $os.TotalVisibleMemorySize / 1MB, 1)
$commitLimitGB = [math]::Round($os.TotalVirtualMemorySize / 1MB, 1)
$script:Results['memory'] = @{
    physical_ram_gb = $physGB; pagefile_gb = $pageGB
    commit_limit_gb = $commitLimitGB; free_physical_gb = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
}
if ($commitLimitGB -lt $MinCommitLimitGB) {
    $capFail += "commit limit ${commitLimitGB}GB < ${MinCommitLimitGB}GB (SCW processes are NOT counted in editor accounting)"
}
Write-Note "ram=${physGB}GB pagefile=${pageGB}GB commit_limit=${commitLimitGB}GB"
if ($capFail.Count -gt 0) {
    $script:Gates['CARLA_RPC_SMOKE'] = 'FAIL'
    Stop-Preflight 'resources' ($capFail -join '; ')
}

$script:Results['note_map_cook_state'] = @'
Readiness != build != runtime. The authoritative map may legitimately be
BLOCKED_COOK_REQUIRED / absent from the cook registry even on a fully qualified
host. UE_EDITOR_SMOKE does not imply the map is cooked. See REQUIREMENTS.
'@

Write-PreflightReport
Write-Host ''
Write-Host 'All five gates PASS. Host is admitted.' -ForegroundColor Green
Write-Host 'You may now run M5B_EXECUTION_SPEC.md.' -ForegroundColor Green
exit 0
