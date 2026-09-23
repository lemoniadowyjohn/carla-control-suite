"""GAP-024 regression tests.

Covers two real, confirmed races in ultimate_pipeline/contracts/writer_lock.py:

1. WriterLock.acquire() was a plain check-then-write (TOCTOU): multiple
   concurrent OS processes could all pass the "is anyone holding this?"
   check before any of them wrote the lock file, so all of them believed
   they held exclusive ownership. Reproduced here with real
   multiprocessing.Process workers (not threads -- the GIL can mask a
   race that is real across separate interpreters/processes).

2. A stale (expired-lease) owner's own in-memory WriterLock object could
   call .heartbeat() or .release() and unconditionally overwrite a
   DIFFERENT agent's legitimately-reclaimed lock, because neither method
   re-validated the identity of what is actually currently persisted on
   disk before writing.

Also covers the "corrupt/unknown-schema lock file at acquire() time must
fail closed" property (5 cases), which must not regress under the new
atomic-acquire implementation.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _writer_lock_mp_worker import acquire_worker  # noqa: E402

from ultimate_pipeline.contracts.writer_lock import WriterLock

N_WORKERS = 8
ITERATIONS = 20


def test_concurrent_acquire_exactly_one_winner_real_processes(tmp_path: Path) -> None:
    """GAP-024 bug 1 (TOCTOU race): N real OS processes race to acquire a
    fresh lock, released simultaneously via a shared Event. Exactly one
    must win, across many iterations, using genuinely separate processes
    (spawn context) so no GIL can mask a race that would occur in
    production between independent agent processes.
    """
    ctx = mp.get_context("spawn")
    multi_or_zero_winner_iterations = 0

    for i in range(ITERATIONS):
        iter_root = tmp_path / f"iter_{i}"
        iter_root.mkdir()
        ready_events = [ctx.Event() for _ in range(N_WORKERS)]
        go_event = ctx.Event()
        result_queue = ctx.Queue()
        procs = []
        for idx in range(N_WORKERS):
            p = ctx.Process(
                target=acquire_worker,
                args=(str(iter_root), f"agent-{idx}", ready_events[idx], go_event, result_queue),
            )
            p.start()
            procs.append(p)

        for e in ready_events:
            assert e.wait(timeout=30), f"iteration {i}: worker failed to signal ready"
        go_event.set()

        results = [result_queue.get(timeout=30) for _ in range(N_WORKERS)]
        for p in procs:
            p.join(timeout=30)
            assert p.exitcode == 0, f"iteration {i}: worker process exited abnormally"

        oks = [r for r in results if r[1] == "ok"]
        blocked = [r for r in results if r[1] == "blocked"]
        errors = [r for r in results if r[1] == "error"]

        assert not errors, f"iteration {i}: unexpected worker errors: {errors}"
        if len(oks) != 1:
            multi_or_zero_winner_iterations += 1
        assert len(oks) == 1, (
            f"iteration {i}: expected exactly one winner of {N_WORKERS} real "
            f"concurrent acquire() calls, got {len(oks)}: {results}"
        )
        assert len(blocked) == N_WORKERS - 1

    assert multi_or_zero_winner_iterations == 0


def test_stale_owner_heartbeat_does_not_clobber_reclaimed_lock(tmp_path: Path) -> None:
    """GAP-024 bug 2 (heartbeat clobber): agent-1 acquires with an
    instantly-expiring lease, agent-2 legitimately reclaims it, then
    agent-1's stale in-memory handle calls .heartbeat(). This must not
    silently overwrite agent-2's active lock.
    """
    stale = WriterLock.acquire(
        root=tmp_path, branch="b1", head_sha="s1", owner="agent-1", lease_minutes=0
    )
    assert stale.is_expired()

    fresh = WriterLock.acquire(
        root=tmp_path, branch="b2", head_sha="s2", owner="agent-2", lease_minutes=60
    )
    assert fresh.owner == "agent-2"

    with pytest.raises(RuntimeError):
        stale.heartbeat()

    on_disk = WriterLock.load(tmp_path / ".agent_locks" / "writer.lock")
    assert on_disk.owner == "agent-2"
    assert on_disk.lock_id == fresh.lock_id
    assert on_disk.status == "active"


def test_stale_owner_release_does_not_clobber_reclaimed_lock(tmp_path: Path) -> None:
    """GAP-024 bug 2 (release clobber): agent-1 acquires with an
    instantly-expiring lease, agent-2 legitimately reclaims it, then
    agent-1's stale in-memory handle calls .release(). This must not mark
    agent-2's still-active lock as released.
    """
    stale = WriterLock.acquire(
        root=tmp_path, branch="b1", head_sha="s1", owner="agent-1", lease_minutes=0
    )
    fresh = WriterLock.acquire(
        root=tmp_path, branch="b2", head_sha="s2", owner="agent-2", lease_minutes=60
    )

    with pytest.raises(RuntimeError):
        stale.release(owner="agent-1", lock_id=stale.lock_id)

    on_disk = WriterLock.load(tmp_path / ".agent_locks" / "writer.lock")
    assert on_disk.status == "active"
    assert on_disk.owner == "agent-2"
    assert on_disk.lock_id == fresh.lock_id


def _write_lock_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_acquire_fails_closed_on_invalid_json(tmp_path: Path) -> None:
    lock_path = tmp_path / ".agent_locks" / "writer.lock"
    _write_lock_file(lock_path, "{not valid json")
    with pytest.raises(Exception):
        WriterLock.acquire(root=tmp_path, branch="b", head_sha="s", owner="agent")


def test_acquire_fails_closed_on_json_list(tmp_path: Path) -> None:
    lock_path = tmp_path / ".agent_locks" / "writer.lock"
    _write_lock_file(lock_path, json.dumps(["not", "a", "dict"]))
    with pytest.raises(Exception):
        WriterLock.acquire(root=tmp_path, branch="b", head_sha="s", owner="agent")


def test_acquire_fails_closed_on_unrecognized_extra_key(tmp_path: Path) -> None:
    lock_path = tmp_path / ".agent_locks" / "writer.lock"
    _write_lock_file(
        lock_path,
        json.dumps(
            {
                "schema": "agent-writer-lock/v1",
                "status": "active",
                "owner": "agent-x",
                "branch": "b",
                "head_sha": "s",
                "created_at": "2026-01-01T00:00:00+00:00",
                "expires_at": "2099-01-01T00:00:00+00:00",
                "totally_unrecognized_field": "boom",
            }
        ),
    )
    with pytest.raises(Exception):
        WriterLock.acquire(root=tmp_path, branch="b", head_sha="s", owner="agent")


def test_acquire_fails_closed_on_unknown_schema_with_valid_required_fields(
    tmp_path: Path,
) -> None:
    """An unrecognized schema string with otherwise-valid required fields
    (and a live expiry) must still be treated conservatively -- i.e. the
    acquire is refused rather than silently clobbering data we don't
    recognize the shape of.
    """
    lock_path = tmp_path / ".agent_locks" / "writer.lock"
    _write_lock_file(
        lock_path,
        json.dumps(
            {
                "schema": "some-unknown-schema/v99",
                "status": "active",
                "owner": "agent-x",
                "branch": "b",
                "head_sha": "s",
                "created_at": "2026-01-01T00:00:00+00:00",
                "expires_at": "2099-01-01T00:00:00+00:00",
            }
        ),
    )
    with pytest.raises(RuntimeError, match="Writer lock held by"):
        WriterLock.acquire(root=tmp_path, branch="b", head_sha="s", owner="agent")


def test_acquire_fails_closed_on_empty_file(tmp_path: Path) -> None:
    lock_path = tmp_path / ".agent_locks" / "writer.lock"
    _write_lock_file(lock_path, "")
    with pytest.raises(Exception):
        WriterLock.acquire(root=tmp_path, branch="b", head_sha="s", owner="agent")
