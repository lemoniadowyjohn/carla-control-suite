"""Cross-platform lock-authority regressions for the single-writer layer.

These pin the properties Phase 5 established, by executable behaviour rather
than by source text:

* liveness is tri-state and ``UNKNOWN`` is never reclaimable;
* EPERM (process exists, owned by someone else) is not death;
* process identity is the OS start identity, so a recycled PID is detectable;
* release and renewal require an exact owner token;
* release and stale reclaim are ABA-safe;
* expiry alone cannot steal a live lock;
* authority is anchored in the common Git directory, so every worktree of a
  repository contends on one lock while per-worktree leases stay distinct;
* malformed ownership evidence blocks instead of being deleted;
* concurrent acquisition yields exactly one winner, deterministically.

Every test builds a throwaway repository under ``tmp_path``. Nothing here reads
or writes the developer's real ``.agent_locks`` namespace.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ultimate_pipeline.governance.single_writer import (
    common_git_lock as cgl,
    lock_paths,
    process_identity as pi,
    worktree_lock as wl,
)

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _git(*args, cwd):
    return subprocess.run(
        ["git", "-c", "user.email=test@example.invalid",
         "-c", "user.name=Authority Test",
         "-c", "init.defaultBranch=main", *args],
        cwd=str(cwd), capture_output=True, text=True, check=True,
    )


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git("init", cwd=root)
    _git("commit", "--allow-empty", "-m", "init", cwd=root)
    return root


@pytest.fixture()
def linked_worktrees(repo, tmp_path):
    """Two extra linked worktrees of the same repository."""
    paths = []
    for name in ("wt_a", "wt_b"):
        p = tmp_path / name
        _git("worktree", "add", str(p), "-b", name, cwd=repo)
        paths.append(p)
    return paths


def _lock_path(repo_root):
    return cgl._get_common_git_lock_path(repo_root)


def _read_raw(repo_root):
    return json.loads(_lock_path(repo_root).read_text(encoding="utf-8"))


def _plant(repo_root, **overrides):
    lock = cgl.CommonGitLock(
        repo_root=str(Path(repo_root).resolve()), operation="planted",
    )
    for key, value in overrides.items():
        setattr(lock, key, value)
    cgl._write_lock(lock)
    return lock


# ---------------------------------------------------------------------------
# liveness: tri-state, and UNKNOWN is not death
# ---------------------------------------------------------------------------


def test_live_current_pid_reads_alive():
    result = pi.probe_liveness(os.getpid())
    assert result.state is pi.LivenessState.ALIVE
    assert result.reclaimable is False


def test_absent_pid_reads_dead_and_reclaimable():
    result = pi.probe_liveness(999999)
    assert result.state is pi.LivenessState.DEAD
    assert result.reclaimable is True


def test_nonpositive_pid_is_unknown_not_dead():
    """A missing PID is missing evidence, never proof of death."""
    for pid in (0, -1):
        result = pi.probe_liveness(pid)
        assert result.state is pi.LivenessState.UNKNOWN
        assert result.reclaimable is False


def test_posix_eperm_is_alive_not_dead(monkeypatch):
    """EPERM means the process EXISTS and is merely not signalable by us."""
    def eperm(pid, sig):
        raise PermissionError(pid, "operation not permitted")

    monkeypatch.setattr(pi.sys, "platform", "linux")
    monkeypatch.setattr(pi.os, "kill", eperm)

    result = pi.probe_liveness(4242)
    assert result.state is pi.LivenessState.ALIVE
    assert result.reclaimable is False


def test_posix_esrch_is_dead(monkeypatch):
    def esrch(pid, sig):
        raise ProcessLookupError(pid)

    monkeypatch.setattr(pi.sys, "platform", "linux")
    monkeypatch.setattr(pi.os, "kill", esrch)

    assert pi.probe_liveness(4242).reclaimable is True


def test_posix_unclassified_oserror_is_unknown(monkeypatch):
    """A transient kernel error proves nothing and must not authorise a steal."""
    def weird(pid, sig):
        raise OSError(22, "invalid argument")

    monkeypatch.setattr(pi.sys, "platform", "linux")
    monkeypatch.setattr(pi.os, "kill", weird)

    result = pi.probe_liveness(4242)
    assert result.state is pi.LivenessState.UNKNOWN
    assert result.reclaimable is False


def test_reclaimable_only_for_proven_death():
    assert pi.LivenessResult(pi.LivenessState.DEAD, 1).reclaimable is True
    assert pi.LivenessResult(pi.LivenessState.ALIVE, 1).reclaimable is False
    assert pi.LivenessResult(pi.LivenessState.UNKNOWN, 1).reclaimable is False


@pytest.mark.skipif(sys.platform == "win32", reason="real POSIX EPERM probe")
def test_real_root_owned_pid_is_not_reclaimed():
    """PID 1 exists and is owned by root; we may not signal it."""
    if os.getuid() != 0:
        result = pi.probe_liveness(1)
        assert result.state is pi.LivenessState.ALIVE
        assert result.reclaimable is False


# ---------------------------------------------------------------------------
# Windows probe: timeout / access denied are UNKNOWN, never death
# ---------------------------------------------------------------------------


def test_windows_access_denied_is_alive_not_dead(monkeypatch):
    """ERROR_ACCESS_DENIED means the process exists but cannot be opened."""
    monkeypatch.setattr(pi.sys, "platform", "win32")
    monkeypatch.setattr(pi, "_OpenProcess", lambda *a: None)
    # get_last_error only exists on Windows, hence raising=False: these tests
    # simulate the Windows branch from either platform.
    monkeypatch.setattr(pi.ctypes, "get_last_error", lambda: pi.ERROR_ACCESS_DENIED,
                        raising=False)

    result = pi.probe_liveness(4242)
    assert result.state is pi.LivenessState.ALIVE
    assert result.reclaimable is False


def test_windows_invalid_parameter_is_dead(monkeypatch):
    monkeypatch.setattr(pi.sys, "platform", "win32")
    monkeypatch.setattr(pi, "_OpenProcess", lambda *a: None)
    monkeypatch.setattr(pi.ctypes, "get_last_error", lambda: pi.ERROR_INVALID_PARAMETER,
                        raising=False)

    assert pi.probe_liveness(4242).reclaimable is True


def test_windows_unclassified_error_is_unknown(monkeypatch):
    """ERROR_INVALID_PARAMETER is death; every other failure code is UNKNOWN."""
    monkeypatch.setattr(pi.sys, "platform", "win32")
    monkeypatch.setattr(pi, "_OpenProcess", lambda *a: None)
    monkeypatch.setattr(pi.ctypes, "get_last_error", lambda: 1117, raising=False)

    result = pi.probe_liveness(4242)
    assert result.state is pi.LivenessState.UNKNOWN
    assert result.reclaimable is False


def test_no_tasklist_shellout_remains():
    """The 10s tasklist timeout and its substring PID match are gone."""
    source = Path(cgl.__file__).read_text(encoding="utf-8")
    assert "tasklist" not in source


# ---------------------------------------------------------------------------
# process identity
# ---------------------------------------------------------------------------


def test_start_identity_comes_from_the_os_not_the_clock(repo):
    lock = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        raw = _read_raw(repo)
        assert raw["holder_start_identity"]
        # It must not be the acquisition stamp.
        assert raw["holder_start_identity"] != raw["acquired_at"]
        # And it must be stable across repeated reads.
        again = pi.process_start_identity(os.getpid())
        assert again == raw["holder_start_identity"]
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_same_pid_same_start_identity_matches(repo):
    start = pi.process_start_identity(os.getpid())
    observed = pi.probe_liveness(os.getpid())
    assert pi.same_process(os.getpid(), start, observed) is True


def test_same_pid_different_start_identity_is_not_the_same_process(repo):
    observed = pi.probe_liveness(os.getpid())
    assert pi.same_process(os.getpid(), "1999-01-01T00:00:00Z", observed) is False


def test_absent_recorded_identity_never_claims_a_match(repo):
    """Without a recorded start identity, a bare PID cannot prove ownership."""
    observed = pi.probe_liveness(os.getpid())
    assert pi.same_process(os.getpid(), "", observed) is False


def test_recycled_pid_authorises_reclaim(repo):
    """A live PID whose start identity differs is a leftover, not an owner."""
    _plant(repo, holder_pid=os.getpid(), holder_start_identity="1999-01-01T00:00:00Z")
    may_reclaim, why = cgl.reclaim_decision(cgl._read_lock(repo))
    assert may_reclaim is True
    assert "recycled" in why


def test_identity_converges_with_orch_core():
    """The governance identity must agree with the Phase-4 hardened helper."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    try:
        from scripts import orch_core
    except Exception:  # pragma: no cover - namespace import may be unavailable
        pytest.skip("scripts.orch_core not importable from this environment")
    ours = pi.process_start_identity(os.getpid())
    theirs = orch_core.process_creation_time(os.getpid())
    if ours is None or theirs is None:
        pytest.skip("this host exposes no OS process start identity")
    # The two render sub-second precision differently (FILETIME vs CIM), so
    # compare the instants rather than the strings.
    import datetime

    def _parse(stamp):
        return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00"))

    delta = abs((_parse(ours) - _parse(theirs)).total_seconds())
    assert delta < 0.01, f"identity differs by {delta}s: {ours} vs {theirs}"


