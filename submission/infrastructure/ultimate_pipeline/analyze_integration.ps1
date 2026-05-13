# ================================
# Ultimate Pipeline Integration Audit
# ================================

$ROOT = "C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\ultimate_pipeline"
$OUT  = "$ROOT\_integration_audit"

New-Item -ItemType Directory -Force -Path $OUT | Out-Null

Write-Host "🔍 Ultimate Pipeline Integration Audit"
Write-Host "Root: $ROOT"
Write-Host "Output: $OUT"
Write-Host ""

# --------------------------------------------------
# 1️⃣ Full program inventory (ground truth)
# --------------------------------------------------
Write-Host "1️⃣ Generating full Python inventory..."

Get-ChildItem `
  $ROOT `
  -Recurse -Filter *.py |
  Select-Object FullName |
  Sort-Object |
  Out-File "$OUT\ultimate_pipeline_all_py.txt"

# --------------------------------------------------
# 2️⃣ Extract imports actually used
# --------------------------------------------------
Write-Host "2️⃣ Extracting actual imports..."

Select-String `
  -Path "$ROOT\**\*.py" `
  -Pattern "import ultimate_pipeline|from ultimate_pipeline" |
  Select-Object Path, Line |
  Out-File "$OUT\ultimate_pipeline_imports.txt"

# --------------------------------------------------
# 3️⃣ Normalize imported modules
# --------------------------------------------------
Write-Host "3️⃣ Normalizing imported modules..."

Select-String `
  -Path "$OUT\ultimate_pipeline_imports.txt" `
  -Pattern "ultimate_pipeline[\w\.]*" |
  ForEach-Object {
    ($_ -split "ultimate_pipeline")[1].TrimStart(".")
  } |
  Sort-Object -Unique |
  Out-File "$OUT\ultimate_pipeline_imported_modules.txt"

# --------------------------------------------------
# 4️⃣ Normalize all existing modules
# --------------------------------------------------
Write-Host "4️⃣ Normalizing all existing modules..."

Get-ChildItem `
  $ROOT `
  -Recurse -Filter *.py |
  ForEach-Object {
    $_.FullName `
      -replace '.*ultimate_pipeline\\', '' `
      -replace '\\', '.' `
      -replace '.py$', ''
  } |
  Sort-Object -Unique |
  Out-File "$OUT\ultimate_pipeline_existing_modules.txt"

# --------------------------------------------------
# 5️⃣ Compute NOT-INTEGRATED modules
# --------------------------------------------------
Write-Host "5️⃣ Computing NOT-INTEGRATED modules..."

Compare-Object `
  (Get-Content "$OUT\ultimate_pipeline_existing_modules.txt") `
  (Get-Content "$OUT\ultimate_pipeline_imported_modules.txt") `
  -PassThru |
  Where-Object {
    $_ -notmatch "^main_pipeline" -and
    $_ -notmatch "^run_pipeline"
  } |
  Sort-Object |
  Out-File "$OUT\ultimate_pipeline_NOT_integrated.txt"

# --------------------------------------------------
# 6️⃣ Subsystem classification
# --------------------------------------------------
Write-Host "6️⃣ Classifying by subsystem..."

Select-String `
  -Path "$OUT\ultimate_pipeline_NOT_integrated.txt" `
  -Pattern "domain_gap" |
  Out-File "$OUT\not_integrated_domain_gap.txt"

Select-String `
  -Path "$OUT\ultimate_pipeline_NOT_integrated.txt" `
  -Pattern "carla" |
  Out-File "$OUT\not_integrated_carla.txt"

Select-String `
  -Path "$OUT\ultimate_pipeline_NOT_integrated.txt" `
  -Pattern "tile|tiling" |
  Out-File "$OUT\not_integrated_tiling.txt"

Select-String `
  -Path "$OUT\ultimate_pipeline_NOT_integrated.txt" `
  -Pattern "diagnostics|debug|visualization|thesis" |
  Out-File "$OUT\not_integrated_tools_and_viz.txt"

# --------------------------------------------------
# 7️⃣ Human-readable dashboard
# --------------------------------------------------
Write-Host ""
Write-Host "=============================="
Write-Host "📊 INTEGRATION AUDIT SUMMARY"
Write-Host "=============================="
Write-Host ""

Write-Host "📁 Total Python files:"
(Get-Content "$OUT\ultimate_pipeline_all_py.txt").Count

Write-Host ""
Write-Host "🔗 Imported modules:"
(Get-Content "$OUT\ultimate_pipeline_imported_modules.txt").Count

Write-Host ""
Write-Host "❌ NOT integrated modules:"
(Get-Content "$OUT\ultimate_pipeline_NOT_integrated.txt").Count

Write-Host ""
Write-Host "📦 Domain gap NOT integrated:"
(Get-Content "$OUT\not_integrated_domain_gap.txt").Count

Write-Host "🚗 CARLA NOT integrated:"
(Get-Content "$OUT\not_integrated_carla.txt").Count

Write-Host "🧩 Tiling NOT integrated:"
(Get-Content "$OUT\not_integrated_tiling.txt").Count

Write-Host ""
Write-Host "✔ Audit complete."
Write-Host "Results saved to: $OUT"
