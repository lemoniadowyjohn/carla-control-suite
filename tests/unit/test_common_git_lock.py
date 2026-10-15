"""Unit coverage for GAP-052 shared Git metadata locks.

`common_git_lock` keeps its lock file at `<repo_root>/.git/.agent_locks/`,
where `repo_root` is a caller argument, so every test here builds a real
throwaway repository under `tmp_path`. No test ever points at the real
repository, its `.git`, or `.agent_locks/`.

The `_is_lock_holder_alive` Windows branch shells out to `tasklist`; those
tests stub `subprocess.run` and `platform.system` rather than invoking a
Windows-only binary, so the whole file collects and runs on ubuntu CI
(GAP-055).
"""
import calendar
import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ultimate_pipeline.governance.single_writer import common_git_lock as cgl


class _OffsetTime:
    """Stand-in for the stdlib `time` module with controlled mktime semantics.

    `is_expired()` compares `time.mktime(time.gmtime())` against
    `time.mktime(time.strptime(stamp))`. The two structs differ in
    `tm_isdst` (`gmtime()` yields 0, `strptime()` yields -1), so `mktime`
    resolves them against the host's standard and daylight rules
    respectively. On a host with active DST the sides are skewed against
    each other and every lock reads as expired one hour early. This shim
    pins both sides to the same offset so the suite is host-independent.
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
    """Force canonical UTC expiry arithmetic for every test in this module."""
    monkeypatch.setattr(cgl, "time", _OffsetTime(0, 0))


def _git(*args, cwd):
    result = subprocess.run(
        ["git", "-c", "user.email=test@example.invalid",
         "-c", "user.name=GAP052 Test",
         "-c", "init.defaultBranch=main", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return result


@pytest.fixture()
def repo(tmp_path):
    """A throwaway git repository with one commit."""
    root = tmp_path / "repo"
    root.mkdir()
    _git("init", cwd=root)
    _git("commit", "--allow-empty", "-m", "init", cwd=root)
    return root


@pytest.fixture()
def linked_worktree(repo, tmp_path):
    """A second worktree checked out from `repo`."""
    path = tmp_path / "wt_linked"
    _git("worktree", "add", str(path), "-b", "linked", cwd=repo)
    return path


@pytest.fixture()
def holder_appears_alive(monkeypatch):
    """Pretend any recorded lock holder is a live process."""
    monkeypatch.setattr(cgl, "_is_lock_holder_alive", lambda lock: True)


def _lock_path(repo_root):
    return Path(repo_root).resolve() / ".git" / ".agent_locks" / "common_git_lock.json"


def _read_raw(repo_root):
    return json.loads(_lock_path(repo_root).read_text(encoding="utf-8"))


def _plant_lock(repo_root, **overrides):
    """Write a lock file directly, bypassing acquire's guards."""
    lock = cgl.CommonGitLock(
        repo_root=str(Path(repo_root).resolve()),
        operation="planted",
        holder_pid=os.getpid(),
    )
    for key, value in overrides.items():
        setattr(lock, key, value)
    cgl._write_lock(lock)
    return lock


# --------------------------------------------------------------------------
# lock file location
# --------------------------------------------------------------------------

def test_lock_lives_inside_the_git_dir(repo):
    lock = cgl.acquire_common_git_lock(repo, "git status")

    try:
        assert lock.repo_root == str(repo.resolve())
        assert _lock_path(repo).exists()
    finally:
        cgl.release_common_git_lock(repo, lock.lock_id)


def test_lock_path_is_shared_by_every_worktree_of_the_repo(repo, linked_worktree):
    """The lock lives in the main .git, so all worktrees contend on it."""
    assert _lock_path(repo) == cgl._get_common_git_lock_path(repo)
    assert cgl._get_common_git_lock_path(repo).is_relative_to(repo.resolve() / ".git")


def test_lock_path_helper_rejects_a_non_repository(tmp_path):
    with pytest.raises(RuntimeError, match="Not a Git repository"):
        cgl._get_common_git_lock_path(tmp_path)


# --------------------------------------------------------------------------
# acquire
# --------------------------------------------------------------------------