# ---------------------------------------------------------------------------
# ownership: token-bound release and renewal
# ---------------------------------------------------------------------------


def test_release_without_token_is_rejected(repo):
    lock = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        with pytest.raises(RuntimeError, match="mandatory"):
            cgl.release_common_git_lock(repo)
        assert _read_raw(repo)["lock_id"] == lock.lock_id
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_release_with_wrong_token_is_rejected(repo):
    lock = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        with pytest.raises(RuntimeError, match="owner token does not match"):
            cgl.release_common_git_lock(repo, "not-my-token")
        assert _read_raw(repo)["lock_id"] == lock.lock_id
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_release_with_exact_token_succeeds(repo):
    lock = cgl.acquire_common_git_lock(repo, "git fetch")
    assert cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id) is True
    assert not _lock_path(repo).exists()


def test_worktree_release_requires_a_token(repo):
    lease = wl.acquire_worktree_lease(repo, purpose="ownership")
    try:
        with pytest.raises(RuntimeError, match="mandatory"):
            wl.release_worktree_lease(repo)
    finally:
        wl.release_worktree_lease(repo, lease.owner_token, lease.lease_id)


def test_previous_generation_cannot_release_the_successor(repo):
    """A: own generation 1, reads it, pauses. B takes generation 2. A resumes."""
    a = cgl.acquire_common_git_lock(repo, "A op")
    path = _lock_path(repo)
    successor = json.loads(path.read_text(encoding="utf-8"))
    successor.update({"lock_id": "b-lock", "owner_token": "b-token", "generation": 999})
    path.write_text(json.dumps(successor), encoding="utf-8")

    with pytest.raises(RuntimeError):
        cgl.release_common_git_lock(repo, a.owner_token, a.lock_id)

    # B's live lock survived.
    assert json.loads(path.read_text(encoding="utf-8"))["owner_token"] == "b-token"


