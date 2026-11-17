"""Windows-feasible V95 adversarial/fault-injection checks (interim).

These tests target highest-risk invariants that can be exercised without
Linux-specific symlink semantics or external CARLA/runtime dependencies.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from ultimate_pipeline.governance.single_writer import worktree_lock as wl
from ultimate_pipeline.governance.single_writer import common_git_lock as cgl


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Minimal git-like worktree root with common git dir namespace."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    # lock_paths expects a git common dir; a .git directory is sufficient for
    # resolve_git_common_dir fallback in this codebase.
    return root


def _lease_path(repo: Path) -> Path:
    return wl._worktree_lease_path(repo)


def test_v95_08_generation_claim_release_refuses_to_unlink_foreign_claim(repo: Path):
    """Releaser must still own claim before unlink; foreign replacement must not be deleted."""
    lease_path = _lease_path(repo)
    claim_path = lease_path.with_name(f"{lease_path.name}.generation-claim")
    foreign = b'{"pid":999999,"start_identity":"foreign","token":"foreign-token"}'

    with pytest.raises(RuntimeError, match="no longer owned by this process|refusing to unlink|LOCKED_UNKNOWN"):
        with wl._generation_claim_at_path(lease_path):
            assert claim_path.exists()
            # Simulate claim replacement/race after acquisition but before cleanup.
            claim_path.write_bytes(foreign)

    # Evidence must be preserved for operator inspection/recovery.
    assert claim_path.exists()
    assert claim_path.read_bytes() == foreign
    claim_path.unlink()


def test_v95_05_fallback_partial_or_empty_publication_is_not_valid_ownership(repo: Path):
    """Fallback/partial publication must not be interpretable as valid ownership."""
    lease_path = _lease_path(repo)
    lease_path.parent.mkdir(parents=True, exist_ok=True)

    # Empty (publisher-died-mid-write) case.
    lease_path.write_bytes(b"")
    state, lease, reason = wl._read_state(repo)
    assert state == wl._LeaseRead.MALFORMED
    assert lease is None
    assert "empty" in reason.lower() or "mid-write" in reason.lower()
    with pytest.raises(wl.MalformedLeaseError):
        wl._read_lease(repo)

    # Partial/invalid JSON case.
    lease_path.write_bytes(b'{"schema":"worktree-mutation-lease/v2","status":"active"')
    state, lease, reason = wl._read_state(repo)
    assert state == wl._LeaseRead.MALFORMED
    assert lease is None
    with pytest.raises(wl.MalformedLeaseError):
        wl._read_lease(repo)

    # Valid JSON but unusable/non-owner record must not become current owner.
    bad = {"schema": "worktree-mutation-lease/v2", "status": "active", "generation": 0}
    lease_path.write_text(json.dumps(bad), encoding="utf-8")
    # Depending on parser strictness this may be parsed or malformed; in no case
    # may it be treated as a current valid owner for a different lease.
    probe = wl.WorktreeLease(
        worktree_root=str(repo.resolve()),
        worktree_identity=wl.lock_paths.worktree_identity(repo.resolve()),
        worktree_name=repo.name,
        lease_id="x",
        owner_token="y",
        generation=1,
    )
    assert wl.lease_is_current(probe) is False


def test_common_git_empty_or_partial_lock_is_not_valid_ownership(repo: Path):
    path = cgl._get_common_git_lock_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_bytes(b"")
    state, lock, reason = cgl._read_state(repo)
    assert state == cgl._LockRead.MALFORMED
    assert lock is None
    with pytest.raises(cgl.MalformedLockError):
        cgl._read_lock(repo)

    path.write_bytes(b'{"schema":"common-git-lock/v2"')
    state, lock, reason = cgl._read_state(repo)
    assert state == cgl._LockRead.MALFORMED
    assert lock is None
    with pytest.raises(cgl.MalformedLockError):
        cgl._read_lock(repo)


def test_v94_02_generation_high_water_blocks_stale_publication(repo: Path):
    """Stale generation must not publish at/under durable high-water."""
    first = wl.acquire_worktree_lease(repo, purpose="first")
    assert first.generation >= 1
    high = wl._generation_high_water(repo)
    assert high >= first.generation
    assert wl.release_worktree_lease(repo, first.owner_token, first.lease_id) is True

    stale = wl.WorktreeLease(
        worktree_root=str(repo.resolve()),
        worktree_identity=wl.lock_paths.worktree_identity(repo.resolve()),
        worktree_name=repo.name,
        lease_id="stale-id",
        owner_token="stale-token",
        generation=high,  # at high-water => stale
        purpose="stale",
        holder_pid=first.holder_pid,
        holder_start_identity=first.holder_start_identity,
    )
    with pytest.raises(RuntimeError, match="stale generation|LOCKED_UNKNOWN|generation"):
        wl.publish_lease(stale)

    # Namespace remains acquirable with a strictly newer generation.
    second = wl.acquire_worktree_lease(repo, purpose="second")
    try:
        assert second.generation > high
    finally:
        wl.release_worktree_lease(repo, second.owner_token, second.lease_id)


def test_v95_07_remove_lease_has_no_production_callers_static(repo: Path):
    """Static audit helper: _remove_lease must not be referenced by production callers."""
    root = Path(__file__).resolve().parents[2]  # F:\wt\v95-verification-20251117
    offenders = []
    for p in root.joinpath("ultimate_pipeline").rglob("*.py"):
        norm = str(p).replace("\\", "/")
        if "governance/single_writer/" in norm:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "_remove_lease(" in text:
            offenders.append(str(p))
    scripts = root.joinpath("scripts")
    if scripts.exists():
        for p in scripts.rglob("*.py"):
            text = p.read_text(encoding="utf-8", errors="replace")
            if "_remove_lease(" in text:
                offenders.append(str(p))
    assert offenders == [], f"production callers of _remove_lease: {offenders}"


def test_v95_06_release_renew_reject_wrong_owner_and_stale_generation(repo: Path):
    """Exact owner token/lease_id/generation required; stale owner cannot mutate successor."""
    owner = wl.acquire_worktree_lease(repo, purpose="owner")
    try:
        with pytest.raises(RuntimeError):
            wl.release_worktree_lease(repo, "wrong-token", owner.lease_id)
        with pytest.raises(RuntimeError):
            wl.release_worktree_lease(repo, owner.owner_token, "wrong-lease-id")
        with pytest.raises(RuntimeError):
            wl.renew_worktree_lease(repo, "wrong-token", owner.lease_id)

        assert wl.release_worktree_lease(repo, owner.owner_token, owner.lease_id) is True
        successor = wl.acquire_worktree_lease(repo, purpose="successor")
        try:
            assert successor.generation > owner.generation
            # Stale generation/token must not release or renew successor.
            with pytest.raises(RuntimeError):
                wl.release_worktree_lease(repo, owner.owner_token, owner.lease_id)
            with pytest.raises(RuntimeError):
                wl.renew_worktree_lease(repo, owner.owner_token, owner.lease_id)
        finally:
            wl.release_worktree_lease(repo, successor.owner_token, successor.lease_id)
    finally:
        # owner already released if we reached successor; ignore if absent
        try:
            wl.release_worktree_lease(repo, owner.owner_token, owner.lease_id)
        except RuntimeError:
            pass


def test_v94_05_cleanup_continues_when_one_scope_has_malformed_generation_claim(repo: Path):
    """Malformed/busy claim on one expired scope must not block independent cleanup."""
    a = repo / "wt_a"
    b = repo / "wt_b"
    a.mkdir()
    b.mkdir()

    # Create expired, reclaimable leases for both scopes.
    for root in (a, b):
        lease = wl.WorktreeLease(
            worktree_root=str(root.resolve()),
            worktree_identity=wl.lock_paths.worktree_identity(root.resolve()),
            worktree_name=root.name,
            lease_id=f"id-{root.name}",
            owner_token=f"tok-{root.name}",
            generation=1,
            holder_pid=99999999,  # expected dead/nonexistent in tests
            holder_ppid=1,
            holder_cmdline="test",
            host="test",
            holder_start_identity="dead-start",
            purpose="expired",
            expires_at="2020-01-01T00:00:00Z",
        )
        wl._write_lease(lease)

    # Corrupt generation claim for scope A (malformed evidence) while lease remains expired.
    claim_a = wl._generation_claim_path_for_lease(wl._worktree_lease_path(a))
    claim_a.write_bytes(b"{not-json")

    diagnostics = []
    removed = wl.cleanup_expired_leases(repo, diagnostics=diagnostics)

    # B should be cleaned independently; A must be retained as blocked evidence.
    assert not wl._worktree_lease_path(b).exists()
    assert wl._worktree_lease_path(a).exists()
    assert claim_a.exists()
    assert removed >= 1
    assert diagnostics, "malformed claim should be reported in diagnostics"
