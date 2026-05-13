# run_calibration.ps1
$ErrorActionPreference = "Stop"

$root = "C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main"
Set-Location $root

Write-Host ""
Write-Host "[INFO] Make sure CARLA is running before continuing." -ForegroundColor Yellow
Write-Host ""

# Prefer venv python if it exists; otherwise fallback to python on PATH
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (Test-Path $venvPy) {
    $py = $venvPy
    Write-Host "[OK] Using venv python: $py" -ForegroundColor Green
} else {
    $py = "python"
    Write-Host "[WARN] .venv not found. Using system python from PATH." -ForegroundColor Yellow
}

# Optional: make Python I/O UTF-8 (extra safety)
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

& $py ".\ultimate_pipeline\tools\calibrate_sensors_in_carla.py" `
  --calib "C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\ultimate_pipeline\sensors\calib_data.json" `
  --output ".\calib_test_out" `
  --ticks 50

Write-Host ""
Write-Host "[OK] Calibration script finished successfully." -ForegroundColor Green
