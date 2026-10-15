"""Unit coverage for GAP-052 per-worktree mutation leases.

`worktree_lock.acquire_worktree_lease` anchors its lease directory at
`Path(__file__).resolve().parents[3]` -- i.e. the checkout that *contains*
this module, not the worktree being leased. Every test here therefore
monkeypatches `_get_worktree_leases_dir` into `tmp_path`, so no test ever
reads or writes the real repository's `.agent_locks/` directory.

No Windows-only API is called, so this file is collectable and runnable on
ubuntu CI (GAP-055).
"""
import calendar
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ultimate_pipeline.governance.single_writer import worktree_lock as wl


class _OffsetTime:
    """Stand-in for the stdlib `time` module with controlled mktime semantics.

    `is_expired()` compares `time.mktime(time.gmtime())` against
    `time.mktime(time.strptime(stamp))`. Those two structs differ in
    `tm_isdst`: `gmtime()` yields 0, `strptime()` yields -1, so `mktime`
    resolves them against the host's *standard* and *daylight* rules
    respectively. On a host with active DST the two sides are skewed
    against each other. This shim pins both sides to the same offset so
    expiry arithmetic is host-independent.
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
    monkeypatch.setattr(wl, "time", _OffsetTime(0, 0))


@pytest.fixture()
def leases_dir(tmp_path, monkeypatch):
    """Redirect the module's lease directory into tmp_path."""
    redirected = tmp_path / "_agent_leases"
    monkeypatch.setattr(wl, "_get_worktree_leases_dir", lambda: redirected)
    redirected.mkdir(parents=True, exist_ok=True)
    return redirected


@pytest.fixture()
def worktree(tmp_path):
    """A throwaway directory standing in for a git worktree root."""
    wt = tmp_path / "wt_main"
    wt.mkdir()
    return wt


def _lease_path_for(worktree_root):
    return wl._worktree_lease_path(Path(worktree_root).resolve())


def _read_raw(worktree_root):
    return json.loads(_lease_path_for(worktree_root).read_text(encoding="utf-8"))


def _plant_lease(worktree_root, **overrides):
    """Write a lease file directly, bypassing acquire's guards."""
    lease = wl.WorktreeLease(
        worktree_root=str(Path(worktree_root).resolve()),
        worktree_name=Path(worktree_root).name,
    )
    for key, value in overrides.items():
        setattr(lease, key, value)
    wl._write_lease(lease)
    return lease


def _utc_delta_seconds(stamp, fmt="%Y-%m-%dT%H:%M:%SZ"):
    """True UTC seconds from now until stamp (never local-time skewed)."""
    return calendar.timegm(time.strptime(stamp, fmt)) - time.time()


# --------------------------------------------------------------------------
# acquire: happy path and lease contents
# --------------------------------------------------------------------------

def test_acquire_returns_active_lease(leases_dir, worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="unit test")

    assert lease.status == "active"
    assert lease.purpose == "unit test"
    assert lease.lease_id
    assert Path(lease.worktree_root) == worktree.resolve()
    assert lease.worktree_name == worktree.name


def test_acquire_creates_exactly_one_lease_file(leases_dir, worktree):
    wl.acquire_worktree_lease(worktree, purpose="one file")

    files = sorted(p.name for p in leases_dir.glob("*.lease.json"))
    assert len(files) == 1
    assert files[0].endswith(".lease.json")


def test_lease_file_records_process_identity(leases_dir, worktree):
    wl.acquire_worktree_lease(worktree, purpose="identity")

    data = _read_raw(worktree)
    assert data["schema"] == wl.SCHEMA_VERSION
    assert data["holder_pid"] == os.getpid()
    assert data["holder_ppid"] == os.getppid()
    assert data["holder_cmdline"] == " ".join(sys.argv)
    assert data["holder_start_utc"]
    assert data["acquired_at"]


def test_lease_json_exposes_the_documented_field_set(leases_dir, worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="fields")

    assert set(lease.to_json()) == {
        "schema", "status", "worktree_root", "worktree_name", "lease_id",
        "acquired_at", "expires_at", "holder_pid", "holder_ppid",
        "holder_cmdline", "holder_start_utc", "purpose",
    }


def test_lease_json_roundtrip_preserves_fields(leases_dir, worktree):
    original = wl.acquire_worktree_lease(worktree, purpose="roundtrip")

    restored = wl.WorktreeLease.from_json(original.to_json())

    assert restored.to_json() == original.to_json()


