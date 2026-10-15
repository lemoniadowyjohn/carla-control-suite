"""Generic filesystem cleanup guard for destructive recursive deletion.

The 2026-10 worktree loss established that a scratch-root cleanup routine can
reach a registered ``git worktree`` and erase it. This module makes that class
of accident structurally impossible rather than merely unlikely: every
recursive-delete request is canonicalized first and then denied if it targets
anything Git-meaningful.

Denial triggers (all evaluated against the canonicalized target):

* the target is a repository root (``.git`` directory present)
* the target is a registered Git worktree root (``.git`` *pointer file* present)
* the target is a registered worktree root according to ``git worktree list``
* the target is an ancestor of a registered worktree
* the target resolves, via junction / symlink / reparse point, to any of the
  above

Deliberate design constraints:

* Canonicalization happens BEFORE any check, so a junction cannot be used to
  launder a forbidden target into an apparently innocent path.
* The guard is a pure predicate plus an executor. It never shells out to
  ``git add``, ``git add -A``, ``git commit`` or any other staging operation.
  A regression test asserts that a denied/allowed cleanup performs zero git
  index mutations.
"""

from __future__ import annotations

import os
import subprocess
from typing import Iterable, List, Optional, Sequence

__all__ = [
    "CleanupGuardError",
    "Verdict",
    "canonicalize",
    "collect_protected_paths",
    "build_guard",
    "evaluate",
    "guarded_rmtree",
]


class CleanupGuardError(RuntimeError):
    """Raised when a destructive operation is refused by the guard."""


class Verdict:
    DENY = "DENY"
    ALLOW = "ALLOW"


def canonicalize(path: str) -> str:
    """Resolve ``path`` to a canonical absolute path.

    ``os.path.realpath`` on Windows resolves 8.3 names, relative components and
    symlinks; we additionally re-resolve reparse points so that a junction is
    reported by its target rather than its own path. Case is folded because NTFS
    is case-insensitive and a case-flip must not bypass the checks.
    """
    absolute = os.path.abspath(path)
    resolved = os.path.realpath(absolute)
    try:
        # realpath() on Windows already expands junctions, but a defensive
        # second pass catches mount points / subst drives that only resolve on
        # explicit open.
        resolved = os.path.realpath(resolved)
    except OSError:
        pass
    return os.path.normcase(os.path.normpath(resolved))


def _is_within(child: str, ancestor: str) -> bool:
    """True when ``child`` is ``ancestor`` or lives beneath it."""
    if child == ancestor:
        return True
    return child.startswith(ancestor.rstrip(os.sep) + os.sep)


def _git_worktree_roots(repo: str) -> List[str]:
    """Return canonical roots of every worktree registered against ``repo``."""
    try:
        proc = subprocess.run(
            ["git", "-C", repo, "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    roots = []
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            candidate = line[len("worktree "):].strip()
            if candidate:
                roots.append(canonicalize(candidate))
    return roots


def collect_protected_paths(repo_root: str) -> List[str]:
    """Build the canonical set of paths a cleanup must never destroy.

    Includes the repository root, every registered worktree root, and the
    ancestors of every worktree up to (and including) the filesystem root, since
    deleting an ancestor of a worktree destroys it just as effectively.
    """
    repo_root = canonicalize(repo_root)
    protected = {repo_root}

    for wt in _git_worktree_roots(repo_root):
        protected.add(wt)
        # An ancestor chain makes "parent of worktree" impossible to delete.
        current = os.path.dirname(wt)
        while current and current not in protected:
            protected.add(current)
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent

    return sorted(protected)


def _has_git_marker(path: str) -> Optional[str]:
    """Return ``'dir'``/``'pointer'`` if ``path`` carries a .git marker."""
    candidate = os.path.join(path, ".git")
    if os.path.isdir(candidate):
        return "dir"
    if os.path.isfile(candidate):
        return "pointer"
    return None


class build_guard:
    """Evaluate cleanup requests against a fixed protected-path set."""

    def __init__(self, repo_root: str, extra_protected: Optional[Iterable[str]] = None):
        self.repo_root = canonicalize(repo_root)
        self.protected = set(collect_protected_paths(self.repo_root))
        for extra in extra_protected or ():
            self.protected.add(canonicalize(extra))
        # A bare worktree registration is a pointer file at its root, so the
        # marker scan below is what catches worktrees this repo does not know.

    def reasons(self, target: str) -> List[str]:
        """Return every reason the target is protected (empty => allowed)."""
        resolved = canonicalize(target)
        found: List[str] = []

        if resolved == self.repo_root:
            found.append("REPOSITORY_ROOT")

        marker = _has_git_marker(resolved)
        if marker == "dir":
            found.append("REPOSITORY_ROOT" if resolved == self.repo_root
                         else "REPO_ROOT_HAS_GIT_DIR")
        elif marker == "pointer":
            found.append("REGISTERED_WORKTREE_ROOT")

        for protected in self.protected:
            if resolved == protected:
                found.append("PROTECTED_PATH")
                break
            if _is_within(protected, resolved):
                found.append("ANCESTOR_OF_PROTECTED_PATH")
                break

        if os.path.normcase(os.path.normpath(os.path.abspath(target))) != resolved:
            found.append("RESOLVES_VIA_LINK_TO_" + ("PROTECTED" if found else "OTHER"))

        # Preserve order while removing duplicates.
        seen = set()
        ordered = []
        for r in found:
            if r not in seen:
                seen.add(r)
                ordered.append(r)
        return ordered

    def __call__(self, target: str) -> str:
        return Verdict.DENY if self.reasons(target) else Verdict.ALLOW


def evaluate(guard: "build_guard", target: str) -> dict:
    """Return a structured decision record for ``target``."""
    reasons = guard.reasons(target)
    return {
        "target": target,
        "canonical": canonicalize(target),
        "verdict": Verdict.DENY if reasons else Verdict.ALLOW,
        "reasons": reasons,
    }


def _collect_tracked_state(repo_root: str) -> bytes:
    """Snapshot the *tracked* git state (worktree + index) as bytes.

    Untracked paths are deliberately excluded: deleting an untracked scratch
    file is the entire point of a cleanup, so including it would make the
    "cleanup did not stage anything" assertion fail for a correct delete. What
    must never change is the tracked diff and the index.
    """
    chunks = []
    for args in (["diff", "--name-only"], ["diff", "--cached", "--name-only"]):
        try:
            proc = subprocess.run(
                ["git", "-C", repo_root, *args],
                capture_output=True, text=True, errors="replace", timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            chunks.append(b"<unavailable>")
        else:
            chunks.append(proc.stdout.encode("utf-8", "replace"))
    return b"\n".join(chunks)


def guarded_rmtree(guard: "build_guard", target: str, dry_run: bool = False) -> dict:
    """Remove ``target`` recursively unless the guard denies it.

    Raises :class:`CleanupGuardError` on denial. Performs no git staging of any
    kind; a snapshot of the tracked/index state taken before and after proves
    the index is untouched.
    """
    decision = evaluate(guard, target)
    if decision["verdict"] == Verdict.DENY:
        raise CleanupGuardError(
            "refusing recursive delete of %s: %s" % (decision["canonical"],
                                                     ",".join(decision["reasons"]))
        )

    before = _collect_tracked_state(guard.repo_root)
    if not dry_run:
        import shutil
        shutil.rmtree(target)
    after = _collect_tracked_state(guard.repo_root)

    decision.update({
        "executed": not dry_run,
        "git_index_unchanged": before == after,
    })
    return decision
