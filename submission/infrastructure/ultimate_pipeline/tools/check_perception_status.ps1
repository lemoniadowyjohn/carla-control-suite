param(
  [Parameter(Mandatory=$true)][string]$OutDir,
  [int]$RpcPort = 2000
)

function Get-OwnerProcessForPort([int]$Port) {
  $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $c) { return $null }
  return Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)"
}

$proc = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'run_perception_safe|run_perception_pair|record_route|perception_runner_local' }

$carla = Get-Process CarlaUE4,CarlaUE4-Win64-Shipping -ErrorAction SilentlyContinue
$portOwner = Get-OwnerProcessForPort -Port $RpcPort

$last = Get-ChildItem $OutDir -Recurse -File -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -match '\\(rgb|lidar|seg)\\' } |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1

[pscustomobject]@{
  PerceptionPID = if($proc){ ($proc.ProcessId -join ",") } else { $null }
  CarlaRunning  = [bool]$carla
  RpcPortOpen   = [bool]$portOwner
  RpcPortOwner  = if($portOwner){ "$($portOwner.Name) [$($portOwner.ProcessId)]" } else { $null }
  LatestSensorFile = if($last){ $last.FullName } else { $null }
  FileAgeSec    = if($last){ [int]((Get-Date) - $last.LastWriteTime).TotalSeconds } else { $null }
  WritingNow    = if($last){ $last.LastWriteTime -gt (Get-Date).AddSeconds(-10) } else { $false }
}
