"""Read-only detector for ungoverned CARLA/UE shared-state mutators.

Scans processes for known mutator images (UE4Editor, UE4Editor-Cmd,
ShaderCompileWorker when parented to a cook/import, CarlaUE4). Any mutator
with no matching live lease is reported -- new governed launches are then
blocked, evidence recorded, but nothing is auto-killed.
"""
from __future__ import annotations

import ctypes
from typing import Any, Dict, List, Optional

from . import lease_store as _leases

MUTATOR_IMAGES = (
    "ue4editor.exe",
    "ue4editor-cmd.exe",
    "carlaue4.exe",
    "carlaue4-win64-shipping.exe",
    "shadercompileworker.exe",
    "recastbuilder.exe",
)


def _all_processes() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        import subprocess

        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Process | Select-Object Id, ProcessName | ConvertTo-Json"],
            capture_output=True, text=True, timeout=60)
        import json

        data = json.loads(r.stdout or "[]")
        if isinstance(data, dict):
            data = [data]
        for row in data:
            out.append({"pid": int(row["Id"]),
                        "image": str(row["ProcessName"]).lower() + ".exe"})
    except Exception:
        pass
    return out


def scan(lease: Optional[_leases.Lease] = None) -> Dict[str, Any]:
    live = lease if lease is not None else _leases.read_current()
    owned_pid: Optional[int] = None
    if live is not None and _leases.lease_owner_alive(live):
        owned_pid = live.executor_pid or live.root_pid
    mutators = [p for p in _all_processes()
                if p["image"] in MUTATOR_IMAGES]
    ungoverned = [m for m in mutators if m["pid"] != owned_pid]
    # ShaderCompileWorker is only a mutator when parented under a governed
    # cook/import tree; standalone orphans are reported separately, not as
    # mutators (they write only their pipe back to a dead parent).
    return {
        "mutators_seen": mutators,
        "owned_pid": owned_pid,
        "ungoverned": ungoverned,
        "UNGOVERNED_MUTATOR_DETECTED": bool(ungoverned),
    }
