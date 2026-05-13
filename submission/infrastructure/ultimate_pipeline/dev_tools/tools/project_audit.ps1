$ROOT = "C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\ultimate_pipeline"

Write-Host "=== SETTINGS FLAGS ==="
Select-String "$ROOT\config\settings.py" -Pattern "ENABLE_|ALLOW_|USE_" |
ForEach-Object { $_.Line.Trim() } | Sort-Object

Write-Host "`n=== FLAG USAGE ==="
Select-String "$ROOT\**\*.py" -Pattern "SETTINGS\.(ENABLE_|ALLOW_|USE_)" |
ForEach-Object { $_.Line.Trim() } | Sort-Object -Unique

Write-Host "`n=== LEGACY FLAG CHECK ==="
Select-String "$ROOT\**\*.py" -Pattern "USE_SHAPELY"

Write-Host "`n=== CARLA DEPENDENCY LEAK ==="
Select-String "$ROOT\**\*.py" -Pattern "import carla|carla\." |
Select-Object Path | Sort-Object -Unique

Write-Host "`n=== SHAPELY USAGE ==="
Select-String "$ROOT\**\*.py" -Pattern "shapely" |
Select-Object Path | Sort-Object -Unique
