"""Unit coverage for the repository-global shared-Git-metadata lock.

`common_git_lock` keeps its lock under the repository's **common** Git
directory, resolved by Git itself, so a main checkout and every linked worktree
contend on one file. Every test here builds a real throwaway repository under
`tmp_path`; no test ever points at the real repository or its `.agent_locks`.

Phase 5 changed release to require an exact owner token, stopped expiry and
uncertain liveness from authorising a steal, and made malformed evidence block.
Tests that previously pinned those defective behaviours were rewritten; see
`test_single_writer_authority.py` for the cross-platform property suite.
"""
import calendar
import hashlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from ultimate_pipeline.governance.single_writer import common_git_lock as cgl
from ultimate_pipeline.governance.single_writer import process_identity as pi


class _OffsetTime:
    """Stand-in for the stdlib `time` module with controlled mktime semantics.

    Expiry must be computed in pure UTC. This shim resolves `mktime()` with the
    offset matching `tm_isdst` exactly like a real DST-active host, so a return
    to local-time conversion is caught.
    """

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
    monkeypatch.setattr(cgl, "time", _OffsetTime(0, 0))


def _git(*args, cwd):
    return subprocess.run(
        ["git", "-c", "user.email=test@example.invalid",
         "-c", "user.name=GAP052 Test",
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
def linked_worktree(repo, tmp_path):
    path = tmp_path / "wt_linked"
    _git("worktree", "add", str(path), "-b", "linked", cwd=repo)
    return path


def _lock_path(repo_root):
    return cgl._get_common_git_lock_path(repo_root)


def _read_raw(repo_root):
    return json.loads(_lock_path(repo_root).read_text(encoding="utf-8"))


def _plant(repo_root, **overrides):
    """Write a lock file directly, bypassing acquire's guards."""
    lock = cgl.CommonGitLock(
        repo_root=str(Path(repo_root).resolve()), operation="planted",
    )
    for key, value in overrides.items():
        setattr(lock, key, value)
    cgl._write_lock(lock)
    return lock


@pytest.fixture()
def release_guard():
    """Yield a helper that releases with the exact token."""
    created = []

    def track(lock):
        created.append(lock)
        return lock

    yield track
    for lock in created:
        try:
            cgl.release_common_git_lock(Path(lock.repo_root), lock.owner_token, lock.lock_id)
        except RuntimeError:
            pass


# --------------------------------------------------------------------------
# lock file location
# --------------------------------------------------------------------------

def test_lock_lives_inside_the_git_dir(repo):
    lock = cgl.acquire_common_git_lock(repo, "git status")
    try:
        assert _lock_path(repo).exists()
        assert _lock_path(repo).is_relative_to(repo.resolve() / ".git")
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_lock_path_is_shared_by_every_worktree_of_the_repo(repo, linked_worktree):
    assert _lock_path(repo) == _lock_path(linked_worktree)


def test_lock_path_helper_rejects_a_non_repository(tmp_path):
    with pytest.raises(RuntimeError, match="Not a Git repository"):
        cgl._get_common_git_lock_path(tmp_path / "not-a-repo")


# --------------------------------------------------------------------------
# acquire
# --------------------------------------------------------------------------

def test_acquire_returns_an_active_lock(repo):
    lock = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        assert lock.status == "active"
        assert lock.operation == "git fetch"
        assert lock.lock_id
        assert lock.owner_token
        assert lock.generation >= 1
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_acquire_rejects_a_non_repository(tmp_path):
    with pytest.raises(RuntimeError, match="Not a Git repository"):
        cgl.acquire_common_git_lock(tmp_path / "not-a-repo", "git fetch")


def test_lock_file_records_process_identity(repo):
    """Process identity comes from the OS, not from the acquisition stamp."""
    lock = cgl.acquire_common_git_lock(repo, "git push")
    try:
        data = _read_raw(repo)
        assert data["schema"] == cgl.SCHEMA_VERSION
        assert data["operation"] == "git push"
        assert data["holder_pid"] == os.getpid()
        assert data["holder_ppid"] == os.getppid()
        assert data["holder_cmdline"]
        assert data["acquired_at"]
        assert data["holder_start_identity"]
        assert data["holder_start_identity"] != data["acquired_at"]
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_lock_json_exposes_the_documented_field_set(repo):
    lock = cgl.acquire_common_git_lock(repo, "git gc")
    try:
        assert set(lock.to_json()) == {
            "schema", "status", "lock_id", "owner_token", "generation",
            "acquired_at", "expires_at", "holder_pid", "holder_ppid",
            "holder_cmdline", "holder_start_identity", "operation", "repo_root",
        }
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_lock_json_roundtrip_preserves_fields(repo):
    original = cgl.acquire_common_git_lock(repo, "git repack")
    try:
        restored = cgl.CommonGitLock.from_json(original.to_json())
        assert restored.to_json() == original.to_json()
    finally:
        cgl.release_common_git_lock(repo, original.owner_token, original.lock_id)


def test_from_json_defaults_missing_fields():
    restored = cgl.CommonGitLock.from_json({"lock_id": "abc"})
    assert restored.lock_id == "abc"
    assert restored.schema == cgl.SCHEMA_VERSION
    assert restored.status == "active"
    assert restored.holder_pid == 0
    assert restored.operation == ""


def test_from_json_reads_the_legacy_start_field():
    """Records written before Phase 5 carried holder_start_utc."""
    restored = cgl.CommonGitLock.from_json(
        {"lock_id": "abc", "holder_start_utc": "2020-01-01T00:00:00Z"}
    )
    assert restored.holder_start_identity == "2020-01-01T00:00:00Z"


def test_timeout_seconds_sets_the_expiry(repo):
    lock = cgl.acquire_common_git_lock(repo, "git fetch", timeout_seconds=45)
    try:
        delta = calendar.timegm(time.strptime(lock.expires_at, "%Y-%m-%dT%H:%M:%SZ")) - time.time()
        assert delta == pytest.approx(45, abs=5)
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_default_timeout_is_five_minutes():
    assert cgl.DEFAULT_TIMEOUT_SECONDS == 300


_DST_ACTIVE_ZONES = [
    pytest.param(3600, 7200, id="europe-cest"),
    pytest.param(-18000, -14400, id="us-eastern-edt"),
]


@pytest.mark.parametrize("std_east, dst_east", _DST_ACTIVE_ZONES)
def test_is_expired_in_dst_active_zone_regression(monkeypatch, std_east, dst_east):
    monkeypatch.setattr(cgl, "time", _OffsetTime(std_east_seconds=std_east, dst_east_seconds=dst_east))
    now = time.time()
    future = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 600))
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 600))

    assert cgl.CommonGitLock(expires_at=future).is_expired() is False
    assert cgl.CommonGitLock(expires_at=past).is_expired() is True


