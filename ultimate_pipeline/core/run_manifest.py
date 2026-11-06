# ultimate_pipeline/core/run_manifest.py
"""Run-manifest writer (research provenance artifact).

Purpose
- Capture a defensible record of each pipeline run: GPS bounds, settings hash,
  key input file hashes (OSM/DEM/calib), and key output hashes (final XODR, reports).
- Best-effort: failures must never crash the pipeline.

Output
- <out_dir>/run_manifest.json

Determinism note:
- The created_utc and updated_utc fields are intentionally excluded from
  determinism comparisons as they capture wall-clock time, not pipeline state.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Use unified hashing utilities
from ultimate_pipeline.utils.file_hashing import sha256_file as _sha256_file
from ultimate_pipeline.utils.file_hashing import safe_md5_file, safe_sha256_file


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _repo_root() -> Path:
    """Repository root for git operations, resolved from this module's location.

    Walks up from the module directory to find the directory containing .git.
    On multi-worktree machines this ensures git operations always bind to the
    actual source repository, never to the current working directory.
    """
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / ".git").is_dir():
            return current
        current = current.parent
    return current


def _atomic_write_text(path: Path, text: str) -> None:
    """Write text atomically via temp file + fsync + os.replace.

    Prevents partial/corrupt files if the process crashes mid-write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp), str(path))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute SHA-256 hash of a file. Wrapper for backward compatibility."""
    return _sha256_file(path, chunk_size=chunk_size)


def _try_cmd(cmd: list[str], cwd: Optional[Path] = None) -> Optional[str]:
    try:
        out = subprocess.check_output(
            cmd, stderr=subprocess.STDOUT, text=True, cwd=str(cwd) if cwd else None
        ).strip()
        return out or None
    except Exception:
        return None


def _fingerprint(path: Path) -> Dict[str, Any]:
    d: Dict[str, Any] = {"path": str(path)}
    try:
        if path.is_file():
            d["exists"] = True
            d["size_bytes"] = path.stat().st_size
            d["sha256"] = sha256_file(path)
            d["md5"] = safe_md5_file(path)
        else:
            d["exists"] = False
    except Exception as e:
        d["exists"] = None
        d["error"] = str(e)
    return d


def update_run_manifest(
        out_dir: str | Path,
        *,
        gps_bounds: Optional[Dict[str, float]] = None,
        settings_snapshot_md5: Optional[str] = None,
        settings_snapshot_sha256: Optional[str] = None,
        settings_schema_version: Optional[str] = None,
        files: Optional[Dict[str, str]] = None,
        outputs: Optional[Dict[str, str]] = None,
        notes: Optional[Dict[str, Any]] = None,
) -> Path:
    """Create or update run_manifest.json (best-effort provenance)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "run_manifest.json"

    manifest: Dict[str, Any] = {}
    if path.exists():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}

    manifest.setdefault("created_utc", _utc_now())
    manifest["updated_utc"] = _utc_now()

    env = manifest.setdefault("env", {})
    env.setdefault("os", platform.platform())
    env.setdefault("python", platform.python_version())
    env.setdefault("machine", platform.machine())
    env.setdefault("git_commit", _try_cmd(["git", "rev-parse", "HEAD"], cwd=_repo_root()))
    env.setdefault("git_status_porcelain", _try_cmd(["git", "status", "--porcelain"], cwd=_repo_root()))

    if gps_bounds is not None:
        manifest["gps_bounds_wgs84"] = gps_bounds

    if settings_snapshot_md5 is not None or settings_snapshot_sha256 is not None or settings_schema_version is not None:
        s = manifest.setdefault("settings", {})
        if settings_snapshot_sha256 is not None:
            s["snapshot_sha256"] = settings_snapshot_sha256
        if settings_snapshot_md5 is not None:
            s["snapshot_md5"] = settings_snapshot_md5
        if settings_schema_version is not None:
            s["schema_version"] = settings_schema_version

    if files:
        inp = manifest.setdefault("inputs", {})
        for k, v in files.items():
            if not v:
                continue
            inp[k] = _fingerprint(Path(v))

    if outputs:
        outp = manifest.setdefault("outputs", {})
        for k, v in outputs.items():
            if not v:
                continue
            outp[k] = _fingerprint(Path(v))

    if notes:
        n = manifest.setdefault("notes", {})
        n.update(notes)

    _atomic_write_text(path, json.dumps(manifest, indent=2, ensure_ascii=False))
    return path
