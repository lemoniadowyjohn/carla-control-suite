$ErrorActionPreference = "Stop"

param(
  [Parameter(Mandatory=$true)]
  [string]$Xodr

  [Parameter(Mandatory=$true)]
  [string]$RunName

  [string]$ManualTown = "Grid0828"
  [string]$Host = "127.0.0.1"
  [int]$Port = 2000
  [int]$SpawnIndex = 0
  [int]$Duration = 10
  [int]$Fps = 20
  [switch]$LowMem
)

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Test-Path $Xodr)) {
  throw "XODR not found: $Xodr"
}

$SmokeOut = Join-Path $RepoRoot ("artifacts\_smoke_load\" + $RunName)
$PairOut  = Join-Path $RepoRoot ("artifacts\_perception_pair\" + $RunName)

Write-Host "[1/2] smoke_load_xodr (fix-before-load + artifacts)" -ForegroundColor Cyan
python -m ultimate_pipeline.tools.smoke_load_xodr `
  --xodr "$Xodr" `
  --out "$SmokeOut" `
  --host "$Host" `
  --port $Port

Write-Host "[2/2] run_perception_pair (manual vs generated)" -ForegroundColor Cyan

$Args = @(
  "-m", "ultimate_pipeline.tools.run_perception_pair"
  "--manual-town", $ManualTown
  "--xodr-in", $Xodr
  "--out-root", $PairOut
  "--host", $Host
  "--port", "$Port"
  "--spawn-index", "$SpawnIndex"
  "--duration", "$Duration"
  "--fps", "$Fps"
)

if ($LowMem) {
  $Args += "--low-mem"
}

python @Args

Write-Host "Done." -ForegroundColor Green
Write-Host "Smoke artifacts: $SmokeOut" -ForegroundColor DarkGray
Write-Host "Perception artifacts: $PairOut" -ForegroundColor DarkGray