def test_unparsable_expiry_is_not_treated_as_expired():
    """A damaged expiry is not proof of death and must not authorise a steal."""
    assert cgl.CommonGitLock(expires_at="not-a-date").is_expired() is False


def test_default_timeout_lock_is_not_stolen_while_held(repo):
    first = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        with pytest.raises(RuntimeError, match="Common Git lock held by"):
            cgl.acquire_common_git_lock(repo, "git push")
    finally:
        cgl.release_common_git_lock(repo, first.owner_token, first.lock_id)


def test_second_acquire_while_held_is_refused(repo):
    first = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        with pytest.raises(RuntimeError, match="not reclaimable"):
            cgl.acquire_common_git_lock(repo, "git push")
    finally:
        cgl.release_common_git_lock(repo, first.owner_token, first.lock_id)


def test_refused_acquire_does_not_disturb_the_holder(repo):
    first = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        with pytest.raises(RuntimeError):
            cgl.acquire_common_git_lock(repo, "git push")
        assert _read_raw(repo)["lock_id"] == first.lock_id
    finally:
        cgl.release_common_git_lock(repo, first.owner_token, first.lock_id)


def test_timeout_is_not_actually_waited_out(repo):
    first = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        started = time.monotonic()
        with pytest.raises(RuntimeError):
            cgl.acquire_common_git_lock(repo, "git push", timeout_seconds=30)
        elapsed = time.monotonic() - started
    finally:
        cgl.release_common_git_lock(repo, first.owner_token, first.lock_id)

    assert elapsed < 5, f"expected an immediate refusal, waited {elapsed:.1f}s"


