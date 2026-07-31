<#
.SYNOPSIS
    Bootstrap the CARLA thesis environment in the current PowerShell session.

.DESCRIPTION
    Dot-source this script to load the thesis environment preset, resolve the
    key executable paths, and optionally move to the repository root.

    Example:
        . .\submission\infrastructure\ultimate_pipeline\tools\enter_carla.ps1
        . .\submission\infrastructure\ultimate_pipeline\tools\enter_carla.ps1 -Profile full_evidence

    This is a session helper only. It does not start CARLA, Blender, or OSM2World.

.PARAMETER Profile
    Preset profile to load from thesis_env_preset.ps1.

.PARAMETER NoSetLocation
    Do not change the current directory to the repository root.
#>

[CmdletBinding()]
param(
    [ValidateSet("fast_offline", "full_evidence")]
    [string]$Profile = "fast_offline",

    [switch]$NoSetLocation
)

$ErrorActionPreference = "Stop"

$scriptRoot = $PSScriptRoot
$repoRoot = Resolve-Path (Join-Path $scriptRoot "..\..\..\..")

if (-not $NoSetLocation) {
    Set-Location $repoRoot
}

. (Join-Path $scriptRoot "thesis_env_preset.ps1") -Profile $Profile

# Export compatibility aliases used by several runners and preflight tools.
$env:UP_CARLA_EXE = $env:CARLA_EXE
$env:UP_BLENDER_EXE = $env:BLENDER_EXE
$env:UP_OSM2WORLD_HOME = $env:OSM2WORLD_HOME

function Show-CarlaBootstrapStatus {
    [CmdletBinding()]
    param()

    [pscustomobject]@{
        RepositoryRoot = $repoRoot.Path
        CurrentLocation = (Get-Location).Path
        Profile = $Profile
        Python = (Get-Command python).Source
        UpCarlaExe = $env:UP_CARLA_EXE
        CarlaExe = $env:CARLA_EXE
        UpBlenderExe = $env:UP_BLENDER_EXE
        BlenderExe = $env:BLENDER_EXE
        UpOsm2WorldHome = $env:UP_OSM2WORLD_HOME
        Osm2WorldHome = $env:OSM2WORLD_HOME
        DisableCarla = $env:UP_DISABLE_CARLA
        EnableDomainGap = $env:UP_ENABLE_DOMAIN_GAP
        EnableOsm2World = $env:ENABLE_OSM2WORLD
        EnableBlenderFbx = $env:ENABLE_BLENDER_FBX
    }
}

Show-CarlaBootstrapStatus | Format-List