def test_acquire_returns_an_active_lock(repo):
    lock = cgl.acquire_common_git_lock(repo, "git fetch")

    try:
        assert lock.status == "active"
        assert lock.operation == "git fetch"
        assert lock.lock_id
    finally:
        cgl.release_common_git_lock(repo, lock.lock_id)


def test_acquire_rejects_a_non_repository(tmp_path):
    with pytest.raises(RuntimeError, match="Not a Git repository"):
        cgl.acquire_common_git_lock(tmp_path, "git fetch")


def test_lock_file_records_process_identity(repo):
    lock = cgl.acquire_common_git_lock(repo, "git push")

    try:
        data = _read_raw(repo)
        assert data["schema"] == cgl.SCHEMA_VERSION
        assert data["operation"] == "git push"
        assert data["holder_pid"] == os.getpid()
        assert data["holder_ppid"] == os.getppid()
        assert data["holder_cmdline"]
        assert data["holder_start_utc"]
        assert data["acquired_at"]
    finally:
        cgl.release_common_git_lock(repo, lock.lock_id)


def test_lock_json_exposes_the_documented_field_set(repo):
    lock = cgl.acquire_common_git_lock(repo, "git gc")

    try:
        assert set(lock.to_json()) == {
            "schema", "status", "lock_id", "acquired_at", "expires_at",
            "holder_pid", "holder_ppid", "holder_cmdline", "holder_start_utc",
            "operation", "repo_root",
        }
    finally:
        cgl.release_common_git_lock(repo, lock.lock_id)


def test_lock_json_roundtrip_preserves_fields(repo):
    original = cgl.acquire_common_git_lock(repo, "git repack")

    try:
        restored = cgl.CommonGitLock.from_json(original.to_json())
        assert restored.to_json() == original.to_json()
    finally:
        cgl.release_common_git_lock(repo, original.lock_id)


def test_from_json_defaults_missing_fields():
    restored = cgl.CommonGitLock.from_json({"lock_id": "abc"})

    assert restored.lock_id == "abc"
    assert restored.schema == cgl.SCHEMA_VERSION
    assert restored.status == "active"
    assert restored.holder_pid == 0
    assert restored.operation == ""


def test_timeout_seconds_sets_the_expiry(repo):
    lock = cgl.acquire_common_git_lock(repo, "git fetch", timeout_seconds=45)

    try:
        delta = calendar.timegm(time.strptime(lock.expires_at, "%Y-%m-%dT%H:%M:%SZ")) - time.time()
        assert delta == pytest.approx(45, abs=5)
    finally:
        cgl.release_common_git_lock(repo, lock.lock_id)


def test_default_timeout_is_five_minutes():
    assert cgl.DEFAULT_TIMEOUT_SECONDS == 300


# GAP-052 regression: expiry must be computed in pure UTC. Each zone below has
# DST active (dst offset != std offset) and the shim resolves mktime() with the
# offset matching tm_isdst, exactly like a real DST-active host. Any return to
# local-time conversion (time.mktime) makes the future-600s case read expired.
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


def test_is_expired_is_timezone_independent(monkeypatch):
    monkeypatch.setattr(cgl, "time", _OffsetTime(std_east_seconds=3600, dst_east_seconds=7200))

    future = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 600))

    assert cgl.CommonGitLock(expires_at=future).is_expired() is False


def test_default_timeout_lock_is_not_stolen_while_held(repo, holder_appears_alive, monkeypatch):
    monkeypatch.setattr(cgl, "time", _OffsetTime(std_east_seconds=3600, dst_east_seconds=7200))
    first = cgl.acquire_common_git_lock(repo, "git fetch")

    try:
        with pytest.raises(RuntimeError, match="Common Git lock held by"):
            cgl.acquire_common_git_lock(repo, "git push")
    finally:
        cgl._remove_lock(repo)


def test_second_acquire_while_held_is_refused(repo, holder_appears_alive):
    first = cgl.acquire_common_git_lock(repo, "git fetch")

    try:
        with pytest.raises(RuntimeError, match="Common Git lock held by"):
            cgl.acquire_common_git_lock(repo, "git push")
    finally:
        cgl.release_common_git_lock(repo, first.lock_id)


