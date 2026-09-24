"""Offline resource and environment preflight for Unreal/CARLA cook planning (O5)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

GIB = 1024 ** 3


def _path_root(value: str | None, fallback: Path) -> Path:
    return Path(value) if value else fallback


def disk_check(label: str, path: Path, required_gib: float) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
        free = usage.free / GIB
        return {"check": label, "status": "PASS" if free >= required_gib else "BLOCKED", "path": str(path), "free_gib": round(free, 3), "required_gib": required_gib, "remediation": f"Free at least {required_gib} GiB on {path}; no files were deleted."}
    except (OSError, ValueError) as exc:
        return {"check": label, "status": "INCOMPLETE", "path": str(path), "required_gib": required_gib, "reason": str(exc), "remediation": "Make the path available or pass a different path; no files were deleted."}


def ram_check(required_gib: float) -> dict[str, Any]:
    try:
        import psutil  # type: ignore
        mem = psutil.virtual_memory()
        available = mem.available / GIB
        total = mem.total / GIB
        return {"check": "ram", "status": "PASS" if available >= required_gib else "BLOCKED", "available_gib": round(available, 3), "total_gib": round(total, 3), "required_gib": required_gib, "remediation": f"Free at least {required_gib} GiB RAM; no processes were terminated."}
    except Exception as exc:
        return {"check": "ram", "status": "INCOMPLETE", "required_gib": required_gib, "reason": f"psutil unavailable: {exc}", "remediation": "Install psutil or provide host memory evidence; no processes were terminated."}


def vram_check(required_gib: float | None) -> dict[str, Any]:
    if not shutil.which("nvidia-smi"):
        return {"check": "vram", "status": "INCOMPLETE", "available_gib": None, "required_gib": required_gib, "reason": "nvidia-smi unavailable; no exact VRAM requirement inferred.", "remediation": "Run nvidia-smi or provide a verified GPU inventory; no VRAM claim is made."}
    try:
        output = subprocess.check_output(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"], text=True, stderr=subprocess.STDOUT, timeout=10)
        values = [float(line.strip()) / 1024 for line in output.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"check": "vram", "status": "INCOMPLETE", "available_gib": None, "required_gib": required_gib, "reason": str(exc), "remediation": "Verify nvidia-smi availability; no VRAM claim is made."}
    if not values:
        return {"check": "vram", "status": "INCOMPLETE", "available_gib": None, "required_gib": required_gib, "reason": "nvidia-smi returned no GPU rows", "remediation": "Provide verified GPU inventory; no VRAM claim is made."}
    largest = max(values)
    return {"check": "vram", "status": "PASS" if required_gib is None or largest >= required_gib else "BLOCKED", "available_gib": round(largest, 3), "required_gib": required_gib, "remediation": "Use a host with sufficient verified VRAM or keep required_gib unset; no exact requirement is inferred."}


def executable_check(label: str, value: str | None, candidates: list[str]) -> dict[str, Any]:
    if value:
        path = Path(value)
        if path.is_file() or path.is_dir():
            return {"check": label, "status": "PASS", "path": str(path)}
        return {"check": label, "status": "BLOCKED", "path": str(path), "reason": "configured path does not exist", "remediation": f"Set {label} to an existing path; no files were changed."}
    found = [shutil.which(c) for c in candidates]
    found = [item for item in found if item]
    if found:
        return {"check": label, "status": "PASS", "path": found[0]}
    return {"check": label, "status": "BLOCKED", "required_candidates": candidates, "reason": "no configured path or executable found", "remediation": f"Set {label} or install one of {candidates}; no files were changed."}


def preflight(repo_root: Path, unreal_root: Path | None, temp_root: Path | None, min_repo_gib: float, min_unreal_gib: float, min_temp_gib: float, min_ram_gib: float, required_vram_gib: float | None) -> dict[str, Any]:
    checks = [
        disk_check("repository_disk", repo_root, min_repo_gib),
        disk_check("unreal_build_disk", unreal_root or repo_root, min_unreal_gib),
        disk_check("temporary_cache_disk", temp_root or Path(tempfile.gettempdir()), min_temp_gib),
        ram_check(min_ram_gib),
        vram_check(required_vram_gib),
        executable_check("carla_root", os.environ.get("CARLA_ROOT"), ["CarlaUE4.exe", "CarlaUE4.sh"]),
        executable_check("ue4_root", os.environ.get("UE4_ROOT"), ["UnrealEditor.exe", "UnrealEditor"]),
    ]
    hard = [c for c in checks if c.get("status") == "BLOCKED"]
    incomplete = [c for c in checks if c.get("status") == "INCOMPLETE"]
    status = "BLOCKED" if hard else ("INCOMPLETE" if incomplete else "PASS")
    return {"schema": "unreal_cook_resource_preflight/v1", "status": status, "claim": "READY_FOR_COOK_PLANNING" if status == "PASS" else "NOT_READY_FOR_COOK_PLANNING", "checks": checks, "remediation_policy": "Report-only; no files are deleted, processes terminated, or thresholds silently changed."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--unreal-root", type=Path, default=None)
    parser.add_argument("--temp-root", type=Path, default=None)
    parser.add_argument("--min-repo-gib", type=float, default=10.0)
    parser.add_argument("--min-unreal-gib", type=float, default=50.0)
    parser.add_argument("--min-temp-gib", type=float, default=10.0)
    parser.add_argument("--min-ram-gib", type=float, default=8.0)
    parser.add_argument("--required-vram-gib", type=float, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args()
    result = preflight(args.repo_root, args.unreal_root, args.temp_root, args.min_repo_gib, args.min_unreal_gib, args.min_temp_gib, args.min_ram_gib, args.required_vram_gib)
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.json_out:
        args.json_out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if result["status"] == "PASS" else 2 if result["status"] == "BLOCKED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