# --------------------------------------------------------------------------
# stale lock handling
# --------------------------------------------------------------------------

def test_lock_held_by_a_dead_process_is_reclaimed(repo):
    _plant(repo, holder_pid=999999, operation="crashed git gc")

    lock = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        assert lock.operation == "git fetch"
        assert _read_raw(repo)["lock_id"] == lock.lock_id
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_expired_lock_with_a_live_owner_is_not_stolen(repo):
    """Phase 5: expiry alone no longer authorises a steal from a live owner."""
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    _plant(
        repo, expires_at=past, holder_pid=os.getpid(), operation="overrun",
        holder_start_identity=pi.process_start_identity(os.getpid()) or "",
    )

    with pytest.raises(RuntimeError, match="not reclaimable"):
        cgl.acquire_common_git_lock(repo, "git fetch")


def test_expired_lock_with_a_dead_owner_is_stolen(repo):
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    _plant(repo, expires_at=past, holder_pid=999999, operation="overrun")

    lock = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        assert lock.operation == "git fetch"
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_released_status_lock_does_not_block(repo):
    _plant(repo, status="released", expires_at="", holder_pid=os.getpid())

    lock = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        assert lock.status == "active"
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_malformed_lock_blocks_instead_of_being_discarded(repo):
    """Phase 5: corrupt evidence is never silently erased by acquisition."""
    lock_path = _lock_path(repo)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("{ truncated", encoding="utf-8")

    with pytest.raises(cgl.MalformedLockError, match="BLOCKED_MALFORMED_LOCK"):
        cgl.acquire_common_git_lock(repo, "git fetch")
    assert lock_path.read_text(encoding="utf-8") == "{ truncated"


# --------------------------------------------------------------------------
# release
# --------------------------------------------------------------------------

def test_release_removes_the_lock_file(repo):
    lock = cgl.acquire_common_git_lock(repo, "git fetch")

    assert cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id) is True
    assert not _lock_path(repo).exists()


def test_release_allows_reacquisition(repo):
    first = cgl.acquire_common_git_lock(repo, "git fetch")
    assert cgl.release_common_git_lock(repo, first.owner_token, first.lock_id) is True

    second = cgl.acquire_common_git_lock(repo, "git push")
    try:
        assert second.lock_id != first.lock_id
        assert second.generation > first.generation
    finally:
        cgl.release_common_git_lock(repo, second.owner_token, second.lock_id)


def test_release_requires_a_token(repo):
    lock = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        with pytest.raises(RuntimeError, match="mandatory"):
            cgl.release_common_git_lock(repo)
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_release_rejects_a_mismatched_lock_id(repo):
    lock = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        with pytest.raises(RuntimeError):
            cgl.release_common_git_lock(repo, lock.owner_token, "not-my-lock-id")
        assert _read_raw(repo)["lock_id"] == lock.lock_id
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_release_removes_no_tombstone_left_behind(repo):
    lock = cgl.acquire_common_git_lock(repo, "git fetch")
    cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)

    leftovers = list(lock_path(repo).parent.glob("*.tombstone"))
    assert leftovers == []


def lock_path(repo_root):
    return _lock_path(repo_root)


# --------------------------------------------------------------------------
# context manager
# --------------------------------------------------------------------------

def test_context_manager_releases_on_clean_exit(repo):
    with cgl.common_git_lock(repo, "git fetch") as lock:
        held_id = lock.lock_id
        assert _lock_path(repo).exists()

    assert not _lock_path(repo).exists()
    assert cgl.get_lock_status(repo)["status"] == "unlocked"
    assert held_id


