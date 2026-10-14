"""GAP-028 regression tests -- WriterLock fresh-lock atomic-publication
partial-read race.

GAP-028 is a DISTINCT residual gap introduced by the GAP-024 O_EXCL fix, not
a re-opening of GAP-024. GAP-024 fixed the check-then-write TOCTOU so only
one process can win the lock; but the winner's os.open(..., O_CREAT|O_EXCL)
makes the lock pathname visible at size 0 BEFORE the fdopen/write/flush/fsync
that populates it complete. A losing contender's immediate load() could
therefore observe an empty or torn file and raise JSONDecodeError out of
acquire(), which the multiprocessing worker surfaces as "error" (observed on
Linux CI: JSONDecodeError('Expecting value: line 1 column 1 (char 0)')).

GAP-024's original comment claimed the O_EXCL-created path "cannot be
observed incomplete" by readers -- true for the *write* side (two writers
can never both believe they won) but false for *readers* during the
visible-before-written window. GAP-028 closes that reader-side window with
a bounded fresh-publication re-read (~500ms ceiling) and fail-closed
handling that never unlinks unreadable content and never reports it as
"Writer lock held by".

Windows spawn-safe: cross-process workers are top-level functions in
tests/unit/_writer_lock_mp_worker.py (acquire_worker, delayed_publish_worker).
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _writer_lock_mp_worker import acquire_worker, delayed_publish_worker  # noqa: E402

from ultimate_pipeline.contracts.writer_lock import LOCK_DIR, LOCK_FILE, WriterLock

N_CONTENDERS = 8
WIDENED_ITERATIONS = 5
# Far above the real ~microsecond fresh-publication window (so contenders
# deterministically land inside it), far below the ~500ms re-read budget
# (so the fixed code recovers by re-reading rather than failing closed).
HOLD_SECONDS = 0.25


def _lock_path_for(root: Path) -> Path:
    return root / LOCK_DIR / LOCK_FILE


def _build_sim_winner_payload(root: Path) -> str:
    now = datetime.now(timezone.utc)
    winner = WriterLock(
        owner="sim-winner",
        status="active",
        branch="race-branch",
        head_sha="race-sha",
        created_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=60)).isoformat(),
        repository=str(root.resolve()),
        lock_id=uuid.uuid4().hex,
        heartbeat_at=now.isoformat(),
    )
    return json.dumps(winner.to_dict())


def test_widened_fresh_publication_contender_never_sees_partial_json(tmp_path: Path) -> None:
    """CONTROLLED widened-timing reproduction of the GAP-028 race.

    A publisher process claims the lock path exactly like a real winner
    (raw O_CREAT|O_EXCL -> pathname visible at size 0), holds it empty for
    HOLD_SECONDS (widening the natural microsecond window), then writes a
    pre-built valid live lock payload. While the path is still empty, N real
    contender processes race WriterLock.acquire().

    On the UNFIXED code a contender's immediate load() raises
    JSONDecodeError on the empty file, which acquire_worker surfaces as an
    "error" outcome -- this assertion (zero errors) is what makes the test
    FAIL on unfixed code. On the FIXED code the contender's bounded
    fresh-publication re-read rides out the window, observes the published
    live lock, and reports a clean "blocked".
    """
    ctx = mp.get_context("spawn")

    for i in range(WIDENED_ITERATIONS):
        iter_root = tmp_path / f"iter_{i}"
        iter_root.mkdir()
        payload_json = _build_sim_winner_payload(iter_root)
        lock_path = _lock_path_for(iter_root)

        pub_ready = ctx.Event()
        pub_go = ctx.Event()
        cont_go = ctx.Event()
        result_queue = ctx.Queue()

        publisher = ctx.Process(
            target=delayed_publish_worker,
            args=(str(iter_root), HOLD_SECONDS, payload_json, pub_ready, pub_go, result_queue),
        )
        publisher.start()
        assert pub_ready.wait(timeout=30), f"iteration {i}: publisher failed to signal ready"

        contenders = []
        cont_ready = [ctx.Event() for _ in range(N_CONTENDERS)]
        for idx in range(N_CONTENDERS):
            p = ctx.Process(
                target=acquire_worker,
                args=(str(iter_root), f"contender-{idx}", cont_ready[idx], cont_go, result_queue),
            )
            p.start()
            contenders.append(p)
        for e in cont_ready:
            assert e.wait(timeout=30), f"iteration {i}: contender failed to signal ready"

        # Release the publisher; wait until it has claimed the path (empty).
        pub_go.set()
        claimed = result_queue.get(timeout=30)
        assert claimed[0] == "publisher" and claimed[1] == "claimed", (
            f"iteration {i}: expected publisher claim, got {claimed}"
        )
        assert lock_path.exists(), f"iteration {i}: claimed path missing"
        assert lock_path.stat().st_size == 0, (
            f"iteration {i}: path should still be empty at claim time, "
            f"size={lock_path.stat().st_size}"
        )

        # Release the contenders while the empty window is still open.
        cont_go.set()

        # 8 contender results + 1 publisher final "ok" (order interleaved).
        messages = [result_queue.get(timeout=30) for _ in range(N_CONTENDERS + 1)]
        cont_results = [m for m in messages if m[0] != "publisher"]
        pub_finals = [m for m in messages if m[0] == "publisher"]
        assert len(cont_results) == N_CONTENDERS, (
            f"iteration {i}: expected {N_CONTENDERS} contender results, got {messages}"
        )

        for p in contenders:
            p.join(timeout=30)
            assert p.exitcode == 0, f"iteration {i}: contender exited abnormally"
        publisher.join(timeout=30)
        assert publisher.exitcode == 0, f"iteration {i}: publisher exited abnormally"

        errors = [r for r in cont_results if r[1] == "error"]
        assert not errors, (
            f"iteration {i}: contenders observed partial/unreadable fresh lock "
            f"(the GAP-028 bug): {errors}"
        )
        assert all(r[1] in ("ok", "blocked") for r in cont_results), (
            f"iteration {i}: unexpected contender outcomes: {cont_results}"
        )
        assert any(m[1] == "ok" for m in pub_finals), (
            f"iteration {i}: publisher did not report ok: {pub_finals}"
        )
        assert not any(m[1] == "error" for m in pub_finals), (
            f"iteration {i}: publisher errored: {pub_finals}"
        )

        # Contenders must not have clobbered/unlinked the winner's payload.
        on_disk = json.loads(lock_path.read_text(encoding="utf-8"))
        assert on_disk["owner"] == "sim-winner", (
            f"iteration {i}: lock owner clobbered: {on_disk.get('owner')}"
        )


def test_contender_fails_closed_on_persistent_empty_fresh_lock_without_deleting(
    tmp_path: Path,
) -> None:
    """A fresh lock path that stays 0 bytes forever (publisher claimed via
    O_EXCL but never wrote) must make a contender fail closed with a
    DISTINCT RuntimeError -- not "Writer lock held by" -- within a bounded
    time, and the empty file must NOT be deleted.
    """
    lock_dir = tmp_path / LOCK_DIR
    lock_dir.mkdir(parents=True)
    lock_path = lock_dir / LOCK_FILE
    open_flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    fd = os.open(str(lock_path), open_flags)
    os.close(fd)
    assert lock_path.stat().st_size == 0

    start = time.monotonic()
    with pytest.raises(RuntimeError) as excinfo:
        WriterLock.acquire(root=tmp_path, branch="b", head_sha="s", owner="agent")
    elapsed = time.monotonic() - start

    message = str(excinfo.value)
    assert "Writer lock held by" not in message
    assert "not readable JSON" in message
    assert elapsed < 5.0, f"fail-closed took {elapsed:.2f}s; expected a bounded wait"
    assert lock_path.exists()
    assert lock_path.stat().st_size == 0


def test_malformed_old_lock_fails_closed_and_is_not_deleted(tmp_path: Path) -> None:
    """A persistently malformed (realistic old, non-JSON) lock must fail
    closed with the distinct RuntimeError and leave the file byte-identical
    -- never silently unlink what we could not parse.
    """
    lock_path = _lock_path_for(tmp_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    content = '{"owner": "old-crashed-writer", "status": "active", garbage...'
    lock_path.write_text(content, encoding="utf-8")

    with pytest.raises(RuntimeError) as excinfo:
        WriterLock.acquire(root=tmp_path, branch="b", head_sha="s", owner="agent")

    message = str(excinfo.value)
    assert "Writer lock held by" not in message
    assert "not readable JSON" in message
    assert lock_path.exists()
    assert lock_path.read_text(encoding="utf-8") == content


def test_stale_expired_lock_is_reclaimable(tmp_path: Path) -> None:
    """Guards against the GAP-028 fix accidentally making everything fail
    closed: a parseable-but-expired (lease 0) lock must still be reclaimable
    by a second acquire, exactly as before the fix.
    """
    first = WriterLock.acquire(
        root=tmp_path, branch="b1", head_sha="s1", owner="old-agent", lease_minutes=0
    )
    assert first.is_expired()

    second = WriterLock.acquire(
        root=tmp_path, branch="b2", head_sha="s2", owner="new-agent", lease_minutes=60
    )
    assert second.owner == "new-agent"

    on_disk = WriterLock.load(_lock_path_for(tmp_path))
    assert on_disk.owner == "new-agent"
    assert on_disk.status == "active"
