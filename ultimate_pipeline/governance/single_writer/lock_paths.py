"""Canonical locations for lock authority within a Git repository.

Two distinct authorities live under one repository's **common** Git directory
(``git rev-parse --git-common-dir``), never under a per-checkout ``.git``:

``<common>/.agent_locks/common_git_lock.json``
    repository-global authority for mutations of *shared* Git metadata
    (refs, objects, config, packed-refs, worktree registry).

``<common>/.agent_locks/worktree_leases/<digest>.lease.json``
    per-worktree authority for files inside one specific worktree.

Why the common directory
------------------------
In a linked worktree ``.git`` is a regular *file* containing a ``gitdir:``
pointer, not a directory. The previous code did ``repo_root/".git"`` and then
appended to it, which raised ``NotADirectoryError`` for every linked worktree.
Merely avoiding the crash would be worse than useless: each worktree would
compute its own lock path and the 'shared' lock would not be shared at all.

Per-worktree identity
---------------------
Worktree identity is a SHA-256 digest of the canonical absolute worktree path.
The previous code flattened the path into a filename by replacing ``:``, ``\\``
and ``/`` with ``_``, which collides: ``C:\\a\\b`` and ``C:\\a_b`` both produced
``C_a_b``. A digest cannot collide across distinct canonical paths, and the
human-readable path is retained inside the file for diagnosis.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

AGENT_LOCKS_DIRNAME = ".agent_locks"
WORKTREE_LEASES_DIRNAME = "worktree_leases"
COMMON_GIT_LOCK_FILENAME = "common_git_lock.json"

_GIT_TIMEOUT_S = 30


def _not_a_repository(path: Path) -> RuntimeError:
    return RuntimeError(f"Not a Git repository: {path}")


def resolve_git_common_dir(repo_root: Path) -> Path:
    """Return the absolute, canonical common Git directory for ``repo_root``.

    Resolution order:

    1. ``git rev-parse --git-common-dir`` -- the authority, because it is what
       Git itself uses and it answers identically from a main checkout and from
       every linked worktree.
    2. A pure-Python fallback that reads the ``gitdir:`` pointer out of a
       linked worktree's ``.git`` *file* and strips the ``/worktrees/<name>``
       suffix. This keeps the module usable where git is not on PATH.

    Raises RuntimeError when the path is not inside a repository at all.
    """
    repo_root = Path(repo_root).resolve()
    if not repo_root.exists():
        raise _not_a_repository(repo_root)

    common = _resolve_via_git(repo_root)
    if common is not None:
        return common

    common = _resolve_via_pointer(repo_root)
    if common is not None:
        return common

    raise _not_a_repository(repo_root)


def _resolve_via_git(repo_root: Path) -> Path | None:
    """Ask Git itself. Returns None when git is unusable or disagrees."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    raw = (result.stdout or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        # Git reports the common dir relative to the cwd it was invoked in.
        candidate = repo_root / candidate
    try:
        return candidate.resolve()
    except OSError:
        return None


def _resolve_via_pointer(repo_root: Path) -> Path | None:
    """Follow a linked worktree's ``gitdir:`` file back to the common dir."""
    dot_git = repo_root / ".git"
    if dot_git.is_dir():
        return dot_git.resolve()
    if not dot_git.is_file():
        return None
    try:
        text = dot_git.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text.lower().startswith("gitdir:"):
        return None
    target = Path(text.split(":", 1)[1].strip())
    if not target.is_absolute():
        target = repo_root / target
    try:
        target = target.resolve()
    except OSError:
        return None
    # <common>/worktrees/<name> -> <common>
    if target.parent.name == "worktrees" and target.parent.parent.name == ".git":
        return target.parent.parent
    return None


def agent_locks_dir(repo_root: Path) -> Path:
    """``<common Git dir>/.agent_locks``, created on demand."""
    path = resolve_git_common_dir(repo_root) / AGENT_LOCKS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def common_git_lock_path(repo_root: Path) -> Path:
    """Path of the repository-global shared-Git-metadata lock."""
    return agent_locks_dir(repo_root) / COMMON_GIT_LOCK_FILENAME


def worktree_leases_dir(repo_root: Path) -> Path:
    """Directory holding per-worktree leases, anchored in the common Git dir."""
    path = agent_locks_dir(repo_root) / WORKTREE_LEASES_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def worktree_identity(worktree_root: Path) -> str:
    """Collision-safe identity for a worktree: SHA-256 of its canonical path.

    Digesting the canonical absolute path means two different worktrees can
    never share a lease file, which the previous flattening scheme could not
    guarantee.
    """
    canonical = str(Path(worktree_root).resolve())
    normalised = os.path.normcase(canonical)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def worktree_lease_path(repo_root: Path, worktree_root: Path) -> Path:
    """Lease file for one worktree, inside the repository-global namespace."""
    digest = worktree_identity(worktree_root)
    return worktree_leases_dir(repo_root) / f"{digest}.lease.json"


def describe_worktree(worktree_root: Path) -> str:
    """Human-readable worktree label, safe for a filename."""
    resolved = Path(worktree_root).resolve()
    label = str(resolved).replace(":", "").replace("\\", "_").replace("/", "_").strip("_")
    return label or "worktree"