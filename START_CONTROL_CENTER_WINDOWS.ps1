# Run this script from the extracted v3 source directory.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host 'Missing .venv. Run: py -3.12 -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e ''.[gui]''' -ForegroundColor Yellow
    exit 2
}
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
& $python -m ultimate_pipeline.gui.cli
exit $LASTEXITCODE
