"""Deterministic F1 lease-claim, cleanup and recovery regression controls."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from ultimate_pipeline.governance.single_writer import lock_paths


_OVERRIDE = os.environ.get("WORKTREE_LOCK_MODULE_PATH")
_MODULE_NAME = "ultimate_pipeline.governance.single_writer.worktree_lock"
if _OVERRIDE:
    _spec = importlib.util.spec_from_file_location(_MODULE_NAME, _OVERRIDE)
    assert _spec is not None and _spec.loader is not None
    wl = importlib.util.module_from_spec(_spec)
    sys.modules[_MODULE_NAME] = wl
    _spec.loader.exec_module(wl)
else:
    from ultimate_pipeline.governance.single_writer import worktree_lock as wl


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=test@example.invalid", "-c", "user.name=F1 Test",
         "-c", "init.defaultBranch=main", *args],
        cwd=str(cwd), capture_output=True, text=True, check=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git("init", cwd=root)
    _git("commit", "--allow-empty", "-m", "init", cwd=root)
    return root


def _lease_path(root: Path) -> Path:
    return wl._worktree_lease_path(root)


def test_t1_renew_holds_claim_against_nested_mutation(repo: Path, monkeypatch):
    lease = wl.acquire_worktree_lease(repo, purpose="T1")
    path = _lease_path(repo)
    original_claim = wl._generation_claim
    monkeypatch.setattr(
        wl,
        "_generation_claim",
        lambda root, **kwargs: original_claim(root, timeout_s=0.02),
    )

    nested_outcomes: list[object] = []
    for nested_action, lease_minutes in (("acquire", 360), ("release", 480)):
        previous_expiry = wl._read_lease(repo).expires_at
        outcome: list[object] = []
        original_write = wl._write_payload
        entered = False

        def nested_write(target: Path, payload: dict):
            nonlocal entered
            if target == path and not entered:
                entered = True
                try:
                    if nested_action == "acquire":
                        wl.acquire_worktree_lease(repo, purpose="nested acquire")
                    else:
                        wl.release_worktree_lease(
                            repo, lease.owner_token, lease.lease_id
                        )
                except RuntimeError as exc:
                    outcome.append(exc)
                else:
                    outcome.append("nested mutation unexpectedly succeeded")
            return original_write(target, payload)

        monkeypatch.setattr(wl, "_write_payload", nested_write)
        renewed = wl.renew_worktree_lease(
            repo, lease.owner_token, lease.lease_id, lease_minutes=lease_minutes
        )
        assert outcome
        nested_outcomes.append(outcome[0])
        current = wl._read_lease(repo)
        assert current is not None
        assert current.lease_id == lease.lease_id == renewed.lease_id
        assert current.generation == lease.generation == renewed.generation
        assert current.expires_at > previous_expiry
        monkeypatch.setattr(wl, "_write_payload", original_write)

    assert all(isinstance(outcome, RuntimeError) for outcome in nested_outcomes)
    assert all("LOCKED_UNKNOWN" in str(outcome) for outcome in nested_outcomes)
    wl.release_worktree_lease(repo, lease.owner_token, lease.lease_id)


def test_t2_release_racing_a_validated_renewal_does_not_resurrect(repo: Path, monkeypatch):
    lease = wl.acquire_worktree_lease(repo, purpose="T2")
    path = _lease_path(repo)
    in_write = threading.Event()
    allow_write = threading.Event()
    release_attempted = threading.Event()
    outcomes: dict[str, object] = {}
    original_write = wl._write_payload
    original_claim = wl._generation_claim

    def observed_claim(root: Path, **kwargs):
        if threading.current_thread().name == "release-worker":
            release_attempted.set()
        return original_claim(root, **kwargs)

    def gated_write(target: Path, payload: dict):
        if target == path and threading.current_thread().name == "renew-worker":
            in_write.set()
            assert allow_write.wait(5)
        return original_write(target, payload)

    monkeypatch.setattr(wl, "_generation_claim", observed_claim)
    monkeypatch.setattr(wl, "_write_payload", gated_write)

    def renew():
        try:
            wl.renew_worktree_lease(repo, lease.owner_token, lease.lease_id)
        except Exception as exc:
            outcomes["renew_error"] = exc

    def release():
        try:
            outcomes["released"] = wl.release_worktree_lease(
                repo, lease.owner_token, lease.lease_id
            )
        except Exception as exc:
            outcomes["release_error"] = exc

    a = threading.Thread(target=renew, name="renew-worker")
    a.start()
    assert in_write.wait(5)
    renewal_claimed = wl._generation_claim_path(repo).exists()
    b = threading.Thread(target=release, name="release-worker")
    b.start()
    assert release_attempted.wait(5)
    allow_write.set()
    a.join(10)
    b.join(10)
    assert not a.is_alive() and not b.is_alive()
    assert renewal_claimed, "renewal must hold the claim across its publication boundary"
    assert "renew_error" not in outcomes, outcomes.get("renew_error")
    assert "release_error" not in outcomes, outcomes.get("release_error")
    assert outcomes["released"] is True
    assert not path.exists(), "released lease must not be resurrected by the stale writer"
    with pytest.raises(RuntimeError):
        wl.renew_worktree_lease(repo, lease.owner_token, lease.lease_id)
    assert not path.exists()


def test_t3_successor_bytes_survive_renewal_at_publication_boundary(
    repo: Path, monkeypatch
):
    old = wl.acquire_worktree_lease(repo, purpose="T3-old")
    path = _lease_path(repo)
    original_write = wl._write_payload
    original_claim = wl._generation_claim
    nested: dict[str, object] = {}
    entered = False

    monkeypatch.setattr(
        wl,
        "_generation_claim",
        lambda root, **kwargs: original_claim(root, timeout_s=0.02),
    )
    monkeypatch.setattr(wl, "reclaim_decision", lambda _lease: (True, "injected dead owner"))

    def replace_during_renewal(target: Path, payload: dict):
        nonlocal entered
        if target == path and not entered:
            entered = True
            try:
                nested["successor"] = wl.acquire_worktree_lease(
                    repo, purpose="T3-successor"
                )
                nested["bytes"] = path.read_bytes()
            except RuntimeError as exc:
                nested["error"] = exc
        return original_write(target, payload)

    monkeypatch.setattr(wl, "_write_payload", replace_during_renewal)
    renewed = wl.renew_worktree_lease(repo, old.owner_token, old.lease_id)
    assert renewed.lease_id == old.lease_id
    if "successor" in nested:
        assert path.read_bytes() == nested["bytes"], "renewal overwrote a claimed successor"
        successor = nested["successor"]
    else:
        assert "LOCKED_UNKNOWN" in str(nested.get("error"))
        successor = wl.acquire_worktree_lease(repo, purpose="T3-successor-after-renew")

    before = path.read_bytes()
    with pytest.raises(RuntimeError):
        wl.renew_worktree_lease(repo, old.owner_token, old.lease_id)
    assert path.read_bytes() == before
    wl.release_worktree_lease(repo, successor.owner_token, successor.lease_id)


def test_t4_cleanup_rechecks_a_renewed_record_under_claim(repo: Path, monkeypatch):
    lease = wl.WorktreeLease(
        worktree_root=str(repo.resolve()), worktree_name=repo.name,
        holder_pid=99999999, generation=1, expires_at="2020-01-01T00:00:00Z",
    )
    wl._write_lease(lease)
    path = _lease_path(repo)
    stale = wl._read_lease(repo)
    assert stale is not None and stale.is_expired()
    renewed_record = json.loads(path.read_text(encoding="utf-8"))
    renewed_record["expires_at"] = "2999-01-01T00:00:00Z"
    path.write_text(json.dumps(renewed_record), encoding="utf-8")
    successor_bytes = path.read_bytes()

    if hasattr(wl, "_iter_worktree_leases"):
        monkeypatch.setattr(wl, "_iter_worktree_leases", lambda _root: iter([(path, stale)]))
    else:
        monkeypatch.setattr(wl, "list_worktree_leases", lambda _root: [stale])
    monkeypatch.setattr(wl, "reclaim_decision", lambda _lease: (True, "injected dead owner"))

    assert wl.cleanup_expired_leases(repo) == 0
    assert path.read_bytes() == successor_bytes


def test_t5_restore_never_overwrites_a_successor(repo: Path, monkeypatch):
    path = _lease_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    original = b"old lease bytes"
    successor = b"successor lease bytes"
    path.write_bytes(original)
    original_read = Path.read_bytes
    injected = False

    def inject_successor(tomb: Path) -> bytes:
        nonlocal injected
        raw = original_read(tomb)
        if not injected and tomb.name.endswith(".tombstone"):
            injected = True
            path.write_bytes(successor)
        return raw

    monkeypatch.setattr(Path, "read_bytes", inject_successor)
    reclaimed, tomb = wl._claim_by_rename(repo, "T5", lambda _raw: False)
    assert (reclaimed, tomb) == (False, None)
    assert path.read_bytes() == successor
    orphaned = list(path.parent.glob(f"{path.name}.T5.*.orphaned"))
    assert len(orphaned) == 1
    assert original_read(orphaned[0]) == original


def test_t6_malformed_recovery_only_removes_the_bytes_it_audited(
    repo: Path, monkeypatch
):
    path = _lease_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"{ malformed original")
    changed = b"{ replacement malformed bytes"
    original_claim = wl._claim_by_rename

    def replace_before_claim(root: Path, tag: str, expect):
        if tag == "recover":
            path.write_bytes(changed)
        return original_claim(root, tag, expect)

    monkeypatch.setattr(wl, "_claim_by_rename", replace_before_claim)
    record = wl.recover_malformed_lease(repo, repo, "operator", "T6 injection")
    assert record["recovered"] is False
    assert path.read_bytes() == changed


def test_r1_restore_error_is_visible_and_keeps_tombstone(repo: Path, monkeypatch):
    path = _lease_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    original = b"{ malformed but preserved"
    path.write_bytes(original)

    def deny_restore(_path, _payload):
        raise PermissionError("injected Windows sharing denial")

    monkeypatch.setattr(wl, "_publish_exclusive", deny_restore)
    with pytest.raises(RuntimeError, match="recovery copy retained"):
        wl._claim_by_rename(repo, "R1", lambda _raw: False)
    assert not path.exists()
    tombstones = list(path.parent.glob(f"{path.name}.R1.*.tombstone"))
    assert len(tombstones) == 1
    assert tombstones[0].read_bytes() == original


def test_r4_write_helpers_cannot_replace_a_published_owner(repo: Path):
    owner = wl.acquire_worktree_lease(repo, purpose="R4 owner")
    path = _lease_path(repo)
    before = path.read_bytes()
    replacement = wl.WorktreeLease(
        worktree_root=str(repo.resolve()), worktree_name=repo.name,
        lease_id="different-lease", owner_token="different-token",
        generation=owner.generation + 1,
    )
    with pytest.raises(RuntimeError, match="owner or generation changed"):
        wl._write_lease(replacement)
    assert path.read_bytes() == before
    with pytest.raises(RuntimeError, match="existing lease"):
        wl.publish_lease(replacement)
    assert path.read_bytes() == before
    wl.release_worktree_lease(repo, owner.owner_token, owner.lease_id)


def test_r2_cleanup_uses_common_git_path_for_retired_worktree(repo: Path):
    retired = repo.parent / "removed-linked-worktree"
    retired.mkdir()
    gitdir = repo / ".git" / "worktrees" / "removed-linked-worktree"
    (retired / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    lease = wl.WorktreeLease(
        worktree_root=str(retired.resolve()), worktree_name=retired.name,
        holder_pid=99999999, generation=1, expires_at="2020-01-01T00:00:00Z",
    )
    wl._write_lease(lease)
    lease_path = lock_paths.worktree_lease_path(repo, retired)
    (retired / ".git").unlink()
    retired.rmdir()

    assert wl.cleanup_expired_leases(repo) == 1
    assert not retired.exists(), "cleanup must not recreate a retired worktree"
    assert not lease_path.exists()


def test_r2_spliced_root_cannot_redirect_cleanup_from_physical_lease(repo: Path):
    listed = repo.parent / "listed-linked-worktree"
    listed.mkdir()
    gitdir = repo / ".git" / "worktrees" / "listed-linked-worktree"
    (listed / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    lease = wl.WorktreeLease(
        worktree_root=str(listed.resolve()), worktree_name=listed.name,
        worktree_identity=lock_paths.worktree_identity(listed),
        holder_pid=99999999, generation=1, expires_at="2020-01-01T00:00:00Z",
    )
    wl._write_lease(lease)
    physical_path = lock_paths.worktree_lease_path(repo, listed)
    spoofed_root = repo.parent / "payload-directed-worktree"
    record = json.loads(physical_path.read_text(encoding="utf-8"))
    record["worktree_root"] = str(spoofed_root)
    record["worktree_identity"] = lock_paths.worktree_identity(spoofed_root)
    physical_path.write_text(json.dumps(record), encoding="utf-8")
    (listed / ".git").unlink()
    listed.rmdir()

    if hasattr(wl, "_iter_worktree_leases"):
        assert list(wl._iter_worktree_leases(repo)) == []
    assert wl.cleanup_expired_leases(repo) == 0
    assert physical_path.exists(), "spliced lease evidence must be left for inspection"
    assert not spoofed_root.exists(), "cleanup must not create payload-selected paths"


def test_r3_busy_lease_does_not_block_other_cleanup(repo: Path, monkeypatch):
    busy_root = repo / "busy-worktree"
    free_root = repo / "free-worktree"
    busy_root.mkdir()
    free_root.mkdir()
    for root in (busy_root, free_root):
        wl._write_lease(wl.WorktreeLease(
            worktree_root=str(root.resolve()), worktree_name=root.name,
            holder_pid=99999999, generation=1, expires_at="2020-01-01T00:00:00Z",
        ))
    busy_path = lock_paths.worktree_lease_path(repo, busy_root)
    free_path = lock_paths.worktree_lease_path(repo, free_root)
    original_root_claim = wl._generation_claim
    original_claim = getattr(wl, "_generation_claim_at_path", original_root_claim)

    def busy_timeout():
        raise RuntimeError(
            "LOCKED_UNKNOWN: timed out waiting for generation claim at injected busy lease"
        )

    def short_root_claim(root: Path, *, timeout_s: float = 30.0):
        if Path(root).resolve() == busy_root.resolve() and threading.current_thread().name == "MainThread":
            busy_timeout()
        return original_root_claim(root, timeout_s=timeout_s)

    def short_claim(path: Path, *, timeout_s: float = 30.0):
        if Path(path).resolve() == busy_path.resolve() and threading.current_thread().name == "MainThread":
            busy_timeout()
        return original_claim(path, timeout_s=timeout_s)

    monkeypatch.setattr(wl, "_generation_claim", short_root_claim)
    if hasattr(wl, "_generation_claim_at_path"):
        monkeypatch.setattr(wl, "_generation_claim_at_path", short_claim)

    if hasattr(wl, "_generation_claim_at_path"):
        holder_claim = original_claim(busy_path, timeout_s=2.0)
    else:
        holder_claim = original_root_claim(busy_root, timeout_s=2.0)
    with holder_claim:
        assert wl.cleanup_expired_leases(repo) == 1

    assert busy_path.exists(), "busy lease must be skipped"
    assert not free_path.exists(), "cleanup must continue to other expired leases"
