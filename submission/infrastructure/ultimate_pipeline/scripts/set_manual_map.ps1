param(
  [ValidateSet("Grid0821","Grid0828")]
  [string]$Grid="Grid0821"
)

if ($Grid -eq "Grid0821") {
  $env:UP_MANUAL_XODR="E:\CARLA\CARLA_0.9.16\Import\Maps\Grid0821\Maps\Grid0821\OpenDrive\Grid0821.xodr"
} else {
  $env:UP_MANUAL_XODR="E:\CARLA\CARLA_0.9.16\Import\Maps\Grid0828\Maps\Grid0828\OpenDrive\Grid0828.xodr"
}

Write-Host "UP_MANUAL_XODR set to $env:UP_MANUAL_XODR"
