#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UE4/UE5 editor and CARLA server executable discovery.

CARLA 0.9.x targets **UE4.26**, whose Windows editor binary is
``Engine/Binaries/Win64/UE4Editor.exe``. ``UnrealEditor.exe`` is the UE5 name
and does not exist in a UE4.26 tree, so tooling that only looks for
``UnrealEditor.exe`` reports "editor absent" on a perfectly complete UE4.26
install. This module searches the real names for the engine family in use.

A discovered file proves only that the file exists. It does **not** prove that
the CARLA project compiled, that the server binary was produced, that a map was
cooked, or that a server answers RPC. Those are separate receipt states and are
never inferred from a path.

The same caveat applies to the two obvious iteration bugs this replaces:
``next(iter((a, b)), None)`` yields only the *first* element, so a single
misspelled or absent first candidate silently masked every later candidate.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

#: Engine families we deliberately support. UE5 detection is kept because the
#: names differ, not because UE5 is the CARLA target.
UE4_EDITOR_CANDIDATES: Dict[str, Sequence[str]] = {
    "windows": ("UE4Editor.exe", "UE4Editor-Cmd.exe"),
    "linux": ("UE4Editor", "UE4Editor-Cmd"),
    "darwin": ("UE4Editor",),
}

UE5_EDITOR_CANDIDATES: Dict[str, Sequence[str]] = {
    "windows": ("UnrealEditor.exe", "UnrealEditor-Cmd.exe"),
    "linux": ("UnrealEditor", "UnrealEditor-Cmd"),
    "darwin": ("UnrealEditor",),
}

#: CARLA server names per family. CARLA 0.9.x builds `CarlaUE4` (UE4 naming);
#: a UE5 port would build `CarlaUnreal`.
CARLA_SERVER_CANDIDATES: Dict[str, Sequence[str]] = {
    "windows": ("CarlaUE4.exe", "CarlaUnreal.exe"),
    "linux": ("CarlaUE4.sh", "CarlaUnreal.sh"),
    "darwin": ("CarlaUE4.sh", "CarlaUnreal.sh"),
}

BINARY_SUBDIRS: Dict[str, Sequence[str]] = {
    "windows": ("Engine/Binaries/Win64", "Engine/Binaries/Win64/ThirdParty"),
    "linux": ("Engine/Binaries/Linux",),
    "darwin": ("Engine/Binaries/Mac",),
}


def editor_candidates(family: str = "ue4", platform_name: str = "windows") -> List[str]:
    """Editor binary names to search, engine family first."""
    table = UE4_EDITOR_CANDIDATES if family == "ue4" else UE5_EDITOR_CANDIDATES
    return list(table.get(platform_name, ()))


def find_editor_executable(
    ue_root: Path,
    *,
    family: str = "ue4",
    platform_name: str = "windows",
    subdirs: Optional[Sequence[str]] = None,
) -> Optional[Path]:
    """Return the first existing editor binary under ``ue_root``.

    Searches every candidate name in every binary subdirectory. Returns None
    when nothing matches; the caller must keep the state ``unknown``/absent
    rather than concluding anything about the build.
    """
    if ue_root is None:
        return None
    root = Path(ue_root)
    dirs = list(subdirs) if subdirs is not None else list(
        BINARY_SUBDIRS.get(platform_name, ("Engine/Binaries/Win64",))
    )
    for subdir in dirs:
        base = root / subdir
        for name in editor_candidates(family, platform_name):
            candidate = base / name
            if candidate.is_file():
                return candidate
    # Also probe the root itself, so a non-standard layout is still discoverable
    # rather than silently reported missing.
    for name in editor_candidates(family, platform_name):
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def find_carla_server_executable(
    carla_root: Path, *, platform_name: str = "windows"
) -> Optional[Path]:
    """Return the CARLA server binary under ``carla_root``, if present."""
    if carla_root is None:
        return None
    root = Path(carla_root)
    names = CARLA_SERVER_CANDIDATES.get(platform_name, ())
    search_dirs = [root, root / "Binaries" / "Win64", root / "Binaries" / "Linux"]
    for directory in search_dirs:
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def carla_project_compiled(carla_root: Path) -> Dict[str, Any]:
    """Detect a compiled CARLA project/script module tree.

    Presence of a compiled module directory is evidence that the C++ project
    was built. It is still not evidence that the server binary exists.
    """
    root = Path(carla_root) if carla_root else None
    if root is None:
        return {
            "state": "unknown",
            "reason": "carla_root_not_supplied",
            "evidence": None,
        }
    markers = (
        root / "Binaries" / "Win64" / "UnrealEditor-Carla.dll",
        root / "Binaries" / "Win64" / "CarlaUE4.target",
        root / "Binaries" / "Linux" / "UnrealEditor-Carla.so",
        root / "CarlaUE4" / "Binaries" / "Win64" / "UnrealEditor-Carla.dll",
    )
    found = [str(p) for p in markers if p.exists()]
    if found:
        return {
            "state": "present",
            "evidence": found,
            "note": "compiled project artifacts found; not a server-binary claim",
        }
    return {
        "state": "absent",
        "evidence": None,
        "reason": "no compiled CARLA project artifacts found under carla_root",
    }


def map_package_cooked(carla_root: Path, content_dir: str = " cooked") -> Dict[str, Any]:
    """Report whether any cooked CARLA content package exists.

    A cooked package directory existing is a necessary but not sufficient
    condition for a specific map to be loadable at runtime.
    """
    root = Path(carla_root) if carla_root else None
    if root is None:
        return {"state": "unknown", "reason": "carla_root_not_supplied", "evidence": None}
    cooked = root / "Content" / "Cooked"
    if not cooked.is_dir():
        return {
            "state": "absent",
            "reason": f"no cooked content directory: {cooked}",
            "evidence": None,
        }
    entries = sorted(p.name for p in cooked.iterdir() if p.is_dir())
    return {
        "state": "present" if entries else "absent",
        "evidence": entries,
        "note": "cooked content directories exist; per-map runtime loadability is unverified",
    }


def engine_family_from_editor(ue_root: Path, *, platform_name: str = "windows") -> str:
    """Report which engine family is installed, as evidence rather than a guess."""
    if find_editor_executable(ue_root, family="ue4", platform_name=platform_name):
        return "ue4"
    if find_editor_executable(ue_root, family="ue5", platform_name=platform_name):
        return "ue5"
    return "unknown"
