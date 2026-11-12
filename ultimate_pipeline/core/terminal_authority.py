#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Terminal authority utilities: stale SUCCESS revocation, run identity, etc.

These are extracted as standalone functions so they can be tested without
triggering the full MainPipeline import cascade.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def revoke_stale_success(out_dir: str | os.PathLike[str]) -> None:
    """Detect and revoke any pre-existing SUCCESS.txt before a new run mutates state.

    Fail-closed: if the stale SUCCESS cannot be removed, the run must not proceed.

    Args:
        out_dir: The pipeline output directory for this run.

    Raises:
        RuntimeError: If a stale SUCCESS.txt exists but cannot be deleted.
    """
    success_path = Path(out_dir) / "SUCCESS.txt"
    if success_path.is_file():
        try:
            stale_hash = hashlib.sha256(success_path.read_bytes()).hexdigest()[:16]
        except Exception:
            stale_hash = "unreadable"
        try:
            success_path.unlink()
            print(f"🗑️  Revoked stale SUCCESS.txt (sha256:{stale_hash}) from previous run")
        except Exception as e:
            raise RuntimeError(
                f"❌ Failed to revoke stale SUCCESS.txt (sha256:{stale_hash}): {e}. "
                "A new run must never proceed while stale SUCCESS remains authoritative."
            ) from e


def generate_run_id() -> str:
    """Generate a new immutable run ID."""
    return uuid.uuid4().hex


def generate_run_started_at() -> str:
    """Generate the run start timestamp in ISO format (UTC)."""
    return datetime.now(timezone.utc).isoformat()


def compute_settings_digest(settings_obj: Any) -> str:
    """Compute a deterministic SHA-256 of the effective settings snapshot."""
    try:
        snapshot = {
            k: getattr(settings_obj, k)
            for k in dir(settings_obj)
            if k.isupper() and not callable(getattr(settings_obj, k))
        }
        blob = json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()
    except Exception:
        return ""


def get_source_sha() -> str:
    """Return the current Git commit SHA, or a deterministic placeholder."""
    try:
        import subprocess

        repo_root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def get_effective_profile(settings_obj: Any) -> str:
    """Resolve the effective release profile from settings or environment."""
    profile = getattr(settings_obj, "RELEASE_PROFILE", "")
    if not profile:
        profile = os.getenv("UP_RELEASE_PROFILE", "")
    if not profile:
        profile = "structural_release"
    return profile.lower()


def write_run_identity(
    out_dir: str | os.PathLike[str],
    run_id: str,
    source_sha: str,
    profile: str,
    settings_digest: str,
    started_at_utc: str,
) -> None:
    """Write run_identity.json at admission time."""
    identity = {
        "run_id": run_id,
        "source_sha": source_sha,
        "profile": profile,
        "settings_digest": settings_digest,
        "started_at_utc": started_at_utc,
        "out_dir": str(out_dir),
    }
    path = Path(out_dir) / "run_identity.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write((json.dumps(identity, indent=2, sort_keys=True) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        if json.loads(path.read_text(encoding="utf-8")) != identity:
            raise RuntimeError("run_identity.json durable reread differs")
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def read_run_identity(out_dir: str | os.PathLike[str]) -> dict | None:
    """Read run_identity.json if present."""
    path = Path(out_dir) / "run_identity.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None