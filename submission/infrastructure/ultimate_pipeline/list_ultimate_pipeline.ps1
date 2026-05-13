# ============================================================
# Ultimate Pipeline Audit Script (Windows PowerShell SAFE)
# ============================================================

$RootPath = "C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main\ultimate_pipeline"
$OutDir   = Join-Path $RootPath "ultimate_pipeline_audit"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# ------------------------------------------------------------
# 1) Directory-only tree
# ------------------------------------------------------------
Get-ChildItem -Path $RootPath -Recurse -Directory |
    Sort-Object FullName |
    Select-Object FullName |
    Out-File (Join-Path $OutDir "dir_tree.txt") -Encoding UTF8

# ------------------------------------------------------------
# 2) Python files only
# ------------------------------------------------------------
$PythonFiles = Get-ChildItem -Path $RootPath -Recurse -File -Filter "*.py"

$PythonFiles.FullName |
    Sort-Object |
    Out-File (Join-Path $OutDir "python_files.txt") -Encoding UTF8

# ------------------------------------------------------------
# 3) All files inventory
# ------------------------------------------------------------
$AllFiles = Get-ChildItem -Path $RootPath -Recurse -File |
    Select-Object FullName, Extension, Length, LastWriteTime

$AllFiles |
    Export-Csv (Join-Path $OutDir "all_files.csv") -NoTypeInformation -Encoding UTF8

$AllFiles |
    ConvertTo-Json -Depth 4 |
    Out-File (Join-Path $OutDir "all_files.json") -Encoding UTF8

# ------------------------------------------------------------
# 4) Largest files report (top 50)
# ------------------------------------------------------------
$AllFiles |
    Sort-Object Length -Descending |
    Select-Object -First 50 |
    Export-Csv (Join-Path $OutDir "largest_files.csv") -NoTypeInformation -Encoding UTF8

# ------------------------------------------------------------
# 5) File count per top-level submodule
# ------------------------------------------------------------
$ModuleCounts = Get-ChildItem -Path $RootPath -Directory |
    ForEach-Object {
        [PSCustomObject]@{
            Module    = $_.Name
            FileCount = (Get-ChildItem $_.FullName -Recurse -File).Count
        }
    }

$ModuleCounts |
    Export-Csv (Join-Path $OutDir "file_counts_per_module.csv") -NoTypeInformation -Encoding UTF8

# ------------------------------------------------------------
# 6) Hashes (MD5 + SHA256)
# ------------------------------------------------------------
$Hashes = foreach ($f in $AllFiles) {
    try {
        [PSCustomObject]@{
            Path   = $f.FullName
            MD5    = (Get-FileHash $f.FullName -Algorithm MD5).Hash
            SHA256 = (Get-FileHash $f.FullName -Algorithm SHA256).Hash
        }
    } catch {
        [PSCustomObject]@{
            Path   = $f.FullName
            MD5    = "ERROR"
            SHA256 = "ERROR"
        }
    }
}

$Hashes |
    Export-Csv (Join-Path $OutDir "file_hashes.csv") -NoTypeInformation -Encoding UTF8

# ------------------------------------------------------------
# 7) Python import dependency analysis (static regex)
# ------------------------------------------------------------
$ImportMap  = @{}
$ReverseMap = @{}

foreach ($py in $PythonFiles) {
    $imports = @()

    try {
        Get-Content $py.FullName | ForEach-Object {
            if ($_ -match '^\s*import\s+([a-zA-Z0-9_\.]+)') {
                $imports += $matches[1]
            }
            elseif ($_ -match '^\s*from\s+([a-zA-Z0-9_\.]+)\s+import') {
                $imports += $matches[1]
            }
        }
    } catch {}

    $imports = $imports | Sort-Object -Unique
    $ImportMap[$py.FullName] = $imports

    foreach ($imp in $imports) {
        if (-not $ReverseMap.ContainsKey($imp)) {
            $ReverseMap[$imp] = @()
        }
        $ReverseMap[$imp] += $py.FullName
    }
}

$ImportMap |
    ConvertTo-Json -Depth 6 |
    Out-File (Join-Path $OutDir "python_imports.json") -Encoding UTF8

$ReverseMap |
    ConvertTo-Json -Depth 6 |
    Out-File (Join-Path $OutDir "python_imports_reverse.json") -Encoding UTF8

# ------------------------------------------------------------
# 8) Auto-generate requirements from imports
# ------------------------------------------------------------

function Get-StdLibModules {
    @(
        "os","sys","re","json","math","time","datetime","itertools","functools",
        "collections","pathlib","typing","subprocess","threading","multiprocessing",
        "logging","traceback","inspect","enum","dataclasses","hashlib","random",
        "statistics","csv","xml","xml.etree","shutil","tempfile","argparse",
        "warnings","copy","glob","pickle","queue","socket","struct","platform",
        "uuid","weakref","contextlib","abc","asyncio"
    )
}

$StdLib     = Get-StdLibModules
$ThirdParty = New-Object System.Collections.Generic.HashSet[string]

foreach ($py in $PythonFiles) {
    try {
        Get-Content $py.FullName | ForEach-Object {
            if ($_ -match '^\s*(import|from)\s+([a-zA-Z0-9_\.]+)') {
                $ThirdParty.Add(($matches[2] -split '\.')[0]) | Out-Null
            }
        }
    } catch {}
}

$ThirdParty =
    $ThirdParty |
    Where-Object {
        ($_ -notin $StdLib) -and ($_ -ne "ultimate_pipeline")
    } |
    Sort-Object -Unique

$Requirements = @()

foreach ($pkg in $ThirdParty) {
    try {
        $cmd = "import importlib, pkg_resources; pkg='$pkg'; " +
               "importlib.import_module(pkg); " +
               "print(pkg_resources.get_distribution(pkg).version)"
        $ver = (python -c $cmd 2>$null).Trim()
        if (-not $ver) { $ver = "UNKNOWN" }
        $Requirements += "$pkg==$ver"
    }
    catch {
        $Requirements += "$pkg==UNKNOWN"
    }
}

$ReqOut = Join-Path $OutDir "requirements.auto.txt"

$Requirements |
    Sort-Object -Unique |
    Out-File $ReqOut -Encoding UTF8

# ------------------------------------------------------------
# DONE
# ------------------------------------------------------------
Write-Host "✔ Ultimate pipeline audit complete."
Write-Host "📂 Output directory:"
Write-Host "   $OutDir"
Write-Host "📦 Auto-generated requirements:"
Write-Host "   $ReqOut"