def test_context_manager_releases_on_exception(repo):
    with pytest.raises(ValueError):
        with cgl.common_git_lock(repo, "git fetch"):
            raise ValueError("boom")

    assert not _lock_path(repo).exists()


def test_context_manager_propagates_acquire_failure(repo):
    first = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        with pytest.raises(RuntimeError):
            with cgl.common_git_lock(repo, "git push"):
                pytest.fail("body must not run")
    finally:
        cgl.release_common_git_lock(repo, first.owner_token, first.lock_id)


# --------------------------------------------------------------------------
# get_lock_status
# --------------------------------------------------------------------------

def test_status_is_unlocked_without_a_lock(repo):
    assert cgl.get_lock_status(repo) == {"status": "unlocked", "lock_id": None}


def test_status_is_active_for_a_live_unexpired_holder(repo):
    lock = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        status = cgl.get_lock_status(repo)
        assert status["status"] == "active"
        assert status["lock_id"] == lock.lock_id
        assert status["holder_pid"] == os.getpid()
        assert status["operation"] == "git fetch"
        assert status["reclaimable"] is False
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


def test_status_is_stale_for_a_dead_holder(repo):
    _plant(repo, holder_pid=999999)
    assert cgl.get_lock_status(repo)["status"] == "stale"


def test_status_is_stale_for_an_expired_dead_lock(repo):
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    _plant(repo, expires_at=past, holder_pid=999999)

    status = cgl.get_lock_status(repo)
    assert status["status"] == "stale"
    assert status["lock_id"]


def test_status_reports_a_released_tombstone_verbatim(repo):
    _plant(repo, status="released", expires_at="")
    assert cgl.get_lock_status(repo)["status"] == "released"


def test_status_is_blocked_for_a_malformed_lock(repo):
    lock_path = _lock_path(repo)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("{ truncated", encoding="utf-8")

    status = cgl.get_lock_status(repo)
    assert status["status"] == "BLOCKED_MALFORMED_LOCK"
    assert status["detail"]


# --------------------------------------------------------------------------
# fail-closed compatibility wrapper
# --------------------------------------------------------------------------

def test_holder_alive_wrapper_is_fail_closed(repo):
    """UNKNOWN must read as 'not reclaimable' through the boolean wrapper."""
    unknown = cgl.CommonGitLock(holder_pid=0)
    assert cgl._is_lock_holder_alive(unknown) is True

    dead = cgl.CommonGitLock(holder_pid=999999)
    assert cgl._is_lock_holder_alive(dead) is False

    alive = cgl.CommonGitLock(
        holder_pid=os.getpid(),
        holder_start_identity=pi.process_start_identity(os.getpid()) or "",
    )
    assert cgl._is_lock_holder_alive(alive) is True


# --------------------------------------------------------------------------
# read helpers
# --------------------------------------------------------------------------

def test_read_lock_returns_none_when_absent(repo):
    assert cgl._read_lock(repo) is None


def test_read_lock_raises_for_unparsable_json(repo):
    lock_path = _lock_path(repo)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("not json at all", encoding="utf-8")

    with pytest.raises(cgl.MalformedLockError):
        cgl._read_lock(repo)


def test_remove_lock_is_idempotent(repo):
    cgl.acquire_common_git_lock(repo, "git fetch")

    cgl._remove_lock(repo)
    cgl._remove_lock(repo)

    assert not _lock_path(repo).exists()


# --------------------------------------------------------------------------
# read_only_session() interaction
# --------------------------------------------------------------------------

def test_common_git_lock_has_no_read_only_session_gate(repo, monkeypatch):
    """Real behaviour: common_git_lock never consults READ_ONLY_SESSION."""
    monkeypatch.setenv("READ_ONLY_SESSION", "1")

    assert not hasattr(cgl, "read_only_session")
    lock = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        assert lock.status == "active"
    finally:
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)


