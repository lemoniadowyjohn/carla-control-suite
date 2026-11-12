"""V98 follow-up controls for PR #37 lease and fencing defects."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from ultimate_pipeline.governance.single_writer import lock_paths
from ultimate_pipeline.governance.single_writer import worktree_lock as wl


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=v98@example.invalid", "-c",
         "user.name=V98 test", "-c", "init.defaultBranch=main", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )


def _linked(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", cwd=repo)
    _git("commit", "--allow-empty", "-m", "fixture", cwd=repo)
    first, second = tmp_path / "first", tmp_path / "second"
    _git("worktree", "add", str(first), "-b", "first", cwd=repo)
    _git("worktree", "add", str(second), "-b", "second", cwd=repo)
    return repo, first, second


def _expired_lease(root: Path) -> wl.WorktreeLease:
    lease = wl.WorktreeLease(
        worktree_root=str(root.resolve()), worktree_name=root.name,
        holder_pid=2_000_000_000, holder_start_identity="dead-fixture",
        expires_at="2000-01-01T00:00:00Z",
    )
    wl._write_lease(lease)
    return lease


def test_malformed_claim_is_reported_and_does_not_abort_other_expired_scope(
    tmp_path, monkeypatch
):
    repo, first, second = _linked(tmp_path)
    lease_a = _expired_lease(first)
    lease_b = _expired_lease(second)
    claim = wl._generation_claim_path(first)
    claim.write_bytes(b"not-json")
    os.utime(claim, (time.time() - 2, time.time() - 2))
    monkeypatch.setattr(
        wl.process_identity, "probe_liveness",
        lambda _pid: SimpleNamespace(reclaimable=True, alive=False,
                                     start_identity=None, detail="dead fixture"),
    )

    report = wl.cleanup_expired_leases_detailed(repo)

    by_root = {Path(entry.worktree_root): entry for entry in report.entries}
    assert report.removed_count == 1
    assert report.overall_ok is False
    assert by_root[first.resolve()].status == "LOCKED_UNKNOWN"
    assert "malformed generation claim" in by_root[first.resolve()].detail
    assert by_root[second.resolve()].status == "REMOVED"
    assert wl._worktree_lease_path(first).exists()
    assert not wl._worktree_lease_path(second).exists()
    assert claim.read_bytes() == b"not-json"
    assert lease_a.lease_id != lease_b.lease_id
    assert first.is_dir() and second.is_dir()


def test_recovery_parent_directory_is_durable_before_exact_byte_claim(
    tmp_path, monkeypatch
):
    repo, first, _second = _linked(tmp_path)
    lease_path = lock_paths.worktree_lease_path(repo, first)
    original = b"{malformed original bytes}"
    lease_path.write_bytes(original)
    events: list[tuple[str, Path]] = []
    real_sync = wl._fsync_directory_required
    real_claim = wl._claim_lease_path

    def sync(directory: Path) -> None:
        events.append(("sync", Path(directory)))
        real_sync(directory)

    def claim(path, tag, expect):
        events.append(("claim", Path(path)))
        audit_dir = lease_path.parent / "recovery_audit"
        receipts = [json.loads(p.read_text(encoding="utf-8"))
                    for p in audit_dir.glob("*.json")]
        assert any(
            receipt.get("phase") == "INTENT"
            and receipt.get("removed_sha256") == hashlib.sha256(original).hexdigest()
            for receipt in receipts
        )
        assert ("sync", lease_path.parent) in events
        assert ("sync", audit_dir) in events
        return real_claim(path, tag, expect)

    monkeypatch.setattr(wl, "_fsync_directory_required", sync)
    monkeypatch.setattr(wl, "_claim_lease_path", claim)
    result = wl.recover_malformed_lease(repo, first, "operator", "fixture")

    assert result["recovered"] is True
    assert Path(result["evidence_copy"]).read_bytes() == original
    assert json.loads(Path(result["audit_path"]).read_text())["phase"] == "COMPLETE"
    assert not lease_path.exists()
    assert events.index(("sync", lease_path.parent)) < events.index(("claim", lease_path))


def test_recovery_parent_fsync_failure_preserves_original_lease(tmp_path, monkeypatch):
    repo, first, _second = _linked(tmp_path)
    lease_path = lock_paths.worktree_lease_path(repo, first)
    original = b"{keep-original-on-fsync-failure}"
    lease_path.write_bytes(original)
    claim_attempted = False

    def fail_sync(directory: Path) -> None:
        if Path(directory) == lease_path.parent:
            raise wl.RecoveryDurabilityError("LOCKED_UNKNOWN: injected fsync failure")

    real_claim = wl._claim_lease_path

    def observe_claim(*args, **kwargs):
        nonlocal claim_attempted
        claim_attempted = True
        return real_claim(*args, **kwargs)

    monkeypatch.setattr(wl, "_fsync_directory_required", fail_sync)
    monkeypatch.setattr(wl, "_claim_lease_path", observe_claim)
    with pytest.raises(wl.RecoveryDurabilityError, match="injected fsync failure"):
        wl.recover_malformed_lease(repo, first, "operator", "fixture")
    assert not claim_attempted
    assert lease_path.read_bytes() == original


def test_exclusive_fallback_never_exposes_empty_or_partial_destination(tmp_path, monkeypatch):
    destination = tmp_path / "lease.json"
    payload = b'{"status":"complete","generation":7}'
    original_fdopen = os.fdopen
    opened = threading.Event()
    allow_write = threading.Event()
    errors: list[BaseException] = []

    class GateFile:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            self.wrapped.__enter__()
            opened.set()
            assert allow_write.wait(5), "test did not release writer barrier"
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def write(self, data):
            return self.wrapped.write(data)

        def flush(self):
            return self.wrapped.flush()

        def fileno(self):
            return self.wrapped.fileno()

    monkeypatch.setattr(wl.os, "fdopen", lambda fd, mode: GateFile(original_fdopen(fd, mode)))

    def writer():
        try:
            wl._publish_exclusive_fallback_bytes(destination, payload)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        assert opened.wait(5), "fallback writer did not reach its publication write"
        if destination.exists():
            assert destination.read_bytes() == payload, (
                "a concurrent reader observed an empty/partial lease publication"
            )
    finally:
        allow_write.set()
        thread.join(5)
    assert not thread.is_alive()
    assert not errors
    assert destination.read_bytes() == payload


def test_exclusive_fallback_fails_closed_when_atomic_link_is_unsupported(tmp_path, monkeypatch):
    destination = tmp_path / "lease.json"

    def fail_link(*_args):
        raise OSError("hard links are disabled")

    monkeypatch.setattr(wl.os, "link", fail_link)
    with pytest.raises(RuntimeError, match="UNSUPPORTED_FILESYSTEM"):
        wl._publish_exclusive_fallback_bytes(destination, b"complete")
    assert not destination.exists()


def test_generation_marker_and_ledger_coloss_cannot_reuse_retired_generation(
    tmp_path
):
    root = tmp_path / "generation"
    root.mkdir()
    _git("init", cwd=root)
    _git("commit", "--allow-empty", "-m", "fixture", cwd=root)
    lease = wl.acquire_worktree_lease(root, purpose="high-water")
    generation = lease.generation
    assert wl.release_worktree_lease(root, lease.owner_token, lease.lease_id)
    wl._ledger_path(root).unlink()
    wl._generation_marker_path(root).unlink()

    next_lease = wl.acquire_worktree_lease(root, purpose="must-not-reuse")
    try:
        assert next_lease.generation > generation
    finally:
        wl.release_worktree_lease(root, next_lease.owner_token, next_lease.lease_id)