def test_refused_acquire_does_not_disturb_the_holder(repo, holder_appears_alive):
    first = cgl.acquire_common_git_lock(repo, "git fetch")

    try:
        with pytest.raises(RuntimeError):
            cgl.acquire_common_git_lock(repo, "git push")
        assert _read_raw(repo)["lock_id"] == first.lock_id
    finally:
        cgl.release_common_git_lock(repo, first.lock_id)


def test_timeout_is_not_actually_waited_out(repo, holder_appears_alive):
    """Real behaviour: the call raises at once rather than blocking for the timeout.

    The docstring advertises `timeout_seconds` as the "maximum time to wait
    for lock acquisition", but the live-holder branch raises immediately.
    """
    first = cgl.acquire_common_git_lock(repo, "git fetch")

    try:
        started = time.monotonic()
        with pytest.raises(RuntimeError):
            cgl.acquire_common_git_lock(repo, "git push", timeout_seconds=30)
        elapsed = time.monotonic() - started
    finally:
        cgl.release_common_git_lock(repo, first.lock_id)

    assert elapsed < 5, f"expected an immediate refusal, waited {elapsed:.1f}s"


def test_concurrent_acquire_has_exactly_one_winner(repo, holder_appears_alive):
    outcomes = []
    barrier = threading.Barrier(4)

    def contender():
        barrier.wait()
        try:
            outcomes.append(cgl.acquire_common_git_lock(repo, "race"))
        except RuntimeError:
            outcomes.append(None)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for _ in range(4):
            pool.submit(contender)

    winners = [o for o in outcomes if o is not None]
    assert len(winners) == 1
    for loser in [o for o in outcomes if o is None]:
        assert loser is None
    cgl.release_common_git_lock(repo, winners[0].lock_id)


# --------------------------------------------------------------------------
# stale lock handling
# --------------------------------------------------------------------------

def test_lock_held_by_a_dead_process_is_stolen(repo, monkeypatch):
    monkeypatch.setattr(cgl, "_is_lock_holder_alive", lambda lock: False)
    _plant_lock(repo, holder_pid=4242, operation="crashed git gc")

    lock = cgl.acquire_common_git_lock(repo, "git fetch")

    try:
        assert lock.operation == "git fetch"
        assert _read_raw(repo)["lock_id"] == lock.lock_id
    finally:
        cgl.release_common_git_lock(repo, lock.lock_id)


def test_expired_lock_is_stolen(repo):
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    _plant_lock(repo, expires_at=past, holder_pid=os.getpid(), operation="overrun")

    lock = cgl.acquire_common_git_lock(repo, "git fetch")

    try:
        assert lock.operation == "git fetch"
    finally:
        cgl.release_common_git_lock(repo, lock.lock_id)


def test_released_status_lock_does_not_block(repo):
    _plant_lock(repo, status="released", expires_at="", holder_pid=os.getpid())

    lock = cgl.acquire_common_git_lock(repo, "git fetch")

    try:
        assert lock.status == "active"
    finally:
        cgl.release_common_git_lock(repo, lock.lock_id)


def test_corrupt_lock_file_is_discarded_and_reacquired(repo):
    lock_path = _lock_path(repo)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("{ truncated", encoding="utf-8")

    lock = cgl.acquire_common_git_lock(repo, "git fetch")

    try:
        assert lock.operation == "git fetch"
        assert _read_raw(repo)["lock_id"] == lock.lock_id
    finally:
        cgl.release_common_git_lock(repo, lock.lock_id)


# --------------------------------------------------------------------------
# release
# --------------------------------------------------------------------------

def test_release_removes_the_lock_file(repo):
    lock = cgl.acquire_common_git_lock(repo, "git fetch")

    assert cgl.release_common_git_lock(repo, lock.lock_id) is True
    assert not _lock_path(repo).exists()


def test_release_allows_reacquisition(repo):
    first = cgl.acquire_common_git_lock(repo, "git fetch")
    assert cgl.release_common_git_lock(repo, first.lock_id) is True

    second = cgl.acquire_common_git_lock(repo, "git push")

    try:
        assert second.lock_id != first.lock_id
    finally:
        cgl.release_common_git_lock(repo, second.lock_id)


