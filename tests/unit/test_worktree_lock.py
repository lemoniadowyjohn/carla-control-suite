"""Unit coverage for per-worktree mutation leases.

Leases are registered in the repository's common Git directory and keyed by a
SHA-256 digest of the canonical worktree path, so two different worktrees can
never collide and a linked worktree resolves to the same namespace as the main
checkout. Every test here builds a throwaway repository under `tmp_path`; the
real repository's `.agent_locks` is never read or written.

Phase 5 made release token-bound, stopped expiry and uncertain liveness from
authorising a steal, anchored identity on the OS process start time, and made a
malformed record block rather than deadlock. Tests that previously pinned those
defective behaviours were rewritten; see `test_single_writer_authority.py`.
"""
import calendar
import json
import os
import time
from pathlib import Path

import pytest

from ultimate_pipeline.governance.single_writer import lock_paths
from ultimate_pipeline.governance.single_writer import process_identity as pi
from ultimate_pipeline.governance.single_writer import worktree_lock as wl


class _OffsetTime:
    """Pins expiry arithmetic to canonical UTC so the suite is host-independent."""

    def __init__(self, std_east_seconds, dst_east_seconds):
        self._std_east = std_east_seconds
        self._dst_east = dst_east_seconds

    def __getattr__(self, name):
        return getattr(time, name)

    def gmtime(self, secs=None):
        struct = time.gmtime() if secs is None else time.gmtime(secs)
        return time.struct_time(tuple(struct[:8]) + (0,))

    def mktime(self, struct):
        east = self._std_east if struct.tm_isdst == 0 else self._dst_east
        return calendar.timegm(struct) - east


@pytest.fixture(autouse=True)
def utc_time_semantics(monkeypatch):
    monkeypatch.setattr(wl, "time", _OffsetTime(0, 0))


def _git(*args, cwd):
    import subprocess

    return subprocess.run(
        ["git", "-c", "user.email=test@example.invalid",
         "-c", "user.name=GAP052 Test",
         "-c", "init.defaultBranch=main", *args],
        cwd=str(cwd), capture_output=True, text=True, check=True,
    )


@pytest.fixture()
def repo(tmp_path):
    """A throwaway git repository standing in for a worktree root."""
    root = tmp_path / "repo"
    root.mkdir()
    _git("init", cwd=root)
    _git("commit", "--allow-empty", "-m", "init", cwd=root)
    return root


@pytest.fixture()
def worktree(tmp_path):
    """A throwaway directory standing in for a worktree root (no git needed)."""
    wt = tmp_path / "wt_main"
    wt.mkdir()
    _git("init", cwd=wt)
    _git("commit", "--allow-empty", "-m", "init", cwd=wt)
    return wt


@pytest.fixture(autouse=True)
def _no_leaked_leases():
    """Release anything a test forgets, so the shared namespace stays clean.

    Resolves the lease namespace WITHOUT creating it, so running this module
    never materialises anything in the real repository's `.agent_locks`.
    """
    yield
    try:
        leases_dir = (
            lock_paths.resolve_git_common_dir(Path.cwd())
            / lock_paths.AGENT_LOCKS_DIRNAME
            / lock_paths.WORKTREE_LEASES_DIRNAME
        )
    except RuntimeError:
        return
    if not leases_dir.is_dir():
        return
    for path in leases_dir.glob("*.lease.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("holder_pid") == os.getpid():
                path.unlink()
        except OSError:
            continue


def _lease_path_for(worktree_root):
    return wl._worktree_lease_path(Path(worktree_root).resolve())


def _read_raw(worktree_root):
    return json.loads(_lease_path_for(worktree_root).read_text(encoding="utf-8"))


def _plant_lease(worktree_root, **overrides):
    lease = wl.WorktreeLease(
        worktree_root=str(Path(worktree_root).resolve()),
        worktree_name=Path(worktree_root).name,
    )
    for key, value in overrides.items():
        setattr(lease, key, value)
    wl._write_lease(lease)
    return lease


def _utc_delta_seconds(stamp, fmt="%Y-%m-%dT%H:%M:%SZ"):
    return calendar.timegm(time.strptime(stamp, fmt)) - time.time()


# --------------------------------------------------------------------------
# acquire: happy path and lease contents
# --------------------------------------------------------------------------

def test_acquire_returns_active_lease(worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="unit test")
    try:
        assert lease.status == "active"
        assert lease.purpose == "unit test"
        assert lease.lease_id
        assert lease.owner_token
        assert lease.generation >= 1
    finally:
        wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id)


