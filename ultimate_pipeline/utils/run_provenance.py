#!/usr/bin/env python3
"""Run provenance collection and writing utilities.

This module provides reusable functions to collect and write provenance
metadata for thesis reproducibility. Works on both Windows and Linux,
and gracefully handles missing git or pip.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _safe_subprocess(cmd: List[str], timeout: float = 5.0) -> Optional[str]:
    """Run a command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def _get_git_commit() -> Optional[str]:
    """Get current git commit SHA, or None if not in a git repo."""
    return _safe_subprocess(["git", "rev-parse", "HEAD"])


def _get_git_branch() -> Optional[str]:
    """Get current git branch name, or None if not in a git repo."""
    return _safe_subprocess(["git", "rev-parse", "--abbrev-ref", "HEAD"])


def _get_git_dirty() -> Optional[bool]:
    """Check if working directory has uncommitted changes."""
    status = _safe_subprocess(["git", "status", "--porcelain"])
    if status is None:
        return None
    return len(status) > 0


def _get_pip_freeze() -> Optional[List[str]]:
    """Get pip freeze output as a list of package specs."""
    output = _safe_subprocess([sys.executable, "-m", "pip", "freeze"], timeout=30.0)
    if output is None:
        return None
    return [line.strip() for line in output.splitlines() if line.strip()]


def _get_up_env_vars() -> Dict[str, str]:
    """Collect environment variables starting with UP_."""
    return {k: v for k, v in os.environ.items() if k.startswith("UP_")}


def collect_provenance(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Collect provenance metadata for the current run.

    Collects:
    - Python version and platform info
    - Git commit SHA (if in a git repo, best-effort)
    - Git branch and dirty status (best-effort)
    - pip freeze output (best-effort)
    - Environment variables starting with UP_
    - Any extra metadata provided

    Args:
        extra: Optional dictionary of extra metadata to merge in.

    Returns:
        Dictionary containing all collected provenance data.
    """
    provenance: Dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": {
            "version": sys.version,
            "version_info": list(sys.version_info[:3]),
            "executable": sys.executable,
            "platform": sys.platform,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "node": platform.node(),
        },
    }

    # Git info (best-effort)
    git_commit = _get_git_commit()
    git_branch = _get_git_branch()
    git_dirty = _get_git_dirty()

    if git_commit is not None:
        provenance["git"] = {
            "commit": git_commit,
            "branch": git_branch,
            "dirty": git_dirty,
        }

    # pip freeze (best-effort)
    pip_packages = _get_pip_freeze()
    if pip_packages is not None:
        provenance["pip_freeze"] = pip_packages

    # UP_ environment variables
    up_env = _get_up_env_vars()
    if up_env:
        provenance["up_env_vars"] = up_env

    # Merge extra metadata
    if extra:
        provenance["extra"] = extra

    return provenance


def write_provenance(out_dir: str, provenance: Dict[str, Any]) -> Path:
    """Write provenance data to a JSON file.

    Args:
        out_dir: Output directory path.
        provenance: Provenance dictionary to write.

    Returns:
        Path to the written provenance.json file.
    """
    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)

    provenance_file = out_path / "provenance.json"
    with provenance_file.open("w", encoding="utf-8") as f:
        json.dump(provenance, f, indent=2)

    return provenance_file


def collect_and_write_provenance(
    out_dir: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Convenience function to collect and write provenance in one call.

    Args:
        out_dir: Output directory path.
        extra: Optional extra metadata to include.

    Returns:
        The collected provenance dictionary.
    """
    provenance = collect_provenance(extra)
    write_provenance(out_dir, provenance)
    return provenance


# CLI for testing/debugging
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Collect and display run provenance")
    ap.add_argument("--out", help="Output directory to write provenance.json")
    ap.add_argument("--json", action="store_true", help="Output as JSON (default: formatted)")
    args = ap.parse_args()

    prov = collect_provenance()

    if args.out:
        written = write_provenance(args.out, prov)
        print(f"Wrote provenance to: {written}")
    elif args.json:
        print(json.dumps(prov, indent=2))
    else:
        print("=== Run Provenance ===")
        print(f"Timestamp: {prov['timestamp_utc']}")
        print(f"Python: {prov['python']['version_info']}")
        print(f"Platform: {prov['platform']['system']} {prov['platform']['release']}")
        if "git" in prov:
            print(f"Git: {prov['git']['commit'][:12]}... ({prov['git']['branch']})")
            if prov["git"].get("dirty"):
                print("  (working directory has uncommitted changes)")
        if "up_env_vars" in prov:
            print(f"UP_ env vars: {list(prov['up_env_vars'].keys())}")
        if "pip_freeze" in prov:
            print(f"Packages: {len(prov['pip_freeze'])} installed")
