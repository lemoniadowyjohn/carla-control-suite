# -*- coding: utf-8 -*-
"""Canonical hashing helpers for research evidence.

Every governed receipt is serialized through ``canonical_json_bytes``
before being hashed, so the receipt digest is reproducible and independent
of dict ordering.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


def canonical_json_bytes(obj: Any) -> bytes:
    """Deterministic JSON encoding: sorted keys, ASCII, no insignificant space."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_of_jsonable(obj: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(obj)).hexdigest()


def sha256_file(path: str | Path) -> str:
    """Streaming SHA256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_dirty_worktree(repo_root: str | Path) -> bool:
    """True when the tracked worktree differs from HEAD (untracked files ignored).

    Untracked scratch files (logs, artifacts) do not change published code
    identity; tracked modifications do.
    """
    import subprocess

    out = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(out.stdout.strip()) or out.returncode != 0


def git_head_sha(repo_root: str | Path) -> str:
    import subprocess

    out = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo_root), capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


SECRET_KEY_MARKERS = ("PASSWORD", "TOKEN", "SECRET", "KEY", "CREDENTIAL", "PASSW")


def safe_env_record(env: dict[str, str] | None = None) -> dict[str, str]:
    """Effective-environment record with secret-valued keys masked.

    Keys whose name contains a secret marker are replaced by ``"<redacted>"``;
    everything else is recorded verbatim so the receipt shows exactly the
    governed environment the run executed under.
    """
    env = dict(os.environ) if env is None else dict(env)
    out: dict[str, str] = {}
    for k in sorted(env):
        if any(marker in k.upper() for marker in SECRET_KEY_MARKERS):
            out[k] = "<redacted>"
        else:
            out[k] = env[k]
    return out
