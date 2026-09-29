@echo off
setlocal enabledelayedexpansion

rem ============================================================================
rem CARLA 0.9.16 Source Build Ladder (fixed)
rem ============================================================================

rem Set root path WITH TRAILING BACKSLASH (critical for path concatenation in scripts)
set ROOT_PATH=G:\CARLA\carla_source_probe\

rem Unreal Engine root (manually set since registry key missing)
set UE4_ROOT=G:\UnrealEngine_4.26_CARLA\

rem Dependency installation directory (same as Build/)
set INSTALLATION_DIR=%ROOT_PATH%Build\

rem Set up Visual Studio 2022 x64 environment
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"

cd %ROOT_PATH%
echo ROOT_PATH=%ROOT_PATH%
echo UE4_ROOT=%UE4_ROOT%
echo INSTALLATION_DIR=%INSTALLATION_DIR%
echo Build started at %date% %time%

rem ============================================================================
rem Pre-setup: Generate Build/CMakeLists.txt.in using helper script
rem ============================================================================
python "%~dp0create_cmake_config.py"

rem ============================================================================
rem Step 1: Build LibCarla (server + client)
rem ============================================================================
echo.
echo =============================================================
echo Step 1: Building LibCarla (server + client)
echo =============================================================
call "%ROOT_PATH%Util\BuildTools\BuildLibCarla.bat" --server --client --generator "Visual Studio 17 2022"
set LIB_CARLA_EXIT=%ERRORLEVEL%
echo LibCarla exit code: %LIB_CARLA_EXIT%
if %LIB_CARLA_EXIT% neq 0 (
    echo ERROR: LibCarla build failed
    exit /b %LIB_CARLA_EXIT%
)

rem ============================================================================
rem Step 2: Build OSM2ODR (OSM to OpenDRIVE conversion)
rem ============================================================================
echo.
echo =============================================================
echo Step 2: Building OSM2ODR
echo =============================================================
call "%ROOT_PATH%Util\BuildTools\BuildOSM2ODR.bat" --build --generator "Visual Studio 17 2022"
set OSM2ODR_EXIT=%ERRORLEVEL%
echo OSM2ODR exit code: %OSM2ODR_EXIT%
if %OSM2ODR_EXIT% neq 0 (
    echo ERROR: OSM2ODR build failed
    exit /b %OSM2ODR_EXIT%
)

rem ============================================================================
rem Step 3: Build Python API
rem ============================================================================
echo.
echo =============================================================
echo Step 3: Building Python API
echo =============================================================
call "%ROOT_PATH%Util\BuildTools\BuildPythonAPI.bat"
set PYTHONAPI_EXIT=%ERRORLEVEL%
echo PythonAPI exit code: %PYTHONAPI_EXIT%
if %PYTHONAPI_EXIT% neq 0 (
    echo ERROR: PythonAPI build failed
    exit /b %PYTHONAPI_EXIT%
)

rem ============================================================================
rem Step 4: Build and launch CarlaUE4
rem ============================================================================
echo.
echo =============================================================
echo Step 4: Building and launching CarlaUE4
echo =============================================================
call "%ROOT_PATH%Util\BuildTools\BuildCarlaUE4.bat" --build --launch
set LAUNCH_EXIT=%ERRORLEVEL%
echo Launch exit code: %LAUNCH_EXIT%
if %LAUNCH_EXIT% neq 0 (
    echo ERROR: CarlaUE4 launch failed
    exit /b %LAUNCH_EXIT%
)

echo.
echo =============================================================
echo BUILD LADDER COMPLETE - ALL STEPS PASSED
echo =============================================================