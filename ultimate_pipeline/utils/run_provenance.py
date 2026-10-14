#!/usr/bin/env python3
"""Run provenance collection and writing utilities.

This module provides reusable functions to collect and write provenance
metadata for thesis reproducibility. Works on both Windows and Linux, and
gracefully handles missing git or pip.

V5 / NEW-203 (closure D17)
--------------------------
The historical behaviour is *best effort*: git identity is derived from the
process working directory, git information is silently omitted when a command
fails, and every environment variable beginning with ``UP_`` is serialized.

That is fine for diagnostics but unsafe for release evidence. This module now
adds a **strict release provenance mode** alongside the preserved best-effort
mode:

* git commands are resolved explicitly against a caller-supplied repository
  root (``git -C <repo_root> ...``) -- the process CWD is never trusted;
* strict mode is *fail closed* -- git unavailable, repo identity unavailable,
  HEAD unavailable, expected-SHA mismatch or a dirty tree where a clean tree is
  required all yield ``status != PASS`` with an explicit failure list, never a
  silently omitted field;
* environment capture uses an explicit, documented **allow-list** of
  non-secret reproducibility variables. Secret-like variables (keys, tokens,
  passwords, credentials, authorization headers) are never written, even when
  they start with ``UP_``.

This module is the single canonical owner for run provenance. No parallel
``strict_provenance`` module exists or may be introduced.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "PROVENANCE_SCHEMA",
    "STRICT_SCHEMA",
    "RELEASE_SAFE_ENV_ALLOWLIST",
    "SECRET_NAME_PATTERN",
    "STATUS_PASS",
    "STATUS_FAIL",
    "is_secret_like_name",
    "filter_release_safe_env",
    "collect_provenance",
    "collect_strict_release_provenance",
    "write_provenance",
    "collect_and_write_provenance",
    "collect_and_write_strict_release_provenance",
]

PROVENANCE_SCHEMA = "RUN_PROVENANCE/v2"
STRICT_SCHEMA = "STRICT_RELEASE_PROVENANCE/v2"

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"

#: Documented allow-list of non-secret reproducibility environment variables.
#: Only variables listed here (or explicitly supplied by the caller) are ever
#: serialized into a provenance receipt. Everything else is excluded by default.
RELEASE_SAFE_ENV_ALLOWLIST: Tuple[str, ...] = (
    "UP_CARLA_VERSION",
    "UP_CARLA_HOST",
    "UP_CARLA_PORT",
    "UP_ENABLE_CARLA_TESTS",
    "UP_COOKED_PACKAGE_SHA256",
    "UP_COOK_MANIFEST_SHA256",
    "UP_IMPORT_PACKAGE_SHA256",
    "UP_MAP_REGISTRY_ID",
    "UP_RUNTIME_MAP",
    "UP_XODR_SHA256",
    "UP_RELEASE_ID",
    "UP_CANDIDATE_ID",
    "UP_SEED",
    "UP_SUBSET",
    "UP_UE_BUILD",
    "UP_RUN_ID",
    "UP_CONCURRENCY",
    "UP_DEVICE",
)

#: Substrings that make a variable name secret-like regardless of prefix.
SECRET_NAME_PATTERN = re.compile(
    r"(SECRET|TOKEN|PASSWORD|PASSWD|PWD|CREDENTIAL|API[_-]?KEY|APIKEY|AUTH|AUTHORIZATION"
    r"|PRIVATE[_-]?KEY|SESSION|COOKIE|ACCESS[_-]?KEY|SIGNING|ENCRYPTION|PASSPHRASE)",
    re.IGNORECASE,
)

_GIT_TIMEOUT = 10.0


# ---------------------------------------------------------------------------
# subprocess / git helpers
# ---------------------------------------------------------------------------


def _safe_subprocess(
    cmd: List[str], timeout: float = 5.0, cwd: Optional[str] = None
) -> Optional[str]:
    """Run a command and return stdout, or None on failure (best-effort path)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def _git(
    repo_root: Optional[str], *args: str, timeout: float = _GIT_TIMEOUT
) -> Tuple[bool, str, str]:
    """Run ``git -C <repo_root> <args>``.

    Returns ``(ok, stdout, stderr)``. ``repo_root`` is passed explicitly via
    ``-C`` so provenance never depends on the process working directory.
    """
    cmd: List[str] = ["git"]
    if repo_root is not None:
        cmd += ["-C", str(repo_root)]
    cmd += list(args)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        return False, "", f"git executable not found: {exc}"
    except subprocess.TimeoutExpired as exc:
        return False, "", f"git command timed out after {timeout}s: {exc}"
    except OSError as exc:
        return False, "", f"git command failed to execute: {exc}"
    return proc.returncode == 0, proc.stdout.strip(), proc.stderr.strip()


