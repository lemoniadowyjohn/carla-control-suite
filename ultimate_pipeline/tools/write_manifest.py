#!/usr/bin/env python3
"""
Write MANIFEST.json / MANIFEST.txt for a run directory.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, Any, List


from ultimate_pipeline.utils.file_hashing import sha256_file


def _git_commit_hash(repo_root: Path) -> str:
    try:
        head = repo_root / ".git" / "HEAD"
        if not head.is_file():
            return "unknown"
        ref = head.read_text(encoding="utf-8").strip()
        if ref.startswith("ref:"):
            target = ref.split(" ", 1)[1].strip()
            ref_path = repo_root / ".git" / target
            if ref_path.is_file():
                val = ref_path.read_text(encoding="utf-8").strip()
                return val
            packed = repo_root / ".git" / "packed-refs"
            if packed.is_file():
                with packed.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or line.startswith("^"):
                            continue
                        parts = line.split()
                        if len(parts) == 2 and parts[1] == target:
                            return parts[0]
        return ref
    except Exception:
        return "unknown"


def _required_listing(required_files: List[str], run_dir: Path) -> List[Dict[str, Any]]:
    out = []
    for rel in required_files:
        p = run_dir / rel
        exists = p.is_file()
        size = p.stat().st_size if exists else None
        entry = {"path": str(p), "exists": exists, "size": size}
        if exists:
            try:
                entry["sha256"] = sha256_file(p)
            except Exception:
                entry["sha256"] = None
        out.append(entry)
    return out


def write_run_manifest(run_dir: str | Path, fields: Dict[str, Any], required_files: List[str]) -> None:
    run_path = Path(run_dir)
    repo_root = run_path
    for parent in [run_path] + list(run_path.parents):
        if (parent / ".git").exists():
            repo_root = parent
            break

    manifest = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit": _git_commit_hash(repo_root),
        "fields": fields,
        "required": _required_listing(required_files, run_path),
    }

    manifest_path = run_path / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    lines = [
        f"timestamp_utc: {manifest['timestamp_utc']}",
        f"git_commit: {manifest['git_commit']}",
    ]
    for k in sorted(fields.keys()):
        lines.append(f"{k}: {fields[k]}")
    lines.append("required:")
    for req in manifest["required"]:
        lines.append(f"  - path: {req['path']} exists: {req['exists']} size: {req['size']}")
    (run_path / "MANIFEST.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