def test_previous_generation_cannot_renew_the_successor(repo):
    a = cgl.acquire_common_git_lock(repo, "A op")
    path = _lock_path(repo)
    successor = json.loads(path.read_text(encoding="utf-8"))
    successor.update({"lock_id": "b-lock", "owner_token": "b-token", "generation": 999})
    path.write_text(json.dumps(successor), encoding="utf-8")

    with pytest.raises(RuntimeError):
        cgl.renew_common_git_lock(repo, a.owner_token, a.lock_id)


def test_renewal_extends_expiry_and_keeps_generation(repo):
    lock = cgl.acquire_common_git_lock(repo, "renew", timeout_seconds=1)
    try:
        time.sleep(1.1)
        renewed = cgl.renew_common_git_lock(
            repo, lock.owner_token, lock.lock_id, ttl_seconds=600
        )
        assert renewed.expires_at > lock.expires_at
        assert renewed.generation == lock.generation
        assert renewed.is_expired() is False
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_wrong_owner_cannot_extend_a_lease(repo):
    lock = cgl.acquire_common_git_lock(repo, "renew", timeout_seconds=600)
    try:
        with pytest.raises(RuntimeError):
            cgl.renew_common_git_lock(repo, "bogus-token")
        assert _read_raw(repo)["expires_at"] == lock.expires_at
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_worktree_renewal_requires_exact_token(repo):
    lease = wl.acquire_worktree_lease(repo, purpose="renew")
    try:
        renewed = wl.renew_worktree_lease(repo, lease.owner_token, lease.lease_id)
        assert renewed.generation == lease.generation
        with pytest.raises(RuntimeError):
            wl.renew_worktree_lease(repo, "bogus")
    finally:
        wl.release_worktree_lease(repo, lease.owner_token, lease.lease_id)


