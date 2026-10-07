"""Create a machine-readable CARLA/UE source build receipt without rebuilding."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.ue_executable_discovery import (
    UE4_EDITOR_CANDIDATES,
    UE5_EDITOR_CANDIDATES,
    carla_project_compiled,
    engine_family_from_editor,
    find_carla_server_executable,
    find_editor_executable,
    map_package_cooked,
)


def _value(status: str, value: Any = None, evidence: str | None = None) -> dict[str, Any]:
    return {"status": status, "value": value, "evidence": evidence}


def _git(root: Path, *args: str) -> tuple[str, str]:
    try:
        out = subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.STDOUT, timeout=15).strip()
        return "verified", out
    except Exception as exc:
        return "unknown", str(exc)


def _file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return _value("unknown", None, f"file not found: {path}")
    try:
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        return _value("verified", {"path": str(path), "bytes": path.stat().st_size, "sha256": h}, str(path))
    except OSError as exc:
        return _value("unknown", None, str(exc))


def build_receipt(ue_root: Path | None, carla_root: Path | None) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema": "carla_source_build_receipt/v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": {},
        "ue4": {},
        "carla": {},
        "build": {},
        "environment": {},
        "status_policy": "Every field is verified, unknown, or not_applicable; expected paths never imply build success.",
    }
    repo = Path(__file__).resolve().parents[1]
    status, sha = _git(repo, "rev-parse", "HEAD")
    receipt["repository"] = {"commit": _value(status, sha if status == "verified" else None, "git rev-parse HEAD"), "branch": _value(*_git(repo, "branch", "--show-current"), evidence="git branch --show-current")}
    ue = ue_root or (Path(os.environ["UE4_ROOT"]) if os.environ.get("UE4_ROOT") else None)
    carla = carla_root or (Path(os.environ["CARLA_ROOT"]) if os.environ.get("CARLA_ROOT") else None)
    if ue is None:
        receipt["ue4"] = {"path": _value("unknown", None, "UE4_ROOT not set"), "branch": _value("unknown"), "commit": _value("unknown"), "editor_executable": _value("unknown"), "editor_hash": _value("unknown")}
    else:
        branch_status, branch = _git(ue, "branch", "--show-current") if (ue / ".git").exists() else ("unknown", "not a git worktree")
        commit_status, commit = _git(ue, "rev-parse", "HEAD") if (ue / ".git").exists() else ("unknown", "not a git worktree")
        editor = find_editor_executable(ue, family="ue4", platform_name="windows")
        editor_family = engine_family_from_editor(ue, platform_name="windows")
        receipt["ue4"] = {"path": _value("verified" if ue.exists() else "unknown", str(ue) if ue.exists() else None), "branch": _value(branch_status, branch), "commit": _value(commit_status, commit), "engine_family": _value("verified" if editor_family != "unknown" else "unknown", None if editor_family == "unknown" else editor_family, f"searched {list(UE4_EDITOR_CANDIDATES['windows']) + list(UE5_EDITOR_CANDIDATES['windows'])} under Engine/Binaries/Win64"), "editor_executable": _file(editor) if editor else _value("unknown", None, "no UE4Editor.exe / UnrealEditor.exe found under Engine/Binaries/Win64"), "editor_hash": _file(editor) if editor else _value("unknown")}
    if carla is None:
        receipt["carla"] = {"path": _value("unknown", None, "CARLA_ROOT not set"), "branch": _value("unknown"), "tag": _value("unknown"), "commit": _value("unknown"), "target_version": _value("unknown")}
    else:
        branch_status, branch = _git(carla, "branch", "--show-current") if (carla / ".git").exists() else ("unknown", "not a git worktree")
        commit_status, commit = _git(carla, "rev-parse", "HEAD") if (carla / ".git").exists() else ("unknown", "not a git worktree")
        tag_status, tag = _git(carla, "describe", "--tags", "--exact-match")
        exe = find_carla_server_executable(carla, platform_name="windows") or find_carla_server_executable(carla, platform_name="linux")
        receipt["carla"] = {"path": _value("verified" if carla.exists() else "unknown", str(carla) if carla.exists() else None), "branch": _value(branch_status, branch), "tag": _value(tag_status, tag if tag_status == "verified" else None), "commit": _value(commit_status, commit), "target_version": _value("unknown", None, "not inferred from executable existence"), "executable": _file(exe) if exe else _value("unknown", None, "no CarlaUE4 server binary found"), "project_compiled": carla_project_compiled(carla), "cooked_content": map_package_cooked(carla)}
    receipt["build"] = {
        "compiler_toolset": _value("unknown", None, "no compiler toolchain queried"),
        "build_configuration": _value("unknown"),
        "python_api_build_status": _value("unknown"),
        "carlaue4_build_status": _value("unknown"),
    }
    # Separate, independently-evidenced build/runtime states. A file existing
    # proves only that the file exists; none of these states is derived from
    # another. Unknown remains unknown.
    editor_path = None
    if ue is not None:
        editor_path = find_editor_executable(ue, family="ue4", platform_name="windows")
    server_path = None
    if carla is not None:
        server_path = find_carla_server_executable(carla, platform_name="windows") or find_carla_server_executable(carla, platform_name="linux")
    receipt["build_states"] = {
        "UE_ENGINE_EDITOR_PRESENT": _value(
            "verified" if editor_path else "unknown",
            str(editor_path) if editor_path else None,
            "UE4Editor.exe (UE4.26) or UnrealEditor.exe (UE5) under Engine/Binaries/Win64"
            if editor_path
            else "no editor binary located; no build conclusion drawn",
        ),
        "CARLA_PROJECT_COMPILED": _value(
            carla_project_compiled(carla)["state"] if carla else "unknown",
            None,
            "compiled CARLA project artifacts" if carla else "CARLA_ROOT not set",
        ),
        "CARLA_SERVER_BINARY_PRESENT": _value(
            "verified" if server_path else "unknown",
            str(server_path) if server_path else None,
            "CarlaUE4 server binary" if server_path else "no server binary located; no build conclusion drawn",
        ),
        "CARLA_RPC_RESPONSIVE": _value("unknown", None, "no server was contacted; port listening is not a CARLA RPC response"),
        "MAP_PACKAGE_COOKED": _value(
            map_package_cooked(carla)["state"] if carla else "unknown",
            map_package_cooked(carla)["evidence"] if carla else None,
            "cooked content directories" if carla else "CARLA_ROOT not set",
        ),
        "MAP_RUNTIME_LOADABLE": _value("unknown", None, "no server was started, so no map was loaded at runtime"),
    }
    receipt["environment"] = {
        "UE4_ROOT": _value("verified" if ue else "unknown", str(ue) if ue else None),
        "python_version": _value("verified", sys.version),
        "cmake_version": _value(*_sh_cmake(), evidence="cmake --version") if False else _value("unknown", None, "not queried"),
        "compiler_version": _value("unknown", None, "not queried"),
    }
    return receipt


def _sh_cmake() -> tuple[str, Any]:
    try:
        return "verified", subprocess.check_output(["cmake", "--version"], text=True, stderr=subprocess.STDOUT, timeout=10).strip()
    except Exception as exc:
        return "unknown", str(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ue4-root", type=Path, default=None)
    parser.add_argument("--carla-root", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("carla_source_build_receipt.json"))
    args = parser.parse_args()
    receipt = build_receipt(args.ue4_root, args.carla_root)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
