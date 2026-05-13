param(
  [ValidateSet("Grid0821","Grid0828")]
  [string]$Grid="Grid0821",
  [Parameter(Mandatory=$true)]
  [string]$AutoXodr,
  [string]$Calib="calib_data.json",
  [string]$OutRoot="recordings/pairs"
)

. "$PSScriptRoot\set_manual_map.ps1" -Grid $Grid

python -m ultimate_pipeline.tools.run_perception_pair `
  --manual-town $Grid `
  --xodr-in $AutoXodr `
  --calib $Calib `
  --out-root $OutRoot

Remove-Item Env:UP_MANUAL_XODR -ErrorAction SilentlyContinue