def test_lease_records_os_process_identity(worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="identity")
    try:
        data = _read_raw(worktree)
        assert data["holder_pid"] == os.getpid()
        assert data["holder_ppid"] == os.getppid()
        assert data["holder_cmdline"]
        assert data["holder_start_identity"]
        # Identity is the OS start time, not the acquisition stamp.
        assert data["holder_start_identity"] != data["acquired_at"]
    finally:
        wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id)


def test_lease_records_worktree_identity(worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="identity")
    try:
        data = _read_raw(worktree)
        assert data["worktree_identity"] == lock_paths.worktree_identity(worktree)
        assert data["worktree_identity"] == lock_paths.worktree_identity(Path(worktree).resolve())
    finally:
        wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id)


def test_lease_json_roundtrip(worktree):
    original = wl.acquire_worktree_lease(worktree, purpose="roundtrip")
    try:
        restored = wl.WorktreeLease.from_json(original.to_json())
        assert restored.to_json() == original.to_json()
    finally:
        wl.release_worktree_lease(worktree, original.owner_token, original.lease_id)


def test_from_json_defaults_missing_fields():
    restored = wl.WorktreeLease.from_json({"lease_id": "abc"})
    assert restored.lease_id == "abc"
    assert restored.schema == wl.SCHEMA_VERSION
    assert restored.status == "active"
    assert restored.holder_pid == 0


def test_lease_minutes_sets_the_expiry(worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="expiry", lease_minutes=30)
    try:
        assert _utc_delta_seconds(lease.expires_at) == pytest.approx(30 * 60, abs=10)
    finally:
        wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id)


def test_negative_minutes_lease_is_immediately_expired(worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="short", lease_minutes=-1)
    assert lease.is_expired() is True
    wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id)


def test_lease_path_is_a_digest_not_a_flattened_path(worktree):
    wl.acquire_worktree_lease(worktree, purpose="sanitise")
    try:
        name = _lease_path_for(worktree).name
        assert name.endswith(".lease.json")
        digest = name[: -len(".lease.json")]
        assert len(digest) == 64, "expected a sha256 digest"
        assert ":" not in digest and "\\" not in digest and "/" not in digest
    finally:
        wl.release_worktree_lease(
            worktree, *_token_and_id(worktree)
        )


def _token_and_id(worktree):
    data = _read_raw(worktree)
    return data["owner_token"], data["lease_id"]


# --------------------------------------------------------------------------
# contention
# --------------------------------------------------------------------------

def test_second_acquire_on_same_worktree_is_refused(worktree):
    first = wl.acquire_worktree_lease(worktree, purpose="first")
    try:
        with pytest.raises(RuntimeError) as excinfo:
            wl.acquire_worktree_lease(worktree, purpose="second")
        message = str(excinfo.value)
        assert first.lease_id in message
        assert "not reclaimable" in message
    finally:
        wl.release_worktree_lease(worktree, first.owner_token, first.lease_id)


def test_refused_acquire_does_not_disturb_the_holder(worktree):
    first = wl.acquire_worktree_lease(worktree, purpose="first")
    try:
        with pytest.raises(RuntimeError):
            wl.acquire_worktree_lease(worktree, purpose="second")
        assert _read_raw(worktree)["lease_id"] == first.lease_id
    finally:
        wl.release_worktree_lease(worktree, first.owner_token, first.lease_id)


