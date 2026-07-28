"""Offline-safe RoadRunner and MATLAB installation detection.

All detection is performed through filesystem probes and registry queries
where available. Importing this module must never require RoadRunner or
MATLAB to be installed or on PATH.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class InstallResult:
    """Result of a single executable/tool detection attempt."""

    name: str
    found: bool
    path: Optional[str]
    version: Optional[str]


@dataclass(frozen=True)
class InstallationReport:
    """Aggregated offline-safe installation report."""

    roadrunner_executable: Optional[str]
    roadrunner_release: Optional[str]
    matlab_executable: Optional[str]
    matlab_release: Optional[str]
    roadrunner_api_available: bool
    automated_driving_toolbox: bool
    scene_builder: bool
    roadrunner_scenario: bool
    asset_library_indication: bool
    grpc_proto_files: tuple[str, ...]
    cmd_roadrunner_api: bool
    supported_imports: tuple[str, ...]
    supported_exports: tuple[str, ...]
    authoring_functions: tuple[str, ...]


_ROADRUNNER_SEARCH_NAMES = (
    "roadrunner",
    "RoadRunner",
    "roadrunner64",
    "RoadRunner64",
)

_MATLAB_SEARCH_NAMES = (
    "matlab",
    "matlab.exe",
)

_ROADRUNNER_INSTALL_INDICATORS = (
    "RoadRunner",
    "Automated Driving Toolbox",
    "Scene Builder",
    "RoadRunner Scenario",
    "roadrunnerAPI",
)

_PROTO_EXTENSIONS = (".proto",)

_AUTHORING_FUNCTIONS = (
    "addLineArcRoad",
    "addClothoidFitRoad",
    "addSegmentedRoad",
    "addSpiral",
    "addParametricCubic",
    "addSuperElevation",
    "addLateralProfile",
    "addElevationProfile",
)

_SUPPORTED_IMPORTS = (
    "xodr",
    "osm",
    "fbx",
    "tiled",
    "kml",
    "shapefile",
)

_SUPPORTED_EXPORTS = (
    "xodr",
    "fbx",
    "tiled",
    "kml",
)


def _find_executable(name: str, extra_paths: tuple[str, ...] = ()) -> Optional[str]:
    """Search for an executable on PATH and in extra_paths."""

    found = shutil.which(name)
    if found is not None:
        return str(Path(found).resolve())

    for directory in extra_paths:
        candidate = Path(directory) / name
        if candidate.exists():
            return str(candidate.resolve())

    return None


def _probe_registry(key_paths: tuple[str, ...], value_name: str) -> Optional[str]:
    """Attempt a Windows registry lookup for a string value.

    Returns None on non-Windows platforms, missing keys, or access errors.
    """

    if platform.system() != "Windows":
        return None

    try:
        import winreg  # type: ignore[import-untyped]
    except ImportError:
        return None

    for key_path in key_paths:
        try:
            with winreg.OpenKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                value, _type = winreg.QueryValueEx(key, value_name)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        except OSError:  # noqa: PERF203
            continue

    try:
        for key_path in key_paths:
            with winreg.OpenKeyEx(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _type = winreg.QueryValueEx(key, value_name)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    except OSError:  # noqa: PERF203
        pass

    return None


def _read_file_safe(path: str) -> Optional[str]:
    """Read a file, returning None on any failure."""

    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _detect_roadrunner_release(rr_path: Optional[str]) -> Optional[str]:
    """Attempt to determine the RoadRunner release version."""

    if rr_path is None:
        return None

    parent = Path(rr_path).parent
    release_file = parent / "release_info.json"
    text = _read_file_safe(str(release_file))
    if text is not None:
        try:
            data = json.loads(text)
            version = data.get("version") or data.get("release") or data.get("Version")
            if isinstance(version, str):
                return version.strip()
        except json.JSONDecodeError:
            pass

    version_file = parent / "version.txt"
    text = _read_file_safe(str(version_file))
    if text is not None:
        return text.strip().splitlines()[0].strip() or None

    for sibling in sorted(parent.iterdir()):
        if sibling.suffix == ".txt" and "version" in sibling.name.lower():
            text = _read_file_safe(str(sibling))
            if text is not None and text.strip():
                return text.strip().splitlines()[0].strip() or None

    return None


def _detect_matlab_release(matlab_path: Optional[str]) -> Optional[str]:
    """Attempt to determine the MATLAB release version."""

    if matlab_path is None:
        return None

    root = Path(matlab_path).parent
    for candidate in (root / "bin" / "matlab", root / "matlab"):
        if candidate.exists():
            text = _read_file_safe(str(candidate))
            if text is not None:
                for line in text.splitlines():
                    if "release" in line.lower() or "version" in line.lower():
                        return line.strip()

    version_file = root / "version.txt"
    text = _read_file_safe(str(version_file))
    if text is not None and text.strip():
        return text.strip().splitlines()[0].strip() or None

    return None


def _find_proto_files(search_roots: tuple[str, ...]) -> tuple[str, ...]:
    """Locate .proto files under the given root directories."""

    found: list[str] = []
    for root in search_roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        for path in root_path.rglob("*.proto"):
            try:
                found.append(str(path.resolve()))
            except OSError:
                continue
    return tuple(sorted(found))


def _probe_tool_availability(name: str) -> bool:
    """Check whether a tool name appears in any RoadRunner discovery output."""

    for search_dir in _roadrunner_discovery_dirs():
        for probe_file in ("capabilities.json", "toolmanifest.json", "install.json"):
            candidate = Path(search_dir) / probe_file
            text = _read_file_safe(str(candidate))
            if text is not None and name in text:
                return True
    return False


def _roadrunner_discovery_dirs() -> tuple[str, ...]:
    """Return directories likely to contain RoadRunner installation metadata."""

    dirs: list[str] = []
    for env_var in ("ROADRUNNER_ROOT", "ROADRUNNER_DIR", "RR_ROOT"):
        val = os.environ.get(env_var)
        if val and Path(val).exists():
            dirs.append(val)

    for base in (
        Path.home() / "Documents" / "RoadRunner",
        Path.home() / "AppData" / "Local" / "RoadRunner",
        Path("/Program Files") / "RoadRunner",
        Path("C:") / "Program Files" / "RoadRunner",
    ):
        if base.exists():
            dirs.append(str(base))

    return tuple(dirs)


def probe_installation() -> InstallationReport:
    """Run all offline-safe probes and return an aggregated report."""

    rr_exe = _find_executable("roadrunner") or _find_executable("RoadRunner")
    rr_release = _detect_roadrunner_release(rr_exe)
    if rr_exe is None:
        rr_exe = _find_executable("roadrunner64") or _find_executable("RoadRunner64")
        if rr_exe is not None:
            rr_release = _detect_roadrunner_release(rr_exe)

    matlab_exe = _find_executable("matlab")
    matlab_release = _detect_matlab_release(matlab_exe)

    proto_roots: list[str] = []
    for var in ("ROADRUNNER_ROOT", "RR_ROOT"):
        val = os.environ.get(var)
        if val:
            proto_roots.append(val)
    for d in _roadrunner_discovery_dirs():
        proto_roots.append(d)

    proto_files = _find_proto_files(tuple(proto_roots))

    addons: list[str] = []
    for probe_dir in _roadrunner_discovery_dirs():
        for probe_file in ("addons.json", "plugins.json", "toolboxmanifest.json"):
            text = _read_file_safe(str(Path(probe_dir) / probe_file))
            if text is not None:
                addons.append(text)

    toolbox_available = any("Automated Driving Toolbox" in a for a in addons)
    scene_builder_available = any("Scene Builder" in a for a in addons)
    scenario_available = any("RoadRunner Scenario" in a for a in addons)
    asset_library_available = any("Asset Library" in a for a in addons)
    api_available = any("roadrunnerAPI" in a or "CmdRoadRunnerApi" in a for a in addons)
    cmd_rr_api = any("CmdRoadRunnerApi" in a for a in addons)

    authoring_found = tuple(
        func
        for func in _AUTHORING_FUNCTIONS
        if any(func in a for a in addons) or _probe_tool_availability(func)
    )

    return InstallationReport(
        roadrunner_executable=rr_exe,
        roadrunner_release=rr_release,
        matlab_executable=matlab_exe,
        matlab_release=matlab_release,
        roadrunner_api_available=api_available,
        automated_driving_toolbox=toolbox_available,
        scene_builder=scene_builder_available,
        roadrunner_scenario=scenario_available,
        asset_library_indication=asset_library_available,
        grpc_proto_files=proto_files,
        cmd_roadrunner_api=cmd_rr_api,
        supported_imports=_SUPPORTED_IMPORTS,
        supported_exports=_SUPPORTED_EXPORTS,
        authoring_functions=authoring_found,
    )