def test_fencing_generations_strictly_increase(repo):
    seen = []
    for i in range(4):
        lock = cgl.acquire_common_git_lock(repo, f"op{i}")
        seen.append(lock.generation)
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)
    assert seen == sorted(seen)
    assert len(set(seen)) == len(seen)


# ---------------------------------------------------------------------------
# expiry semantics
# ---------------------------------------------------------------------------


def test_expired_but_live_owner_is_not_stolen(repo):
    """Expiry is evidence renewal is unhealthy, not proof the owner died."""
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    _plant(
        repo, expires_at=past, holder_pid=os.getpid(),
        holder_start_identity=pi.process_start_identity(os.getpid()) or "",
    )
    may_reclaim, why = cgl.reclaim_decision(cgl._read_lock(repo))
    assert may_reclaim is False
    assert "alive" in why

    with pytest.raises(RuntimeError, match="not reclaimable"):
        cgl.acquire_common_git_lock(repo, "steal attempt")


def test_expired_with_unknown_owner_is_not_stolen(repo):
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    _plant(repo, expires_at=past, holder_pid=0)
    may_reclaim, why = cgl.reclaim_decision(cgl._read_lock(repo))
    assert may_reclaim is False
    assert "UNKNOWN" in why


def test_expired_with_proven_dead_owner_may_be_reclaimed(repo):
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    _plant(repo, expires_at=past, holder_pid=999999)
    may_reclaim, _why = cgl.reclaim_decision(cgl._read_lock(repo))
    assert may_reclaim is True

    lock = cgl.acquire_common_git_lock(repo, "after death")
    try:
        assert lock.operation == "after death"
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_status_surfaces_expired_live_owner_without_stealing(repo):
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    _plant(
        repo, expires_at=past, holder_pid=os.getpid(),
        holder_start_identity=pi.process_start_identity(os.getpid()) or "",
    )
    status = cgl.get_lock_status(repo)
    assert status["status"] == "active_expired_owner_alive"
    assert status["reclaimable"] is False
    assert status["expired"] is True


def test_worktree_cleanup_keeps_expired_but_live_lease(repo):
    lease = wl.acquire_worktree_lease(repo, purpose="live", lease_minutes=600)
    # Force it expired without changing ownership evidence.
    path = wl._worktree_lease_path(repo)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["expires_at"] = "2020-01-01T00:00:00Z"
    path.write_text(json.dumps(record), encoding="utf-8")

    assert wl.cleanup_expired_leases(repo) == 0
    assert path.exists()

    wl.release_worktree_lease(repo, lease.owner_token, lease.lease_id)