def test_different_worktrees_may_hold_leases_concurrently(tmp_path):
    roots = []
    for name in ("wt_a", "wt_b"):
        root = tmp_path / name
        root.mkdir()
        _git("init", cwd=root)
        _git("commit", "--allow-empty", "-m", "init", cwd=root)
        roots.append(root)

    first = wl.acquire_worktree_lease(roots[0], purpose="a")
    second = wl.acquire_worktree_lease(roots[1], purpose="b")
    try:
        assert first.lease_id != second.lease_id
        assert _lease_path_for(roots[0]) != _lease_path_for(roots[1])
    finally:
        wl.release_worktree_lease(roots[0], first.owner_token, first.lease_id)
        wl.release_worktree_lease(roots[1], second.owner_token, second.lease_id)


def test_concurrent_acquire_on_one_worktree_has_one_holder(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    worktree = tmp_path / "wt_race"
    worktree.mkdir()
    _git("init", cwd=worktree)
    _git("commit", "--allow-empty", "-m", "init", cwd=worktree)

    outcomes = []
    barrier = threading.Barrier(6)

    def contender():
        barrier.wait()
        try:
            outcomes.append(wl.acquire_worktree_lease(worktree, purpose="race"))
        except RuntimeError:
            outcomes.append(None)

    with ThreadPoolExecutor(max_workers=6) as pool:
        for _ in range(6):
            pool.submit(contender)

    held = [o for o in outcomes if o is not None]
    for lease in held:
        wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id)

    # Every acquisition must have been sequential, never overlapping.
    generations = [o.generation for o in held]
    assert len(set(generations)) == len(generations)


# --------------------------------------------------------------------------
# release and renewal
# --------------------------------------------------------------------------

def test_release_allows_reacquisition(worktree):
    first = wl.acquire_worktree_lease(worktree, purpose="first")
    wl.release_worktree_lease(worktree, first.owner_token, first.lease_id)

    second = wl.acquire_worktree_lease(worktree, purpose="next")
    try:
        assert second.lease_id != first.lease_id
        assert second.generation > first.generation
    finally:
        wl.release_worktree_lease(worktree, second.owner_token, second.lease_id)


def test_release_without_token_is_rejected(worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="owned")
    try:
        with pytest.raises(RuntimeError, match="mandatory"):
            wl.release_worktree_lease(worktree)
    finally:
        wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id)


def test_release_with_wrong_token_is_rejected(worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="owned")
    try:
        with pytest.raises(RuntimeError, match="owner token does not match"):
            wl.release_worktree_lease(worktree, "not-my-lease-id")
    finally:
        wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id)


def test_release_twice_fails_the_second_time(worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="twice")
    assert wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id) is True
    with pytest.raises(RuntimeError):
        wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id)


def test_stale_generation_cannot_release_the_successor(worktree):
    stale = wl.acquire_worktree_lease(worktree, purpose="old")
    path = _lease_path_for(worktree)
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update({"lease_id": "b-lease", "owner_token": "b-token", "generation": 999})
    path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(RuntimeError):
        wl.release_worktree_lease(worktree, stale.owner_token, stale.lease_id)
    assert json.loads(path.read_text(encoding="utf-8"))["owner_token"] == "b-token"


def test_renew_extends_the_lease(worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="renew", lease_minutes=1)
    try:
        renewed = wl.renew_worktree_lease(
            worktree, lease.owner_token, lease.lease_id, lease_minutes=120
        )
        assert renewed.expires_at > lease.expires_at
        assert renewed.generation == lease.generation
    finally:
        wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id)


def test_renew_requires_the_exact_token(worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="renew")
    try:
        with pytest.raises(RuntimeError):
            wl.renew_worktree_lease(worktree, "bogus")
    finally:
        wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id)


# --------------------------------------------------------------------------
# expiry semantics
# --------------------------------------------------------------------------