def test_release_returns_false_when_no_lock_exists(repo):
    assert cgl.release_common_git_lock(repo) is False


def test_release_rejects_a_mismatched_lock_id(repo):
    lock = cgl.acquire_common_git_lock(repo, "git fetch")

    try:
        assert cgl.release_common_git_lock(repo, "not-my-lock-id") is False
        assert _read_raw(repo)["lock_id"] == lock.lock_id
    finally:
        cgl.release_common_git_lock(repo, lock.lock_id)


def test_release_rewrites_status_before_removing(repo, monkeypatch):
    """The released tombstone is written first, then the file is unlinked."""
    seen = {}
    real_remove = cgl._remove_lock

    def spy_remove(root):
        seen["status_at_remove"] = _read_raw(root)["status"]
        real_remove(root)

    monkeypatch.setattr(cgl, "_remove_lock", spy_remove)
    lock = cgl.acquire_common_git_lock(repo, "git fetch")

    assert cgl.release_common_git_lock(repo, lock.lock_id) is True
    assert seen["status_at_remove"] == "released"


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


def test_context_manager_propagates_acquire_failure(repo, holder_appears_alive):
    first = cgl.acquire_common_git_lock(repo, "git fetch")

    try:
        with pytest.raises(RuntimeError):
            with cgl.common_git_lock(repo, "git push"):
                pytest.fail("body must not run")
    finally:
        cgl.release_common_git_lock(repo, first.lock_id)


# --------------------------------------------------------------------------
# get_lock_status
# --------------------------------------------------------------------------

def test_status_is_unlocked_without_a_lock(repo):
    assert cgl.get_lock_status(repo) == {"status": "unlocked", "lock_id": None}


def test_status_is_active_for_a_live_unexpired_holder(repo, holder_appears_alive):
    lock = cgl.acquire_common_git_lock(repo, "git fetch")

    try:
        status = cgl.get_lock_status(repo)
        assert status["status"] == "active"
        assert status["lock_id"] == lock.lock_id
        assert status["holder_pid"] == os.getpid()
        assert status["operation"] == "git fetch"
        assert status["repo_root"] == str(repo.resolve())
    finally:
        cgl.release_common_git_lock(repo, lock.lock_id)


def test_status_is_stale_for_a_dead_holder(repo, monkeypatch):
    monkeypatch.setattr(cgl, "_is_lock_holder_alive", lambda lock: False)
    lock = cgl.acquire_common_git_lock(repo, "git fetch")

    try:
        assert cgl.get_lock_status(repo)["status"] == "stale"
    finally:
        cgl.release_common_git_lock(repo, lock.lock_id)


def test_status_is_stale_for_an_expired_lock(repo):
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    planted = _plant_lock(repo, expires_at=past, holder_pid=os.getpid())

    assert cgl.get_lock_status(repo)["status"] == "stale"
    assert cgl.get_lock_status(repo)["lock_id"] == planted.lock_id


def test_status_reports_a_released_tombstone_verbatim(repo):
    """A non-active status is echoed back rather than reclassified."""
    planted = _plant_lock(repo, status="released", expires_at="")

    assert cgl.get_lock_status(repo)["status"] == "released"
    assert planted.lock_id


def test_status_is_unlocked_for_a_corrupt_lock_file(repo):
    lock_path = _lock_path(repo)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("{ truncated", encoding="utf-8")

    assert cgl.get_lock_status(repo)["status"] == "unlocked"


# --------------------------------------------------------------------------
# _is_lock_holder_alive
# --------------------------------------------------------------------------

def test_holder_alive_is_false_for_a_nonpositive_pid():
    assert cgl._is_lock_holder_alive(cgl.CommonGitLock(holder_pid=0)) is False
    assert cgl._is_lock_holder_alive(cgl.CommonGitLock(holder_pid=-1)) is False