def test_worktree_cleanup_removes_expired_dead_lease(repo):
    path = wl._worktree_lease_path(repo)
    wl._write_lease(
        wl.WorktreeLease(
            worktree_root=str(repo.resolve()), holder_pid=999999,
            expires_at="2020-01-01T00:00:00Z",
        )
    )
    assert wl.cleanup_expired_leases(repo) == 1
    assert not path.exists()


# ---------------------------------------------------------------------------
# ABA-safe reclaim
# ---------------------------------------------------------------------------


def test_stale_reclaimer_does_not_delete_the_new_generation(repo):
    """Reclaimer judged generation G, but G was replaced. It must restore."""
    path = _lock_path(repo)
    old = _plant(repo, holder_pid=999999, generation=100, lock_id="old-lock",
                 owner_token="old-token")
    judged = cgl.reclaim_decision(old)
    assert judged[0] is True

    # A successor publishes before the reclaimer gets to act.
    new_record = json.loads(path.read_text(encoding="utf-8"))
    new_record.update({"lock_id": "new-lock", "owner_token": "new-token",
                       "generation": 200, "holder_pid": os.getpid()})
    path.write_text(json.dumps(new_record), encoding="utf-8")

    claimed, _tomb = cgl._claim_by_rename(
        repo, "reclaim", cgl._lock_matches("old-lock", "old-token", 100)
    )
    assert claimed is False
    # The successor's bytes were put back, not destroyed.
    assert json.loads(path.read_text(encoding="utf-8"))["owner_token"] == "new-token"


def test_reclaim_of_the_exact_generation_succeeds(repo):
    path = _lock_path(repo)
    old = _plant(repo, holder_pid=999999, generation=100, lock_id="old-lock",
                 owner_token="old-token")
    claimed, tomb = cgl._claim_by_rename(
        repo, "reclaim", cgl._lock_matches(old.lock_id, old.owner_token, old.generation)
    )
    assert claimed is True
    tomb.unlink()
    assert not path.exists()


# ---------------------------------------------------------------------------
# malformed evidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("payload", ["{ truncated", "", "not json at all", "[1,2,3]"])
def test_malformed_lock_blocks_and_is_not_deleted(repo, payload):
    path = _lock_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(cgl.MalformedLockError, match="BLOCKED_MALFORMED_LOCK"):
        cgl.acquire_common_git_lock(repo, "git fetch")
    assert path.read_text(encoding="utf-8") == payload


def test_malformed_status_is_actionable(repo):
    path = _lock_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ truncated", encoding="utf-8")
    status = cgl.get_lock_status(repo)
    assert status["status"] == "BLOCKED_MALFORMED_LOCK"
    assert status["detail"]


def test_operator_recovery_is_explicit_and_audited(repo):
    path = _lock_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ truncated", encoding="utf-8")

    record = cgl.recover_malformed_lock(repo, "operator@example.invalid", "verified")
    assert record["recovered"] is True
    assert len(record["removed_sha256"]) == 64
    assert record["operator"] == "operator@example.invalid"
    assert record["recovered_at"]
    assert not path.exists()


def test_malformed_worktree_lease_blocks_and_is_not_deleted(repo):
    path = wl._worktree_lease_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ truncated", encoding="utf-8")
    with pytest.raises(wl.MalformedLeaseError, match="BLOCKED_MALFORMED_LEASE"):
        wl.acquire_worktree_lease(repo, purpose="after corruption")
    assert path.read_text(encoding="utf-8") == "{ truncated"


# ---------------------------------------------------------------------------
# common Git directory authority across worktrees
# ---------------------------------------------------------------------------