def test_from_json_defaults_missing_optional_fields():
    restored = wl.WorktreeLease.from_json({"lease_id": "abc"})

    assert restored.lease_id == "abc"
    assert restored.schema == wl.SCHEMA_VERSION
    assert restored.status == "active"
    assert restored.holder_pid == 0
    assert restored.purpose == ""


def test_lease_minutes_controls_expiry_window(leases_dir, worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="expiry", lease_minutes=30)

    # expires_at is second-granular, so allow a small scheduling margin.
    assert _utc_delta_seconds(lease.expires_at) == pytest.approx(30 * 60, abs=5)


def test_negative_minutes_lease_is_immediately_expired(leases_dir, worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="short", lease_minutes=-1)

    assert lease.is_expired() is True


def test_lease_path_is_sanitised_from_worktree_path(leases_dir, worktree):
    wl.acquire_worktree_lease(worktree, purpose="sanitise")

    name = _lease_path_for(worktree).name
    assert ":" not in name
    assert "\\" not in name
    assert "/" not in name


# --------------------------------------------------------------------------
# contention
# --------------------------------------------------------------------------

def test_second_acquire_on_same_worktree_is_refused(leases_dir, worktree):
    first = wl.acquire_worktree_lease(worktree, purpose="first")

    with pytest.raises(RuntimeError) as excinfo:
        wl.acquire_worktree_lease(worktree, purpose="second")

    message = str(excinfo.value)
    assert first.lease_id in message
    assert "already has an active lease" in message


def test_refused_acquire_does_not_disturb_the_holder(leases_dir, worktree):
    first = wl.acquire_worktree_lease(worktree, purpose="first")

    with pytest.raises(RuntimeError):
        wl.acquire_worktree_lease(worktree, purpose="second")

    assert _read_raw(worktree)["lease_id"] == first.lease_id


def test_different_worktrees_may_hold_leases_concurrently(leases_dir, tmp_path):
    first_root = tmp_path / "wt_a"
    second_root = tmp_path / "wt_b"
    first_root.mkdir()
    second_root.mkdir()

    first = wl.acquire_worktree_lease(first_root, purpose="a")
    second = wl.acquire_worktree_lease(second_root, purpose="b")

    assert first.lease_id != second.lease_id
    assert len(list(leases_dir.glob("*.lease.json"))) == 2


def test_concurrent_acquire_has_exactly_one_winner(leases_dir, worktree):
    """O_EXCL must let exactly one of N racing acquirers proceed."""
    outcomes = []
    barrier = threading.Barrier(4)

    def contender():
        barrier.wait()
        try:
            outcomes.append(("ok", wl.acquire_worktree_lease(worktree, purpose="race")))
        except RuntimeError:
            outcomes.append("refused")

    with ThreadPoolExecutor(max_workers=4) as pool:
        for _ in range(4):
            pool.submit(contender)

    winners = [o for o in outcomes if isinstance(o, tuple)]
    assert len(winners) == 1
    assert len([o for o in outcomes if o == "refused"]) == 3


# --------------------------------------------------------------------------
# stale-lease handling
# --------------------------------------------------------------------------

def test_expired_lease_does_not_block_acquisition(leases_dir, worktree):
    stale = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    _plant_lease(worktree, expires_at=stale, holder_pid=4242, purpose="stale")

    fresh = wl.acquire_worktree_lease(worktree, purpose="fresh")

    assert fresh.purpose == "fresh"
    assert _read_raw(worktree)["lease_id"] == fresh.lease_id


def test_released_lease_does_not_block_acquisition(leases_dir, worktree):
    _plant_lease(worktree, status="released", expires_at="", holder_pid=4242)

    fresh = wl.acquire_worktree_lease(worktree, purpose="after release")

    assert fresh.status == "active"


def test_expired_lease_from_acquire_does_not_block_next_acquire(leases_dir, worktree):
    wl.acquire_worktree_lease(worktree, purpose="instant", lease_minutes=-1)

    fresh = wl.acquire_worktree_lease(worktree, purpose="next")

    assert fresh.purpose == "next"