# ---------------------------------------------------------------------------
# Windows claim-by-rename: a concurrent reader must not abort a release.
# On Windows `os.replace` is denied (WinError 32) while any other handle holds
# the published record open without FILE_SHARE_DELETE, so a claim that lost that
# race used to surface as "the published lock changed while releasing" -- a
# misleading refusal of a perfectly legitimate release. It must instead retry.
# ---------------------------------------------------------------------------


def test_claim_survives_a_concurrent_reader_holding_the_lock_open(repo):
    """A brief concurrent reader must not abort the claim.

    A competing acquirer reads the published record while deciding whether it
    may reclaim. On Windows that open handle denies the owner's rename
    (WinError 32); the claim must retry and succeed once the reader is done
    rather than surfacing a misleading "the lock changed" refusal.
    """
    cgl.acquire_common_git_lock(repo, "incumbent")
    path = _lock_path(repo)
    before = path.read_bytes()

    reader = open(path, "rb")

    def release_reader():
        time.sleep(0.05)          # a read is short-lived, unlike a hung holder
        reader.close()

    threading.Thread(target=release_reader, daemon=True).start()
    claimed, tomb = cgl._claim_by_rename(repo, "release", lambda raw: raw == before)

    assert claimed is True, "a transient reader must not abort the claim"
    assert tomb is not None
    tomb.unlink()

    again = cgl.acquire_common_git_lock(repo, "after")
    cgl.release_common_git_lock(repo, again.owner_token, again.lock_id)


@pytest.mark.skipif(os.name != "nt", reason="WinError 32 is Windows-specific")
def test_release_is_not_refused_merely_because_a_reader_is_open(repo):
    """End-to-end: release succeeds while a short-lived reader holds the lock."""
    incumbent = cgl.acquire_common_git_lock(repo, "incumbent")
    path = _lock_path(repo)
    reader = open(path, "rb")

    def release_reader():
        time.sleep(0.05)
        reader.close()

    threading.Thread(target=release_reader, daemon=True).start()
    cgl.release_common_git_lock(repo, incumbent.owner_token, incumbent.lock_id)
    reader.close()
    assert not path.exists()


@pytest.mark.skipif(os.name != "nt", reason="WinError 32 is Windows-specific")
def test_release_reports_a_persistent_rename_denial_accurately(repo, monkeypatch):
    """A denied rename is not a changed owner and must not be reported as one.

    When a reader holds the record open past the retry budget the rename never
    happens, so the published generation is unchanged. Claiming it "changed"
    would be false evidence; the refusal must say what actually happened and
    leave the live record intact and releasable.
    """
    incumbent = cgl.acquire_common_git_lock(repo, "incumbent")
    path = _lock_path(repo)
    monkeypatch.setattr(cgl, "_CLAIM_RENAME_RETRY_S", 0.05)
    monkeypatch.setattr(cgl, "_CLAIM_RENAME_RETRY_DELAY_S", 0.01)

    reader = open(path, "rb")
    try:
        with pytest.raises(RuntimeError) as excinfo:
            cgl.release_common_git_lock(
                repo, incumbent.owner_token, incumbent.lock_id)
    finally:
        reader.close()

    message = str(excinfo.value)
    assert "could not be claimed" in message
    assert "changed while releasing" not in message
    assert path.exists(), "the live record must survive a denied rename"
    assert cgl.release_common_git_lock(
        repo, incumbent.owner_token, incumbent.lock_id) is True