def _git_cwd_args(repo_root: Optional[str]) -> List[str]:
    """``git -C <root>`` prefix, or empty when no root is bound (best effort)."""
    return ["-C", str(repo_root)] if repo_root else []


def _get_git_commit(repo_root: Optional[str] = None) -> Optional[str]:
    """Get HEAD SHA for ``repo_root`` (or the CWD in best-effort mode)."""
    return _safe_subprocess(["git", *_git_cwd_args(repo_root), "rev-parse", "HEAD"])


def _get_git_branch(repo_root: Optional[str] = None) -> Optional[str]:
    """Get the current branch name for ``repo_root``."""
    return _safe_subprocess(
        ["git", *_git_cwd_args(repo_root), "rev-parse", "--abbrev-ref", "HEAD"]
    )


def _get_git_dirty(repo_root: Optional[str] = None) -> Optional[bool]:
    """Check whether ``repo_root`` has uncommitted changes."""
    out = _safe_subprocess(
        ["git", *_git_cwd_args(repo_root), "status", "--porcelain"]
    )
    if out is None:
        return None
    return len(out) > 0


def _get_pip_freeze() -> Optional[List[str]]:
    """Get pip freeze output as a list of package specs."""
    output = _safe_subprocess([sys.executable, "-m", "pip", "freeze"], timeout=30.0)
    if output is None:
        return None
    return [line.strip() for line in output.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# environment sanitization
# ---------------------------------------------------------------------------


def is_secret_like_name(name: str) -> bool:
    """True when an environment variable *name* looks secret-bearing."""
    if not name:
        return False
    return bool(SECRET_NAME_PATTERN.search(name))


def filter_release_safe_env(
    environ: Optional[Dict[str, str]] = None,
    *,
    allowlist: Optional[Iterable[str]] = None,
) -> Dict[str, str]:
    """Return only release-safe, non-secret environment variables.

    Three independent filters must all pass:

    1. the name is in the documented allow-list (unless the caller supplies
       extra names, which are themselves still screened for secret-like names);
    2. the name is not secret-like;
    3. the *value* is not a recognized secret payload shape.
    """
    env = os.environ if environ is None else environ
    allowed = set(RELEASE_SAFE_ENV_ALLOWLIST)
    if allowlist:
        allowed.update(allowlist)

    result: Dict[str, str] = {}
    for name, value in env.items():
        if name not in allowed:
            continue
        if is_secret_like_name(name):
            continue
        if not isinstance(value, str):
            continue
        if _looks_like_secret_value(value):
            continue
        result[name] = value
    return result


def _looks_like_secret_value(value: str) -> bool:
    """Reject values that are obviously embedded credentials."""
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if not stripped:
        return False
    upper = stripped.upper()
    if upper.startswith(("BEARER ", "BASIC ", "TOKEN ")):
        return True
    if re.match(r"^(sk|pk|ghp|gho|ghu|ghs|xox[baprs])[-_]", stripped):
        return True
    if stripped.count(".") == 2 and len(stripped) > 40 and re.match(r"^[A-Za-z0-9_\-]+$", stripped):
        return True
    return False


# ---------------------------------------------------------------------------
# best-effort provenance (preserved for existing non-release callers)
# ---------------------------------------------------------------------------


def _get_up_env_vars() -> Dict[str, str]:
    """Collect allow-listed, non-secret ``UP_*`` variables.

    V5 narrowed this from "every ``UP_*`` variable" to the documented release-safe
    allow-list, so a secret-bearing variable can never reach a receipt.
    """
    return filter_release_safe_env()


def _tool_versions() -> Dict[str, Any]:
    """Collect versions of the tools that materially affect results."""
    versions: Dict[str, Any] = {}

    for dist in ("carla", "ultralytics", "torch"):
        try:
            versions[dist] = importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:
            versions[dist] = None
    return versions


def _carla_version_from_env() -> Optional[str]:
    safe = filter_release_safe_env()
    return safe.get("UP_CARLA_VERSION")


def collect_provenance(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Collect best-effort provenance metadata for the current run.

    Preserved for diagnostics. Git identity is derived from the process working
    directory and omitted entirely when git is unavailable -- this is
    intentionally *not* suitable as release evidence. Use
    :func:`collect_strict_release_provenance` for that.

    Args:
        extra: Optional dictionary of extra metadata to merge in.

    Returns:
        Dictionary containing all collected provenance data.
    """
    provenance: Dict[str, Any] = {
        "schema": PROVENANCE_SCHEMA,
        "mode": "diagnostic_best_effort",
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

    # Git info (best-effort, CWD-derived)
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

    # Release-safe environment variables only (V5/NEW-203).
    up_env = _get_up_env_vars()
    if up_env:
        provenance["up_env_vars"] = up_env
        provenance["up_env_vars_policy"] = "release_safe_allowlist"

    # Merge extra metadata
    if extra:
        provenance["extra"] = extra

    return provenance


# ---------------------------------------------------------------------------
# strict release provenance (fail closed)
# ---------------------------------------------------------------------------


def _resolve_repo_root(repo_root: Any) -> Tuple[Optional[str], Optional[str]]:
    """Resolve and validate the repository root. Returns (path, error)."""
    if repo_root is None:
        return None, "no repository root supplied; refusing to infer from CWD"
    try:
        path = Path(repo_root).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        return None, f"repository root could not be resolved: {exc}"
    if not path.exists():
        return None, f"repository root does not exist: {path.as_posix()}"
    if not path.is_dir():
        return None, f"repository root is not a directory: {path.as_posix()}"
    return str(path), None


def _repo_identity(repo_root: str) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """Return (remotes, error). Remotes bind the evidence to a repository."""
    ok, out, err = _git(repo_root, "remote", "-v")
    if not ok:
        return None, err or "git remote -v failed"
    remotes: Dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] not in remotes:
            remotes[parts[0]] = parts[1]
    if not remotes:
        return None, "repository has no configured git remote"
    return remotes, None


def collect_strict_release_provenance(
    repo_root: Any,
    *,
    expected_sha: Optional[str] = None,
    require_clean: bool = True,
    expected_repo_substring: Optional[str] = None,
    require_remote: bool = True,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Collect fail-closed provenance bound to an explicit repository identity.

    Every field is required. Nothing is silently omitted: an unavailable fact is
    recorded as a failure. Returns a payload whose ``status`` is ``PASS`` only
    when every required condition holds.
    """
    failures: List[Dict[str, str]] = []
    resolved_root, root_error = _resolve_repo_root(repo_root)
    if root_error:
        failures.append({"field": "repo_root", "reason": root_error})

    git_block: Dict[str, Any] = {
        "repo_root": resolved_root,
        "commit": None,
        "branch": None,
        "detached_head": None,
        "dirty": None,
        "dirty_entries": [],
        "remotes": {},
    }

    if resolved_root:
        # git availability
        ok, out, err = _git(resolved_root, "rev-parse", "HEAD")
        if not ok:
            failures.append(
                {
                    "field": "git",
                    "reason": "git unavailable or repository is not a git work tree: "
                    + (err or out or "unknown error"),
                }
            )
        else:
            git_block["commit"] = out.strip() or None
            if not git_block["commit"]:
                failures.append({"field": "git.commit", "reason": "HEAD is empty"})

        ok, out, err = _git(resolved_root, "rev-parse", "--abbrev-ref", "HEAD")
        branch = out.strip() if ok else ""
        git_block["branch"] = branch or None
        if branch == "HEAD":
            git_block["detached_head"] = True
            if not expected_sha:
                failures.append(
                    {
                        "field": "git.branch",
                        "reason": "detached HEAD cannot be bound to a branch and no expected_sha supplied",
                    }
                )
        else:
            git_block["detached_head"] = False
            if not branch:
                failures.append({"field": "git.branch", "reason": "branch name unavailable"})

        ok, out, err = _git(resolved_root, "status", "--porcelain")
        if ok:
            entries = [line for line in out.splitlines() if line.strip()]
            git_block["dirty"] = bool(entries)
            git_block["dirty_entries"] = entries[:200]
        else:
            git_block["dirty"] = None
            failures.append(
                {"field": "git.dirty", "reason": "git status failed: " + (err or "unknown")}
            )

        if require_remote:
            remotes, remote_error = _repo_identity(resolved_root)
            if remote_error:
                failures.append({"field": "git.remotes", "reason": remote_error})
            else:
                git_block["remotes"] = remotes or {}

        # expected SHA binding
        if expected_sha:
            actual = (git_block.get("commit") or "").lower()
            wanted = str(expected_sha).lower()
            git_block["expected_sha"] = str(expected_sha)
            if actual != wanted:
                failures.append(
                    {
                        "field": "git.commit",
                        "reason": f"expected SHA {wanted} but repository HEAD is {actual or 'UNKNOWN'}",
                    }
                )

        if require_clean and git_block.get("dirty"):
            failures.append(
                {
                    "field": "git.dirty",
                    "reason": "release evidence requires a clean worktree but uncommitted changes are present",
                }
            )

        if expected_repo_substring:
            remotes = git_block.get("remotes") or {}
            haystack = " ".join(remotes.values()).lower()
            if str(expected_repo_substring).lower() not in haystack:
                failures.append(
                    {
                        "field": "git.remotes",
                        "reason": f"no git remote contains expected repository identity {expected_repo_substring!r}",
                    }
                )

    carla_version = _carla_version_from_env()
    tool_versions = _tool_versions()

    payload: Dict[str, Any] = {
        "schema": STRICT_SCHEMA,
        "mode": "strict_release",
        "status": STATUS_PASS if not failures else STATUS_FAIL,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "repo": {
            "expected_repo_substring": expected_repo_substring,
            "require_clean": require_clean,
        },
        "git": git_block,
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
        "tools": tool_versions,
        "carla": {
            "version": tool_versions.get("carla"),
            "expected_version": carla_version,
        },
        "environment": {
            "policy": "release_safe_allowlist",
            "allowlist": list(RELEASE_SAFE_ENV_ALLOWLIST),
            "captured": filter_release_safe_env(),
        },
        "failures": failures,
    }
    if extra:
        payload["extra"] = extra
    return payload


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------


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
    """Convenience function to collect and write diagnostic provenance."""
    provenance = collect_provenance(extra)
    write_provenance(out_dir, provenance)
    return provenance


def collect_and_write_strict_release_provenance(
    out_dir: str,
    repo_root: Any,
    *,
    expected_sha: Optional[str] = None,
    require_clean: bool = True,
    expected_repo_substring: Optional[str] = None,
    require_remote: bool = True,
    extra: Optional[Dict[str, Any]] = None,
    filename: str = "strict_release_provenance.json",
) -> Dict[str, Any]:
    """Collect and write strict release provenance. Writes the receipt even on
    FAIL -- a failure receipt is the evidence that the gate ran and refused.
    """
    provenance = collect_strict_release_provenance(
        repo_root,
        expected_sha=expected_sha,
        require_clean=require_clean,
        expected_repo_substring=expected_repo_substring,
        require_remote=require_remote,
        extra=extra,
    )
    out_path = Path(out_dir).expanduser().resolve()
    out_path.mkdir(parents=True, exist_ok=True)
    target = out_path / filename
    with target.open("w", encoding="utf-8") as handle:
        json.dump(provenance, handle, indent=2, sort_keys=True)
    provenance["written_to"] = str(target)
    return provenance


# CLI for testing/debugging
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Collect and display run provenance")
    ap.add_argument("--out", help="Output directory to write provenance.json")
    ap.add_argument("--json", action="store_true", help="Output as JSON (default: formatted)")
    ap.add_argument(
        "--strict-release",
        action="store_true",
        help="Collect fail-closed strict release provenance",
    )
    ap.add_argument("--repo-root", help="Repository root (required for --strict-release)")
    ap.add_argument("--expected-sha", help="Expected HEAD SHA (required for --strict-release)")
    ap.add_argument("--expect-repo", help="Substring that a git remote URL must contain")
    ap.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Do not require a clean worktree in strict release mode",
    )
    args = ap.parse_args()

    if args.strict_release:
        payload = collect_and_write_strict_release_provenance(
            args.out or ".",
            args.repo_root,
            expected_sha=args.expected_sha,
            require_clean=not args.allow_dirty,
            expected_repo_substring=args.expect_repo,
        )
        print(
            f"[run_provenance] strict status={payload['status']} "
            f"failures={len(payload['failures'])}"
        )
        raise SystemExit(0 if payload["status"] == STATUS_PASS else 1)

    prov = collect_provenance()

    if args.out:
        written = write_provenance(args.out, prov)
        print(f"Wrote provenance to: {written}")
    elif args.json:
        print(json.dumps(prov, indent=2))
    else:
        print("=== Run Provenance ===")
        print(f"Timestamp: {prov['timestamp_utc']}")
        print(f"Python: {prov['version_info'] if 'version_info' in prov else prov['python']['version_info']}")
        print(f"Platform: {prov['platform']['system']} {prov['platform']['release']}")
        if "git" in prov:
            print(f"Git: {prov['git']['commit'][:12]}... ({prov['git']['branch']})")
            if prov["git"].get("dirty"):
                print("  (working directory has uncommitted changes)")
        if "up_env_vars" in prov:
            print(f"UP_ env vars (allow-listed): {list(prov['up_env_vars'].keys())}")
        if "pip_freeze" in prov:
            print(f"Packages: {len(prov['pip_freeze'])} installed")