def test_acquire_steals_a_stale_file_found_during_the_o_excl_race(leases_dir, worktree, monkeypatch):
    """The retry branch of the O_EXCL loop must reclaim a stale lease file.

    The pre-check read is forced to miss, which is exactly what happens when
    another process creates a stale lease between the pre-check and the
    exclusive create.
    """
    expired = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    _plant_lease(worktree, expires_at=expired, holder_pid=4242, purpose="stale")
    real_read = wl._read_lease
    calls = []

    def racing_read(root):
        calls.append(root)
        if len(calls) == 1:
            return None  # simulate "no lease seen" at the pre-check
        return real_read(root)

    monkeypatch.setattr(wl, "_read_lease", racing_read)

    fresh = wl.acquire_worktree_lease(worktree, purpose="racer")

    assert fresh.purpose == "racer"
    assert len(calls) >= 2, "the O_EXCL retry branch was not exercised"


# --------------------------------------------------------------------------
# is_expired
# --------------------------------------------------------------------------

def test_is_expired_is_false_without_an_expiry():
    assert wl.WorktreeLease(expires_at="").is_expired() is False


def test_is_expired_is_true_for_a_past_timestamp():
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
    assert wl.WorktreeLease(expires_at=past).is_expired() is True


def test_is_expired_is_false_for_a_future_timestamp():
    future = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 600))
    assert wl.WorktreeLease(expires_at=future).is_expired() is False


def test_is_expired_fails_closed_on_a_malformed_timestamp():
    assert wl.WorktreeLease(expires_at="not-a-timestamp").is_expired() is True


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
    monkeypatch.setattr(wl, "time", _OffsetTime(std_east_seconds=std_east, dst_east_seconds=dst_east))
    now = time.time()
    future = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + 600))
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 600))

    assert wl.WorktreeLease(expires_at=future).is_expired() is False
    assert wl.WorktreeLease(expires_at=past).is_expired() is True


def test_is_expired_is_timezone_independent(monkeypatch):
    monkeypatch.setattr(wl, "time", _OffsetTime(std_east_seconds=3600, dst_east_seconds=7200))

    future = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 600))

    assert wl.WorktreeLease(expires_at=future).is_expired() is False


def test_lease_stays_valid_through_its_remaining_minutes(leases_dir, worktree, monkeypatch):
    monkeypatch.setattr(wl, "time", _OffsetTime(std_east_seconds=3600, dst_east_seconds=7200))

    # 30 minutes is comfortably shorter than the one-hour DST skew.
    lease = wl.acquire_worktree_lease(worktree, purpose="dst skew", lease_minutes=30)

    assert wl.WorktreeLease.from_json(lease.to_json()).is_expired() is False


# --------------------------------------------------------------------------
# release
# --------------------------------------------------------------------------

def test_release_removes_the_lease_file(leases_dir, worktree):
    wl.acquire_worktree_lease(worktree, purpose="release me")

    assert wl.release_worktree_lease(worktree) is True
    assert not _lease_path_for(worktree).exists()


def test_release_allows_reacquisition(leases_dir, worktree):
    first = wl.acquire_worktree_lease(worktree, purpose="first")
    assert wl.release_worktree_lease(worktree) is True

    second = wl.acquire_worktree_lease(worktree, purpose="second")

    assert second.lease_id != first.lease_id


def test_release_returns_false_when_no_lease_exists(leases_dir, worktree):
    assert wl.release_worktree_lease(worktree) is False


def test_release_rejects_a_mismatched_lease_id(leases_dir, worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="owned")

    assert wl.release_worktree_lease(worktree, "not-my-lease-id") is False
    assert _read_raw(worktree)["lease_id"] == lease.lease_id


def test_release_accepts_the_matching_lease_id(leases_dir, worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="owned")

    assert wl.release_worktree_lease(worktree, lease.lease_id) is True
    assert not _lease_path_for(worktree).exists()


def test_release_reports_success_when_releasing_its_own_lease_twice(leases_dir, worktree):
    lease = wl.acquire_worktree_lease(worktree, purpose="twice")
    assert wl.release_worktree_lease(worktree, lease.lease_id) is True

    # The file is gone, so a repeat release is a clean False.
    assert wl.release_worktree_lease(worktree, lease.lease_id) is False


# --------------------------------------------------------------------------
# listing and cleanup
# --------------------------------------------------------------------------

def test_list_worktree_leases_is_empty_by_default(leases_dir):
    assert wl.list_worktree_leases() == []