def test_expired_but_live_holder_is_not_stolen(worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="live")
    try:
        path = _lease_path_for(worktree)
        record = json.loads(path.read_text(encoding="utf-8"))
        record["expires_at"] = "2020-01-01T00:00:00Z"
        path.write_text(json.dumps(record), encoding="utf-8")

        with pytest.raises(RuntimeError, match="not reclaimable"):
            wl.acquire_worktree_lease(worktree, purpose="steal")
    finally:
        wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id)


def test_expired_with_dead_holder_is_reclaimed(worktree):
    _plant_lease(worktree, holder_pid=999999, expires_at="2020-01-01T00:00:00Z")

    lease = wl.acquire_worktree_lease(worktree, purpose="after death")
    try:
        assert lease.purpose == "after death"
    finally:
        wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id)


# --------------------------------------------------------------------------
# malformed evidence
# --------------------------------------------------------------------------

def test_corrupt_lease_blocks_with_an_actionable_error(worktree):
    """Phase 5: a malformed record blocks and is recoverable, not silently erased."""
    lease_path = _lease_path_for(worktree)
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease_path.write_text("{ truncated json", encoding="utf-8")

    with pytest.raises(wl.MalformedLeaseError, match="BLOCKED_MALFORMED_LEASE"):
        wl.acquire_worktree_lease(worktree, purpose="after corruption")
    assert lease_path.read_text(encoding="utf-8") == "{ truncated json"


def test_malformed_lease_has_an_operator_recovery_path(worktree):
    lease_path = _lease_path_for(worktree)
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease_path.write_text("{ truncated json", encoding="utf-8")

    record = wl.recover_malformed_lease(
        worktree, worktree, "operator@example.invalid", "verified corrupt"
    )
    assert record["recovered"] is True
    assert len(record["removed_sha256"]) == 64
    assert record["operator"] == "operator@example.invalid"
    assert record["recovered_at"]
    assert not lease_path.exists()


# --------------------------------------------------------------------------
# listing and cleanup
# --------------------------------------------------------------------------

def test_list_is_empty_by_default(tmp_path):
    assert wl.list_worktree_leases(tmp_path / "does-not-exist") == []


def test_list_reports_acquired_roots(tmp_path):
    """Listing spans one repository's shared namespace.

    The two worktrees must belong to the SAME repository: separate repositories
    correctly get separate namespaces, which is what the exclusion below checks.
    """
    repo = tmp_path / "shared_repo"
    repo.mkdir()
    _git("init", cwd=repo)
    _git("commit", "--allow-empty", "-m", "init", cwd=repo)

    roots = []
    for name in ("lt_a", "lt_b"):
        root = tmp_path / name
        _git("worktree", "add", str(root), "-b", name, cwd=repo)
        roots.append(root)

    a = wl.acquire_worktree_lease(roots[0], purpose="a")
    b = wl.acquire_worktree_lease(roots[1], purpose="b")
    try:
        found = wl.list_worktree_leases(repo)
        ids = {lease.lease_id for lease in found}
        assert {a.lease_id, b.lease_id} <= ids
    finally:
        wl.release_worktree_lease(roots[0], a.owner_token, a.lease_id)
        wl.release_worktree_lease(roots[1], b.owner_token, b.lease_id)


def test_separate_repositories_get_separate_namespaces(tmp_path):
    roots = []
    for name in ("iso_a", "iso_b"):
        root = tmp_path / name
        root.mkdir()
        _git("init", cwd=root)
        _git("commit", "--allow-empty", "-m", "init", cwd=root)
        roots.append(root)

    a = wl.acquire_worktree_lease(roots[0], purpose="a")
    b = wl.acquire_worktree_lease(roots[1], purpose="b")
    try:
        assert _lease_path_for(roots[0]) != _lease_path_for(roots[1])
        ids_in_a = {lease.lease_id for lease in wl.list_worktree_leases(roots[0])}
        ids_in_b = {lease.lease_id for lease in wl.list_worktree_leases(roots[1])}
        assert a.lease_id in ids_in_a and b.lease_id not in ids_in_a
        assert b.lease_id in ids_in_b and a.lease_id not in ids_in_b
    finally:
        wl.release_worktree_lease(roots[0], a.owner_token, a.lease_id)
        wl.release_worktree_lease(roots[1], b.owner_token, b.lease_id)


