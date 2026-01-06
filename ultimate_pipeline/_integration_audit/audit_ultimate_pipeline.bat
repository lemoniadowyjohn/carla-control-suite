@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ============================================================
REM Project Audit: structure + modules + dependencies
REM Output: _project_audit\<timestamp>\
REM ============================================================

REM --- Resolve project root = folder where this .bat lives ---
set "ROOT=%~dp0"
REM remove trailing backslash
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

REM --- Choose Python interpreter ---
set "PY=python"
if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"

REM --- Choose scan target (default: ultimate_pipeline) ---
set "SCAN_DIR=%ROOT%\ultimate_pipeline"
if not "%~1"=="" set "SCAN_DIR=%~1"

REM --- Create timestamped output dir ---
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
set "OUT=%ROOT%\_project_audit\%TS%"

mkdir "%OUT%" 2>nul

echo.
echo ============================================================
echo   Project audit starting
echo   ROOT     : %ROOT%
echo   SCAN_DIR : %SCAN_DIR%
echo   PY       : %PY%
echo   OUT      : %OUT%
echo ============================================================
echo.

REM --- Basic environment info ---
"%PY%" -c "import sys,platform; print('python:',sys.version); print('exe:',sys.executable); print('platform:',platform.platform())" > "%OUT%\env.txt" 2>&1

REM --- Project tree ---
echo [1/5] Writing tree...
tree "%ROOT%" /F /A > "%OUT%\tree_full.txt" 2>&1

REM --- Quick file inventory ---
echo [2/5] Writing inventory...
powershell -NoProfile -Command ^
  "Get-ChildItem -Path '%ROOT%' -Recurse -File | Select FullName,Length,LastWriteTime | Sort Length -Descending | ConvertTo-Csv -NoTypeInformation" ^
  > "%OUT%\files_inventory.csv" 2>&1

REM --- pip freeze (from chosen interpreter) ---
echo [3/5] Writing pip freeze...
"%PY%" -m pip freeze > "%OUT%\pip_freeze.txt" 2>&1

REM --- Write analyzer script into OUT dir ---
echo [4/5] Generating analyze_imports.py...
powershell -NoProfile -Command ^
"$code=@'
import os, sys, ast, json, csv

def walk_py_files(scan_dir: str):
    for root, dirs, files in os.walk(scan_dir):
        # ignore common noise folders
        dirs[:] = [d for d in dirs if d not in {'.git','__pycache__','.venv','venv','build','dist','.idea','.pytest_cache'}]
        for f in files:
            if f.endswith('.py'):
                yield os.path.join(root, f)

