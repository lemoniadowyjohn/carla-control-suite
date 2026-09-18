#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Finalize run outputs with signature.json and SUCCESS.txt."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable


def _hash_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_within(base: Path, target: Path) -> bool:
    """Check if target is inside base directory."""
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def write_signature_json(out_dir: str, key_paths: Iterable[str]) -> Dict[str, Any]:
    """Write signature.json with SHA-256 hashes of files.

    Keys are POSIX-style relative paths to out_dir.
    Files outside out_dir are silently skipped.
    """
    out_path = Path(out_dir).resolve()
    sig: Dict[str, Any] = {"hash_algorithm": "sha256", "files": {}}
    for p in key_paths:
        if not p:
            continue
        path = Path(p)
        if not path.is_absolute():
            path = out_path / path
        path = path.resolve()

        # Skip files outside out_dir (not portable)
        if not _is_within(out_path, path):
            continue

        if path.is_file():
            try:
                # Use POSIX-style relative path as key
                rel_key = path.relative_to(out_path).as_posix()
                sig["files"][rel_key] = _hash_file_sha256(path)
            except Exception:
                pass
    text = json.dumps(sig, indent=2, sort_keys=True)
    if not text.endswith("\n"):
        text += "\n"
    (out_path / "signature.json").write_text(text, encoding="utf-8")
    return sig


def write_success_txt(out_dir: str, summary: str = "") -> None:
    out_path = Path(out_dir)
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    body = f"OK {ts}\n"
    if summary:
        body += f"{summary.strip()}\n"
    (out_path / "SUCCESS.txt").write_text(body, encoding="utf-8")