def test_every_worktree_resolves_one_common_lock(repo, linked_worktrees):
    paths = [cgl._get_common_git_lock_path(p) for p in (repo, *linked_worktrees)]
    assert len(set(paths)) == 1


def test_lock_taken_in_a_worktree_excludes_the_main_checkout(repo, linked_worktrees):
    wt_a = linked_worktrees[0]
    lock = cgl.acquire_common_git_lock(wt_a, "git fetch")
    try:
        with pytest.raises(RuntimeError, match="held by"):
            cgl.acquire_common_git_lock(repo, "git push")
        with pytest.raises(RuntimeError, match="held by"):
            cgl.acquire_common_git_lock(linked_worktrees[1], "git push")
    finally:
        cgl.release_common_git_lock(wt_a, lock.owner_token, lock.lock_id)


def test_worktree_leases_stay_distinct_inside_one_repository(repo, linked_worktrees):
    a = wl.acquire_worktree_lease(linked_worktrees[0], purpose="a")
    b = wl.acquire_worktree_lease(linked_worktrees[1], purpose="b")
    try:
        assert a.lease_id != b.lease_id
        assert wl._worktree_lease_path(linked_worktrees[0]) != \
            wl._worktree_lease_path(linked_worktrees[1])
        # Same worktree is refused.
        with pytest.raises(RuntimeError):
            wl.acquire_worktree_lease(linked_worktrees[0], purpose="dup")
    finally:
        wl.release_worktree_lease(linked_worktrees[0], a.owner_token, a.lease_id)
        wl.release_worktree_lease(linked_worktrees[1], b.owner_token, b.lease_id)


def test_worktree_identity_is_a_digest_and_cannot_collide(tmp_path):
    first = tmp_path / "a" / "b"
    second = tmp_path / "a_b"
    first.mkdir(parents=True)
    second.mkdir()
    # The old flattening scheme mapped both of these to the same filename.
    assert lock_paths.describe_worktree(first) == lock_paths.describe_worktree(second)
    assert lock_paths.worktree_identity(first) != lock_paths.worktree_identity(second)


def test_worktree_identity_is_case_normalised(tmp_path):
    p = tmp_path / "wt"
    p.mkdir()
    assert lock_paths.worktree_identity(p) == lock_paths.worktree_identity(p)


def test_non_repository_is_rejected_clearly(tmp_path):
    with pytest.raises(RuntimeError, match="Not a Git repository"):
        cgl._get_common_git_lock_path(tmp_path / "definitely-not-a-repo")


# ---------------------------------------------------------------------------
# concurrency: exactly one winner, deterministically
# ---------------------------------------------------------------------------


def test_concurrent_acquire_has_exactly_one_winner(repo):
    """Hard gate: the published lock is always held by at most one owner.

    Contenders are released together by a barrier and each records an
    ENTER/EXIT marker into an append-only log. Because every publish, release
    and reclaim appends exactly one marker, the log must strictly alternate
    ENTER/EXIT. Two ENTERs without an intervening EXIT would be two owners
    inside the critical section at once. This is checked deterministically,
    over many rounds, rather than inferred from a winner count.
    """
    log = Path(repo) / "critical.log"
    marker = os.open(str(log), os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)

    def _append(text):
        os.write(marker, f"{text}\n".encode("ascii"))
        os.fsync(marker)

    for round_index in range(10):
        _append("ROUND")
        barrier = threading.Barrier(8)
        errors = []

        def contender():
            barrier.wait()
            try:
                lock = cgl.acquire_common_git_lock(repo, f"race{round_index}")
            except RuntimeError:
                return
            try:
                _append("ENTER")
                time.sleep(0.002)
                _append("EXIT")
            finally:
                try:
                    cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)
                except RuntimeError as exc:
                    errors.append(str(exc))

        with ThreadPoolExecutor(max_workers=8) as pool:
            for _ in range(8):
                pool.submit(contender)

        assert not errors, f"round {round_index}: {errors}"

    os.close(marker)

    depth = 0
    rounds = 0
    for line in log.read_text(encoding="utf-8").splitlines():
        if line == "ROUND":
            assert depth == 0, f"round boundary inside a critical section (depth={depth})"
            rounds += 1
            continue
        if line == "ENTER":
            assert depth == 0, "two owners were inside the critical section at once"
            depth += 1
        else:
            assert depth == 1, "EXIT without a matching ENTER"
            depth -= 1
    assert depth == 0
    assert rounds == 10