def test_list_worktree_leases_reports_acquired_roots(leases_dir, tmp_path):
    first_root = tmp_path / "wt_a"
    second_root = tmp_path / "wt_b"
    first_root.mkdir()
    second_root.mkdir()
    wl.acquire_worktree_lease(first_root, purpose="a")
    wl.acquire_worktree_lease(second_root, purpose="b")

    listed = {lease.worktree_root for lease in wl.list_worktree_leases()}

    assert listed == {str(first_root.resolve()), str(second_root.resolve())}


def test_list_worktree_leases_skips_unparsable_files(leases_dir, worktree):
    wl.acquire_worktree_lease(worktree, purpose="good")
    broken = leases_dir / "garbage.lease.json"
    broken.write_text("{not json", encoding="utf-8")

    listed = wl.list_worktree_leases()

    assert [lease.purpose for lease in listed] == ["good"]


def test_cleanup_removes_expired_and_keeps_active(leases_dir, tmp_path):
    stale_root = tmp_path / "wt_stale"
    live_root = tmp_path / "wt_live"
    stale_root.mkdir()
    live_root.mkdir()
    past = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    _plant_lease(stale_root, expires_at=past, holder_pid=4242)
    wl.acquire_worktree_lease(live_root, purpose="live")

    removed = wl.cleanup_expired_leases()

    assert removed == 1
    assert not _lease_path_for(stale_root).exists()
    assert _lease_path_for(live_root).exists()


def test_cleanup_on_an_empty_directory_removes_nothing(leases_dir):
    assert wl.cleanup_expired_leases() == 0


# --------------------------------------------------------------------------
# read helpers
# --------------------------------------------------------------------------

def test_read_lease_returns_none_when_absent(leases_dir, worktree):
    assert wl._read_lease(worktree) is None


def test_read_lease_returns_none_for_unparsable_json(leases_dir, worktree):
    lease_path = _lease_path_for(worktree)
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease_path.write_text("{not json", encoding="utf-8")

    assert wl._read_lease(worktree) is None


def test_read_lease_roundtrips_a_written_lease(leases_dir, worktree):
    wl.acquire_worktree_lease(worktree, purpose="readback")

    loaded = wl._read_lease(worktree)

    assert loaded is not None
    assert loaded.purpose == "readback"


def test_remove_lease_is_idempotent(leases_dir, worktree):
    wl.acquire_worktree_lease(worktree, purpose="remove")

    wl._remove_lease(worktree)
    wl._remove_lease(worktree)

    assert not _lease_path_for(worktree).exists()


# --------------------------------------------------------------------------
# read_only_session() interaction
# --------------------------------------------------------------------------

def test_read_only_session_helper_is_exposed_by_the_module():
    assert callable(wl.read_only_session)


def test_read_only_session_reads_the_environment(leases_dir, worktree, monkeypatch):
    monkeypatch.setenv("READ_ONLY_SESSION", "1")

    assert wl.read_only_session() is True


def test_acquire_still_succeeds_under_read_only_session(leases_dir, worktree, monkeypatch):
    """Documents the real behaviour: the guard is imported but never consulted."""
    monkeypatch.setenv("READ_ONLY_SESSION", "1")

    lease = wl.acquire_worktree_lease(worktree, purpose="read only session")

    assert lease.status == "active"


@pytest.mark.xfail(
    strict=True,
    reason="GAP-052 BUG: worktree_lock imports read_only_session (line 27) but never calls it, "
           "so a READ_ONLY_SESSION process can still take a mutation lease",
)
def test_acquire_is_refused_under_read_only_session(leases_dir, worktree, monkeypatch):
    monkeypatch.setenv("READ_ONLY_SESSION", "1")

    with pytest.raises(RuntimeError):
        wl.acquire_worktree_lease(worktree, purpose="should be refused")


@pytest.mark.xfail(
    strict=True,
    reason="GAP-052 BUG: acquire_worktree_lease treats an unparsable lease file as "
           "'leased by another process' with no public recovery path, unlike common_git_lock",
)
def test_corrupt_lease_file_does_not_permanently_lock_the_worktree(leases_dir, worktree):
    lease_path = _lease_path_for(worktree)
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease_path.write_text("{ truncated json", encoding="utf-8")

    lease = wl.acquire_worktree_lease(worktree, purpose="after corruption")

    assert lease.status == "active"