def test_claim_restore_never_clobbers_a_concurrent_successor(repo, monkeypatch):
    """Restoring non-matching bytes must not overwrite a new owner's record.

    A successor that publishes while a claim is in flight must keep its record:
    replacing it would destroy a live owner's evidence, which is precisely what
    this module exists to prevent.
    """
    path = _lock_path(repo)
    cgl._write_lock(cgl.CommonGitLock(
        repo_root=str(repo), operation="incumbent", generation=7,
        holder_pid=os.getpid(), holder_ppid=os.getpid(),
        holder_cmdline="pytest", holder_start_identity="x",
        expires_at="2999-01-01T00:00:00Z",
    ))

    real_durable_replace = cgl._durable_replace
    successor_bytes = json.dumps(
        {"lock_id": "successor", "owner_token": "t", "generation": 8}
    ).encode("utf-8")
    injected = {"done": False}

    def replace_and_publish_a_successor(src, dst):
        real_durable_replace(src, dst)
        # The claim has just moved the published record away; a successor
        # publishes into the window before the claim inspects the path.
        if not injected["done"] and Path(dst).name.endswith(".tombstone"):
            injected["done"] = True
            path.write_bytes(successor_bytes)

    monkeypatch.setattr(cgl, "_durable_replace", replace_and_publish_a_successor)
    claimed, tomb = cgl._claim_by_rename(repo, "reclaim", lambda raw: False)
    monkeypatch.undo()

    assert claimed is False
    assert path.read_bytes() == successor_bytes, "successor record was clobbered"
    assert tomb is not None and Path(tomb).exists(), \
        "displaced evidence must be preserved as a tombstone"
    Path(tomb).unlink()
    path.unlink()


def test_failed_tombstone_restore_blocks_acquisition_and_preserves_evidence(
    repo, monkeypatch
):
    """An un-restorable displaced generation must block fresh publication."""
    from ultimate_pipeline.governance.single_writer import common_git_lock as cgl

    original_lock = cgl.acquire_common_git_lock(repo, "git test", timeout_seconds=2)
    path = cgl._get_common_git_lock_path(repo)
    original = path.read_bytes()
    # Make the audited bytes fail the predicate, then deny only the restore.
    # The production path must stop instead of treating the now-absent final
    # pathname as an empty namespace and publishing a new owner over the gap.
    original_durable_replace = cgl._durable_replace
    moved = {"tomb": None}

    def fail_tombstone_restore(source, destination):
        source = Path(source)
        destination = Path(destination)
        if destination == path and source.name.endswith(".tombstone"):
            moved["tomb"] = source
            raise PermissionError("injected restore denial")
        result = original_durable_replace(source, destination)
        if destination.name.endswith(".tombstone"):
            moved["tomb"] = destination
        return result

    monkeypatch.setattr(cgl, "_durable_replace", fail_tombstone_restore)
    with pytest.raises(RuntimeError, match="restore"):
        cgl._claim_by_rename(repo, "adversarial", lambda raw: False)

    # The complete original lock must remain recoverable under the tombstone,
    # and the failed claim must not publish another generation.
    assert moved["tomb"] is not None and moved["tomb"].exists()
    assert moved["tomb"].read_bytes() == original
    assert not path.exists()

    status = cgl.get_lock_status(repo)
    assert status["status"] == "BLOCKED_UNRESOLVED_TOMBSTONE"
    assert status["unresolved_tombstones"][0]["sha256"] == hashlib.sha256(
        original
    ).hexdigest()

    # The acquisition path must surface uncertainty instead of publishing.
    with pytest.raises(RuntimeError, match="unresolved"):
        cgl.acquire_common_git_lock(repo, "git retry", timeout_seconds=1)
    assert not path.exists()
    assert moved["tomb"].read_bytes() == original

    with pytest.raises(ValueError, match="operator identity"):
        cgl.recover_unresolved_tombstone(
            repo, moved["tomb"].name, "", "verified recovery", hashlib.sha256(original).hexdigest()
        )
    with pytest.raises(RuntimeError, match="SHA-256"):
        cgl.recover_unresolved_tombstone(
            repo, moved["tomb"].name, "operator", "verified recovery", "0" * 64
        )
    assert moved["tomb"].read_bytes() == original

    recovery = cgl.recover_unresolved_tombstone(
        repo,
        moved["tomb"].name,
        "operator@example.invalid",
        "restore displaced generation after digest verification",
        hashlib.sha256(original).hexdigest(),
    )
    assert recovery["recovered"] is True
    assert recovery["intent_status"] == "COMPLETE"
    assert Path(recovery["recovery_record_path"]).is_file()
    assert path.read_bytes() == original
    assert not moved["tomb"].exists()
    assert cgl.get_lock_status(repo)["status"] == "active"
    assert cgl.release_common_git_lock(
        repo, original_lock.owner_token, original_lock.lock_id
    ) is True
    successor = cgl.acquire_common_git_lock(repo, "git after recovery", timeout_seconds=2)
    assert cgl.release_common_git_lock(
        repo, successor.owner_token, successor.lock_id
    ) is True