def test_holder_alive_windows_branch_uses_tasklist(monkeypatch):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="python.exe  1234  Console")

    monkeypatch.setattr(cgl.platform, "system", lambda: "Windows")
    monkeypatch.setattr(cgl.subprocess, "run", fake_run)

    assert cgl._is_lock_holder_alive(cgl.CommonGitLock(holder_pid=1234)) is True
    assert calls[0][0] == ["tasklist", "/FI", "PID eq 1234"]
    assert calls[0][1]["timeout"] == 10


def test_holder_alive_windows_branch_is_false_when_absent_from_tasklist(monkeypatch):
    monkeypatch.setattr(cgl.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        cgl.subprocess, "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=""),
    )

    assert cgl._is_lock_holder_alive(cgl.CommonGitLock(holder_pid=1234)) is False


def test_holder_alive_posix_branch_sends_signal_zero(monkeypatch):
    seen = []
    monkeypatch.setattr(cgl.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cgl.os, "kill", lambda pid, sig: seen.append((pid, sig)))

    assert cgl._is_lock_holder_alive(cgl.CommonGitLock(holder_pid=1234)) is True
    assert seen == [(1234, 0)]


def test_holder_alive_is_false_when_kill_raises(monkeypatch):
    def boom(pid, sig):
        raise ProcessLookupError(pid)

    monkeypatch.setattr(cgl.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cgl.os, "kill", boom)

    assert cgl._is_lock_holder_alive(cgl.CommonGitLock(holder_pid=1234)) is False


def test_holder_alive_is_false_when_the_probe_times_out(monkeypatch):
    def boom(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 10)

    monkeypatch.setattr(cgl.platform, "system", lambda: "Windows")
    monkeypatch.setattr(cgl.subprocess, "run", boom)

    assert cgl._is_lock_holder_alive(cgl.CommonGitLock(holder_pid=1234)) is False


def test_holder_alive_for_this_process_is_true(monkeypatch):
    """Our own pid must read as alive, whichever branch the host takes.

    `os.kill` is stubbed so that a non-win32 host never sends a real signal,
    and the win32 branch is stubbed so no `tasklist` process is spawned.
    """
    monkeypatch.setattr(cgl.platform, "system", lambda: "Linux")
    monkeypatch.setattr(cgl.os, "kill", lambda pid, sig: None)

    assert cgl._is_lock_holder_alive(cgl.CommonGitLock(holder_pid=os.getpid())) is True


# --------------------------------------------------------------------------
# read_only_session() interaction
# --------------------------------------------------------------------------

def test_common_git_lock_has_no_read_only_session_gate(repo, monkeypatch):
    """Real behaviour: common_git_lock never consults READ_ONLY_SESSION.

    Unlike the worktree lease module it does not even import the helper.
    """
    monkeypatch.setenv("READ_ONLY_SESSION", "1")

    assert not hasattr(cgl, "read_only_session")
    lock = cgl.acquire_common_git_lock(repo, "git fetch")
    try:
        assert lock.status == "active"
    finally:
        cgl.release_common_git_lock(repo, lock.lock_id)


# --------------------------------------------------------------------------
# read helpers
# --------------------------------------------------------------------------

def test_read_lock_returns_none_when_absent(repo):
    assert cgl._read_lock(repo) is None


def test_read_lock_returns_none_for_unparsable_json(repo):
    lock_path = _lock_path(repo)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("not json at all", encoding="utf-8")

    assert cgl._read_lock(repo) is None


def test_remove_lock_is_idempotent(repo):
    cgl.acquire_common_git_lock(repo, "git fetch")

    cgl._remove_lock(repo)
    cgl._remove_lock(repo)

    assert not _lock_path(repo).exists()


@pytest.mark.xfail(
    strict=True,
    reason="GAP-052 BUG: _get_common_git_lock_path() treats any existing .git as a directory, so "
           "passing a linked worktree root raises NotADirectoryError instead of the documented "
           "RuntimeError('Not a Git repository')",
)
def test_linked_worktree_root_raises_a_clear_runtime_error(repo, linked_worktree):
    with pytest.raises(RuntimeError, match="Not a Git repository"):
        cgl.acquire_common_git_lock(linked_worktree, "git fetch")