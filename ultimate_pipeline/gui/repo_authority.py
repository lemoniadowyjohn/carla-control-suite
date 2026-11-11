"""Production mutation authority for GUI writes inside a Git worktree.

The GUI has no private write path. Any write whose destination is inside a
Git worktree must hold the same per-worktree lease as the CLI:

* ``read_only_session()`` denies immediately;
* a lease held by another live process refuses, never steals;
* an unreadable/unknown lease state refuses (``MalformedLeaseError`` and
  ``RuntimeError`` both become :class:`RepositoryMutationRefused`);
* the lease is released only after the outermost write completes.

Writes outside a repository are not governed by this module; callers that
target temp directories, user exports or other non-repo locations keep their
existing behaviour. The gate is deliberately re-entrant so one GUI action can
write several repository files while holding one lease.
"""

from __future__ import annotations

import threading
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Iterator

from ultimate_pipeline.governance.single_writer.os_lock import read_only_session
from ultimate_pipeline.governance.single_writer.worktree_lock import (
    DEFAULT_LEASE_MINUTES,
    WorktreeLease,
    acquire_worktree_lease,
    release_worktree_lease,
)

__all__ = [
    "RepositoryAuthority",
    "RepositoryMutationRefused",
    "repository_write",
    "repository_authority",
]


class RepositoryMutationRefused(RuntimeError):
    """A GUI write inside a repository was refused by mutation authority."""


def find_repository_root(target: str | Path) -> Path | None:
    """Return the worktree root containing ``target``, or ``None``.

    ``target`` may be an existing file, an existing directory, or a file that
    does not exist yet. Resolution is by directory ancestry, never by cwd, so
    an export to an unrelated directory is not treated as a repo write.
    """
    path = Path(target).resolve()
    start = path if path.is_dir() else path.parent
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


class RepositoryAuthority:
    """Re-entrant holder of one worktree mutation lease."""

    def __init__(self, lease_minutes: int = DEFAULT_LEASE_MINUTES) -> None:
        self._lease_minutes = int(lease_minutes)
        self._lock = threading.RLock()
        self._depth = 0
        self._root: Path | None = None
        self._lease: WorktreeLease | None = None

    @property
    def held(self) -> bool:
        with self._lock:
            return self._lease is not None

    @property
    def worktree_root(self) -> Path | None:
        with self._lock:
            return self._root

    @property
    def lease_id(self) -> str | None:
        with self._lock:
            return self._lease.lease_id if self._lease is not None else None

    def acquire(self, purpose: str = "GUI repository write",
                root: str | Path | None = None) -> WorktreeLease:
        """Acquire (or count a re-entrant use of) the worktree lease."""
        with self._lock:
            if self._depth:
                self._depth += 1
                assert self._lease is not None
                return self._lease

            if read_only_session():
                raise RepositoryMutationRefused(
                    "BLOCKED_READ_ONLY_SESSION: refusing GUI repository write"
                )

            resolved = (Path(root).resolve() if root is not None
                        else find_repository_root(Path.cwd()))
            if resolved is None:
                raise RepositoryMutationRefused(
                    f"BLOCKED_NOT_A_REPOSITORY: no worktree root for "
                    f"{root if root is not None else Path.cwd()}"
                )
            try:
                lease = acquire_worktree_lease(
                    resolved, purpose=purpose, lease_minutes=self._lease_minutes
                )
            except Exception as exc:
                raise RepositoryMutationRefused(
                    f"BLOCKED_MUTATION_AUTHORITY: {exc}"
                ) from exc

            self._root = resolved
            self._lease = lease
            self._depth = 1
            return lease

    def release(self) -> None:
        """Release the lease when the outermost write finishes."""
        with self._lock:
            if not self._depth:
                return
            self._depth -= 1
            if self._depth:
                return
            lease, root = self._lease, self._root
            self._lease = None
            self._root = None

        if lease is None or root is None:
            return
        try:
            release_worktree_lease(
                root, owner_token=lease.owner_token, lease_id=lease.lease_id
            )
        except Exception as exc:
            raise RepositoryMutationRefused(
                f"BLOCKED_LEASE_RELEASE: {exc}"
            ) from exc

    @contextmanager
    def write(self, target: str | Path,
              purpose: str = "GUI repository write") -> Iterator[Path | None]:
        """Guard a write to ``target``; no-op outside a Git worktree."""
        root = find_repository_root(target)
        if root is None:
            yield None
            return
        self.acquire(purpose, root=root)
        try:
            yield root
        except BaseException:
            try:
                self.release()
            except RepositoryMutationRefused:
                pass
            raise
        else:
            self.release()


_authority = RepositoryAuthority()


def repository_authority() -> RepositoryAuthority:
    """Process-wide authority shared by every GUI persistence path."""
    return _authority


def repository_write(target: str | Path,
                     purpose: str = "GUI repository write",
                     ) -> AbstractContextManager[Path | None]:
    """Module-level convenience wrapper around the shared authority."""
    return _authority.write(target, purpose=purpose)