def test_tombstone_recovery_retries_after_crash_between_link_and_cleanup(repo, monkeypatch):
    from ultimate_pipeline.governance.single_writer import common_git_lock as cgl

    original_lock = cgl.acquire_common_git_lock(repo, "git test", timeout_seconds=2)
    path = cgl._get_common_git_lock_path(repo)
    tomb = path.with_name(f"{path.name}.crash-fixture.tombstone")
    raw = path.read_bytes()
    path.unlink()
    tomb.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    original_link = cgl.os.link
    injected = {"raised": False}

    def link_then_crash(source, destination):
        result = original_link(source, destination)
        if Path(destination) == path and not injected["raised"]:
            injected["raised"] = True
            raise OSError("injected crash after atomic link")
        return result

    monkeypatch.setattr(cgl.os, "link", link_then_crash)
    with pytest.raises(OSError, match="crash after atomic link"):
        cgl.recover_unresolved_tombstone(
            repo, tomb.name, "operator", "fault test", digest
        )
    assert path.read_bytes() == raw
    assert tomb.read_bytes() == raw
    assert cgl.get_lock_status(repo)["status"] == "BLOCKED_UNRESOLVED_TOMBSTONE"

    monkeypatch.setattr(cgl.os, "link", original_link)
    recovered = cgl.recover_unresolved_tombstone(
        repo, tomb.name, "operator", "retry after verified interrupted recovery", digest
    )
    assert recovered["recovered"] is True
    assert path.read_bytes() == raw
    assert not tomb.exists()
    assert cgl.release_common_git_lock(
        repo, original_lock.owner_token, original_lock.lock_id
    ) is True


def test_tombstone_recovery_rejects_path_escape_and_corrupted_record(repo):
    from ultimate_pipeline.governance.single_writer import common_git_lock as cgl

    path = cgl._get_common_git_lock_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    tomb = path.with_name(f"{path.name}.corrupt.tombstone")
    tomb.write_bytes(b"tampered")
    digest = hashlib.sha256(b"expected original").hexdigest()
    with pytest.raises(ValueError, match="namespace"):
        cgl.recover_unresolved_tombstone(
            repo, "..\\outside.tombstone", "operator", "test", digest
        )
    with pytest.raises(RuntimeError, match="SHA-256"):
        cgl.recover_unresolved_tombstone(
            repo, tomb.name, "operator", "test", digest
        )
    assert tomb.read_bytes() == b"tampered"
    assert not path.exists()


def test_tombstone_recovery_rejects_inode_replacement_before_read(repo, monkeypatch):
    path = cgl._get_common_git_lock_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    tomb = path.with_name(f"{path.name}.inode-race.tombstone")
    replacement = path.with_name("attacker-replacement.bin")
    tomb.write_bytes(b"original lock evidence")
    replacement.write_bytes(b"different replacement bytes")
    expected = hashlib.sha256(b"original lock evidence").hexdigest()
    original_open = cgl.os.open
    swapped = False

    def replace_before_open(filename, flags, *args, **kwargs):
        nonlocal swapped
        if Path(filename) == tomb and not swapped:
            swapped = True
            cgl.os.replace(replacement, tomb)
        return original_open(filename, flags, *args, **kwargs)

    monkeypatch.setattr(cgl.os, "open", replace_before_open)
    with pytest.raises(RuntimeError, match="changed while opening"):
        cgl.recover_unresolved_tombstone(
            repo, tomb.name, "operator", "inode race test", expected
        )
    assert swapped
    assert tomb.read_bytes() == b"different replacement bytes"
    assert not path.exists()