def test_cleanup_keeps_live_leases_and_removes_dead_ones(worktree):
    path = _lease_path_for(worktree)

    live = wl.acquire_worktree_lease(worktree, purpose="live")
    record = json.loads(path.read_text(encoding="utf-8"))
    record["expires_at"] = "2020-01-01T00:00:00Z"
    path.write_text(json.dumps(record), encoding="utf-8")

    assert wl.cleanup_expired_leases(worktree) == 0, "a live owner's lease must survive"
    assert path.exists()

    wl.release_worktree_lease(worktree, live.owner_token, live.lease_id)

    _plant_lease(worktree, holder_pid=999999, expires_at="2020-01-01T00:00:00Z")
    assert wl.cleanup_expired_leases(worktree) == 1
    assert not path.exists()


def test_cleanup_on_an_empty_namespace_removes_nothing(worktree):
    assert wl.cleanup_expired_leases(worktree) == 0


# --------------------------------------------------------------------------
# read helpers
# --------------------------------------------------------------------------

def test_read_lease_returns_none_when_absent(worktree):
    assert wl._read_lease(worktree) is None


def test_read_lease_raises_for_unparsable_json(worktree):
    lease_path = _lease_path_for(worktree)
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease_path.write_text("not json at all", encoding="utf-8")

    with pytest.raises(wl.MalformedLeaseError):
        wl._read_lease(worktree)


def test_read_lease_roundtrips_a_written_lease(worktree):
    wl._write_lease(
        wl.WorktreeLease(worktree_root=str(worktree.resolve()), purpose="readback")
    )

    loaded = wl._read_lease(worktree)

    assert loaded is not None
    assert loaded.purpose == "readback"


def test_remove_lease_is_idempotent(worktree):
    wl.acquire_worktree_lease(worktree, purpose="remove")

    wl._remove_lease(worktree)
    wl._remove_lease(worktree)

    assert not _lease_path_for(worktree).exists()


# --------------------------------------------------------------------------
# read_only_session() interaction
# --------------------------------------------------------------------------

def test_read_only_session_helper_is_exposed_by_the_module():
    assert callable(wl.read_only_session)


def test_read_only_session_reads_the_environment(monkeypatch):
    monkeypatch.setenv("READ_ONLY_SESSION", "1")
    assert wl.read_only_session() is True


def test_acquire_still_succeeds_under_read_only_session(worktree, monkeypatch):
    """Documents real behaviour: the helper is imported but not consulted.

    Out of Phase 5 scope (a session-policy gate, not lock authority); tracked
    separately rather than changed here.
    """
    monkeypatch.setenv("READ_ONLY_SESSION", "1")

    lease = wl.acquire_worktree_lease(worktree, purpose="read only session")

    assert lease.status == "active"
    wl.release_worktree_lease(worktree, lease.owner_token, lease.lease_id)


@pytest.mark.xfail(
    strict=True,
    reason="GAP-052 known bug, out of Phase 5 scope: worktree_lock imports "
           "read_only_session but never calls it, so a READ_ONLY_SESSION process "
           "can still take a mutation lease. Phase 5 hardened lock authority "
           "(liveness, identity, fencing, ABA, malformed policy) and deliberately "
           "did not change session policy.",
)
def test_acquire_is_refused_under_read_only_session(worktree, monkeypatch):
    monkeypatch.setenv("READ_ONLY_SESSION", "1")

    with pytest.raises(RuntimeError):
        wl.acquire_worktree_lease(worktree, purpose="should be refused")