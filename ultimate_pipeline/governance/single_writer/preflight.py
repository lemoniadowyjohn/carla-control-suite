"""Governed mutation pre-flight: lease acquisition + duplicate detection.

Required flow for every governed mutating entry point:
  acquire_operation() -> snapshot -> spawn_owned -> heartbeat ->
  terminal receipt -> release

No lease: DENY. Read-only session: MUTATION_DENIED_READ_ONLY_SESSION.
Duplicate live fingerprint: DUPLICATE_OPERATION_ALREADY_RUNNING.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import domains as _domains
from . import lease_store as _leases
from .os_lock import NamedMutex, read_only_session


@dataclass
class PreflightResult:
    allowed: bool
    code: str
    detail: str = ""
    lease: Optional[_leases.Lease] = None
    mutex: Optional[NamedMutex] = None


def operation_fingerprint(operation: str, roots: Dict[str, str],
                          package_or_map: str,
                          importsettings_semantic_sha: str = "",
                          extra: Optional[Dict[str, Any]] = None) -> str:
    parts: Dict[str, Any] = {
        "operation": operation,
        "engine_root": roots.get("engine_root", ""),
        "project_root": roots.get("project_root", ""),
        "content_root": roots.get("content_root", ""),
        "package_or_map": package_or_map,
        "importsettings_semantic_sha": importsettings_semantic_sha,
    }
    if extra:
        parts["extra"] = extra
    return _leases.fingerprint_operation(parts)


def acquire_operation(operation: str, roots: Dict[str, str],
                      package_or_map: str,
                      importsettings_semantic_sha: str = "",
                      timeout_ms: int = 0,
                      extra: Optional[Dict[str, Any]] = None) -> PreflightResult:
    """Attempt to acquire the single-writer lease for a mutation."""
    if read_only_session():
        return PreflightResult(False, "MUTATION_DENIED_READ_ONLY_SESSION",
                               "READ_ONLY_SESSION is set; all shared-state mutation denied")
    if operation not in _domains.OPERATION_DOMAINS:
        return PreflightResult(False, "UNKNOWN_OPERATION",
                               f"{operation} is not a governed operation")
    mutex = NamedMutex()
    acq = mutex.acquire(timeout_ms=timeout_ms)
    if not acq.acquired:
        return PreflightResult(False, "DENY_MUTEX_BUSY",
                               f"single-writer mutex held ({acq.error})")
    fp = operation_fingerprint(operation, roots, package_or_map,
                               importsettings_semantic_sha, extra)
    live = _leases.read_current()
    if live is not None:
        if _leases.lease_owner_alive(live):
            # Fingerprint first: an identical live operation is a DUPLICATE
            # even under global exclusivity (this exact branch must have
            # prevented the duplicate NoSig launch).
            if live.operation_fingerprint == fp:
                mutex.release()
                return PreflightResult(
                    False, "DUPLICATE_OPERATION_ALREADY_RUNNING",
                    f"identical live operation (run {live.run_id})")
            conflict = _domains.check_conflict(operation, live.operation)
            if conflict["conflict"]:
                mutex.release()
                return PreflightResult(
                    False, "DENY_LIVE_CONFLICT",
                    f"{conflict['reason']} (live run {live.run_id})")
        else:
            # Dead owner: never auto-reclaim here. Flag and deny; an
            # operator must run reconcile_stale() explicitly.
            live.state = "STALE_RECONCILIATION_REQUIRED"
            mutex.release()
            return PreflightResult(
                False, "DENY_STALE_RECONCILIATION_REQUIRED",
                f"previous owner dead (run {live.run_id}); explicit reconcile required")
    if acq.abandoned:
        mutex.release()
        return PreflightResult(
            False, "DENY_STALE_RECONCILIATION_REQUIRED",
            "mutex was abandoned by a dead owner; explicit reconcile required")
    lease = _leases.new_lease(
        operation, _domains.domains_for(operation), fp, acq.namespace,
        roots.get("engine_root", ""), roots.get("project_root", ""),
        roots.get("content_root", ""))
    # Publish AFTER the mutex is held and all checks passed.
    _leases._write_current(lease)
    return PreflightResult(True, "ACQUIRED", f"run {lease.run_id}",
                           lease, mutex)


def release_operation(lease: _leases.Lease, mutex: NamedMutex,
                      terminal_state: str) -> Dict[str, Any]:
    _leases.release(lease, terminal_state)
    mutex.release()
    return {"run_id": lease.run_id, "terminal_state": terminal_state}


def snapshot_configuration(paths: Dict[str, str]) -> Dict[str, Any]:
    """SHA-bind every artifact a governed mutation depends on."""
    out: Dict[str, Any] = {}
    for key, path in paths.items():
        p = Path(path)
        try:
            h = hashlib.sha256()
            with p.open("rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            out[key] = {"path": str(p), "sha256": h.hexdigest(),
                        "bytes": p.stat().st_size}
        except OSError as e:
            out[key] = {"path": str(p), "error": str(e)}
    return out


def configuration_mutated(baseline: Dict[str, Any],
                          current: Dict[str, Any]) -> List[str]:
    changed = []
    for key, base in baseline.items():
        cur = current.get(key, {})
        if base.get("sha256") != cur.get("sha256"):
            changed.append(key)
    return changed