def safe_read(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
            return fh.read()
    except Exception:
        return ''

def relpath(path: str, base: str) -> str:
    try:
        return os.path.relpath(path, base)
    except Exception:
        return path

def get_stdlib_names():
    # Python 3.10+: sys.stdlib_module_names exists
    try:
        return set(sys.stdlib_module_names)  # type: ignore[attr-defined]
    except Exception:
        # fallback: not perfect, but decent baseline
        return {
            'os','sys','re','math','json','csv','time','datetime','typing','pathlib','itertools','functools',
            'subprocess','threading','multiprocessing','collections','dataclasses','logging','argparse',
            'xml','xml.etree','statistics','random','hashlib','base64','inspect','traceback','pickle',
            'socket','http','urllib','email','unittest'
        }

def top_level(mod: str) -> str:
    # "xml.etree.ElementTree" -> "xml"
    return mod.split('.')[0] if mod else mod

def parse_imports(code: str):
    imports = []
    if not code.strip():
        return imports
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name:
                    imports.append(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                # from X import Y  -> record X
                imports.append(node.module)
            else:
                # relative import: from . import something
                imports.append('.' * (node.level or 1))
    return imports

def is_internal(mod: str):
    # Treat anything in ultimate_pipeline.* as internal
    return mod.startswith('ultimate_pipeline')

def main():
    if len(sys.argv) < 4:
        print('Usage: analyze_imports.py <project_root> <scan_dir> <out_dir>')
        return 2

    project_root = os.path.abspath(sys.argv[1])
    scan_dir     = os.path.abspath(sys.argv[2])
    out_dir      = os.path.abspath(sys.argv[3])

    stdlib = get_stdlib_names()

    imports_by_file = {}
    internal_edges = set()
    external = set()
    internal = set()

    # Build a rough module name for each file (for edge source labels)
    def file_to_module(path: str) -> str:
        rp = relpath(path, project_root).replace('\\','/')
        if rp.endswith('.py'):
            rp = rp[:-3]
        rp = rp.replace('/', '.')
        rp = rp.replace('.__init__', '')
        return rp

    py_files = list(walk_py_files(scan_dir))

    for path in py_files:
        code = safe_read(path)
        imps = parse_imports(code)
        src_mod = file_to_module(path)
        imports_by_file[relpath(path, project_root)] = sorted(set(imps))

        for imp in imps:
            if not imp:
                continue

            # Handle relative imports separately
            if imp.startswith('.'):
                internal.add('(relative)')
                continue

            t = top_level(imp)

            # classify
            if is_internal(imp) or is_internal(t):
                internal.add(imp)
                internal_edges.add((src_mod, imp))
            else:
                if t not in stdlib:
                    external.add(t)

    os.makedirs(out_dir, exist_ok=True)

    # 1) imports by file
    with open(os.path.join(out_dir, 'imports_by_file.json'), 'w', encoding='utf-8') as f:
        json.dump(imports_by_file, f, indent=2)

    # 2) external deps list
    with open(os.path.join(out_dir, 'external_deps.txt'), 'w', encoding='utf-8') as f:
        for x in sorted(external):
            f.write(x + '\n')

    # 3) internal edges CSV
    with open(os.path.join(out_dir, 'internal_import_edges.csv'), 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['from_module','to_import'])
        for a,b in sorted(internal_edges):
            w.writerow([a,b])

    # 4) Graphviz DOT for internal dependencies (optional visualization)
    dot_path = os.path.join(out_dir, 'internal_import_graph.dot')
    with open(dot_path, 'w', encoding='utf-8') as f:
        f.write('digraph imports {\n')
        f.write('  rankdir=LR;\n')
        f.write('  node [shape=box, fontsize=10];\n')
        for a,b in sorted(internal_edges):
            # keep it readable
            bb = b.replace('\"','')
            aa = a.replace('\"','')
            f.write(f'  \"{aa}\" -> \"{bb}\";\n')
        f.write('}\n')

    # 5) summary
    summary_path = os.path.join(out_dir, 'summary.txt')
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(f'project_root: {project_root}\n')
        f.write(f'scan_dir: {scan_dir}\n')
        f.write(f'python_files_scanned: {len(py_files)}\n')
        f.write(f'unique_external_top_level_deps: {len(external)}\n')
        f.write(f'unique_internal_imports: {len(internal)}\n')
        f.write(f'internal_import_edges: {len(internal_edges)}\n')

    print('[OK] Wrote:')
    print(' - imports_by_file.json')
    print(' - external_deps.txt')
    print(' - internal_import_edges.csv')
    print(' - internal_import_graph.dot')
    print(' - summary.txt')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
'@; Set-Content -Path '%OUT%\analyze_imports.py' -Value $code -Encoding UTF8"

REM --- Run analyzer ---
echo [5/5] Running module/dependency analysis...
"%PY%" "%OUT%\analyze_imports.py" "%ROOT%" "%SCAN_DIR%" "%OUT%" > "%OUT%\analyze_imports.log" 2>&1

echo.
echo ============================================================
echo   DONE.
echo   Open: %OUT%
echo   Key files:
echo     - summary.txt
echo     - external_deps.txt
echo     - internal_import_edges.csv
echo     - internal_import_graph.dot
echo     - imports_by_file.json
echo ============================================================
echo.

REM Optionally open the output folder in Explorer
explorer "%OUT%" >nul 2>&1

endlocal
exit /b 0