def test_tombstone_recovery_symlink_swap_is_not_read_or_linked(repo, monkeypatch):
    path = cgl._get_common_git_lock_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    tomb = path.with_name(f"{path.name}.symlink-race.tombstone")
    external = path.parent.parent / "external-lock-target.bin"
    tomb.write_bytes(b"original lock evidence")
    external.write_bytes(b"external secret bytes")
    expected = hashlib.sha256(b"original lock evidence").hexdigest()
    try:
        tomb.unlink()
        tomb.symlink_to(external)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable in this Windows environment: {exc}")
    # Start with a regular path for the lstat and swap it to a symlink exactly
    # at the open boundary. If the implementation follows it, the descriptor
    # identity differs and no stream read or publication is allowed.
    tomb.unlink()
    tomb.write_bytes(b"original lock evidence")
    original_open = cgl.os.open
    original_fdopen = cgl.os.fdopen
    swapped = False
    reads = []

    class ReadTracker:
        def __init__(self, wrapped):
            self.wrapped = wrapped

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.wrapped.__exit__(*args)

        def fileno(self):
            return self.wrapped.fileno()

        def read(self, count=-1):
            reads.append(count)
            return self.wrapped.read(count)

    def swap_to_symlink_before_open(filename, flags, *args, **kwargs):
        nonlocal swapped
        if Path(filename) == tomb and not swapped:
            swapped = True
            tomb.unlink()
            tomb.symlink_to(external)
        return original_open(filename, flags, *args, **kwargs)

    monkeypatch.setattr(cgl.os, "open", swap_to_symlink_before_open)
    monkeypatch.setattr(
        cgl.os, "fdopen", lambda fd, *a, **kw: ReadTracker(original_fdopen(fd, *a, **kw))
    )
    with pytest.raises(RuntimeError, match="changed while opening"):
        cgl.recover_unresolved_tombstone(
            repo, tomb.name, "operator", "symlink race test", expected
        )
    assert swapped
    assert reads == []
    assert external.read_bytes() == b"external secret bytes"
    assert not path.exists()
    assert tomb.is_symlink()


def test_release_archive_failure_is_observable_and_preserves_tombstone(repo, monkeypatch):
    lock = cgl.acquire_common_git_lock(repo, "git release failure", timeout_seconds=2)
    path = cgl._get_common_git_lock_path(repo)
    original_replace = cgl._durable_replace

    def fail_archive(source, destination):
        source = Path(source)
        destination = Path(destination)
        if source.name.endswith(".tombstone") and ".released." in destination.name:
            raise PermissionError("injected release archive denial")
        return original_replace(source, destination)

    monkeypatch.setattr(cgl, "_durable_replace", fail_archive)
    with pytest.raises(RuntimeError, match="could not be durably finalized"):
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)

    tombstones = list(path.parent.glob(f"{path.name}.*.tombstone"))
    assert len(tombstones) == 1
    assert json.loads(tombstones[0].read_text(encoding="utf-8"))["lock_id"] == lock.lock_id
    assert cgl.get_lock_status(repo)["status"] == "BLOCKED_UNRESOLVED_TOMBSTONE"


def test_release_durability_failure_never_returns_success(repo, monkeypatch):
    lock = cgl.acquire_common_git_lock(repo, "git release fsync failure", timeout_seconds=2)
    path = cgl._get_common_git_lock_path(repo)
    raw = path.read_bytes()
    original_replace = cgl._durable_replace

    def replace_then_report_durability_failure(source, destination):
        source = Path(source)
        destination = Path(destination)
        result = original_replace(source, destination)
        if source.name.endswith(".tombstone") and ".released." in destination.name:
            raise RuntimeError("injected directory durability failure")
        return result

    monkeypatch.setattr(cgl, "_durable_replace", replace_then_report_durability_failure)
    with pytest.raises(RuntimeError, match="could not be durably finalized"):
        cgl.release_common_git_lock(repo, lock.owner_token, lock.lock_id)
    archives = list(path.parent.glob(f"{path.name}.released.*.json"))
    assert len(archives) == 1
    assert archives[0].read_bytes() == raw
    assert not path.exists()
