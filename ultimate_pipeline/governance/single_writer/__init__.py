"""Single-writer control plane for governed CARLA mutations (Batch 17).

The Win32 named mutex in :mod:`os_lock` is the machine-wide authority for CARLA
asset mutation; lease JSON is evidence. The Git mutation layer is separate and
portable: :mod:`common_git_lock` governs repository-global shared Git metadata,
:mod:`worktree_lock` governs per-worktree mutation, and both resolve their
authority in the common Git directory via :mod:`lock_paths`.

Process liveness and process-start identity for both come from
:mod:`process_identity`, whose invariant is that UNKNOWN is never proof of death.
"""
from . import domains, exit_codes, handoff, job_supervision, lease_store
from . import os_lock, preflight, run_settings, ungoverned_detector
from . import common_git_lock, lock_paths, process_identity, worktree_lock

__all__ = [
    "domains",
    "exit_codes",
    "handoff",
    "job_supervision",
    "lease_store",
    "lock_paths",
    "os_lock",
    "preflight",
    "process_identity",
    "run_settings",
    "ungoverned_detector",
    "worktree_lock",
    "common_git_lock",
]