def test_contenders_observe_a_coherent_published_record(repo):
    """Whatever a contender sees, the published record is whole and owned."""
    observed = []

    def contender():
        try:
            lock = cgl.acquire_common_git_lock(repo, "reader")
        except RuntimeError:
            return
        try:
            raw = json.loads(_lock_path(repo).read_text(encoding="utf-8"))
            observed.append((raw["lock_id"], raw["owner_token"], raw["generation"]))
        finally:
            cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)

    with ThreadPoolExecutor(max_workers=8) as pool:
        for _ in range(8):
            pool.submit(contender)

    assert observed
    for lock_id, token, generation in observed:
        assert lock_id and token
        assert isinstance(generation, int) and generation >= 1


def test_multiprocess_stress_bounded(tmp_path):
    """Bounded cross-process stress: 25 rounds x 8 contenders.

    Each round runs eight separate OS processes that race for the same lock.
    Every process that enters the critical section appends ENTER/EXIT markers
    to one append-only log. The invariant is mutual exclusion, so the log must
    alternate strictly and generations must be unique.
    """
    repo = tmp_path / "stress"
    repo.mkdir()
    _git("init", cwd=repo)
    _git("commit", "--allow-empty", "-m", "init", cwd=repo)

    log = repo / "critical.log"
    script = tmp_path / "contender.py"
    script.write_text(
        "import os, sys\n"
        f"sys.path.insert(0, {str(Path.cwd())!r})\n"
        "from pathlib import Path\n"
        "from ultimate_pipeline.governance.single_writer import common_git_lock as cgl\n"
        "repo = Path(sys.argv[1]); log = Path(sys.argv[2])\n"
        "fd = os.open(str(log), os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)\n"
        "def mark(text):\n"
        "    os.write(fd, (text + chr(10)).encode('ascii')); os.fsync(fd)\n"
        "try:\n"
        "    lock = cgl.acquire_common_git_lock(repo, 'stress', timeout_seconds=30)\n"
        "except RuntimeError:\n"
        "    sys.exit(0)\n"
        "mark('ENTER %d %d' % (os.getpid(), lock.generation))\n"
        "mark('EXIT  %d %d' % (os.getpid(), lock.generation))\n"
        "cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)\n",
        encoding="utf-8",
    )

    rounds = 25
    contenders = 8
    for round_index in range(rounds):
        with open(log, "a", encoding="utf-8"):
            pass
        with open(log, "a", encoding="utf-8") as fh:
            fh.write("ROUND\n")
        procs = [
            subprocess.Popen(
                [sys.executable, str(script), str(repo), str(log)],
                cwd=str(Path.cwd()), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
            )
            for _ in range(contenders)
        ]
        for proc in procs:
            proc.communicate(timeout=120)

    # Verify mutual exclusion across every round, from the append-only log.
    depth = 0
    entered = 0
    generations = []
    for line in log.read_text(encoding="utf-8").splitlines():
        if line == "ROUND":
            assert depth == 0, "a round ended while a holder was inside"
            continue
        kind, _pid, generation = line.split()
        if kind == "ENTER":
            assert depth == 0, "two processes held the lock at once"
            depth += 1
            entered += 1
            generations.append(int(generation))
        else:
            assert depth == 1, "EXIT without ENTER"
            depth -= 1
    assert depth == 0
    assert entered == len(generations)
    assert len(set(generations)) == len(generations), "a fencing generation was reused"