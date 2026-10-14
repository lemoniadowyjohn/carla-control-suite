"""Module-level multiprocessing workers for the GAP-024 / GAP-028 WriterLock
regression tests (tests/unit/test_writer_lock_concurrency.py,
tests/unit/test_writer_lock_atomic_publication.py).

These must live in their own importable module (not nested inside the test
function) because Windows' default multiprocessing start method is
"spawn": the child interpreter re-imports the target function by module
path, so it has to be a real top-level module, not a closure.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from ultimate_pipeline.contracts.writer_lock import LOCK_DIR, LOCK_FILE, WriterLock


def acquire_worker(
    root: str,
    owner: str,
    ready_event,
    go_event,
    result_queue,
    lease_minutes: int = 60,
) -> None:
    """Signal readiness, wait for the synchronized start gate, then race to
    acquire the writer lock. Puts (owner, outcome, detail) on result_queue.
    """
    root_path = Path(root)
    ready_event.set()
    go_event.wait(timeout=30)
    try:
        lock = WriterLock.acquire(
            root=root_path,
            branch="race-branch",
            head_sha="race-sha",
            owner=owner,
            lease_minutes=lease_minutes,
        )
        result_queue.put((owner, "ok", lock.lock_id))
    except RuntimeError as exc:
        result_queue.put((owner, "blocked", str(exc)))
    except Exception as exc:  # pragma: no cover - surfaced to the test as a failure
        result_queue.put((owner, "error", repr(exc)))


def delayed_publish_worker(
    root: str,
    hold_seconds: float,
    payload_json: str,
    ready_event,
    go_event,
    result_queue,
) -> None:
    """GAP-028 controlled widened-timing publisher.

    After go_event, claim the canonical lock path exactly like a real
    winner would (raw os.open with O_CREAT|O_EXCL|O_WRONLY|O_BINARY, so the
    pathname becomes visible at size 0), report "claimed" on result_queue,
    sleep hold_seconds while the path is still empty (widening the natural
    microsecond publication window to something a contender can
    deterministically land inside, while staying well below the ~500ms
    fresh-publication re-read budget), then write the pre-built valid lock
    JSON payload, fsync, close, and report "ok".
    """
    root_path = Path(root)
    lock_dir = root_path / LOCK_DIR
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / LOCK_FILE
    open_flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)

    ready_event.set()
    go_event.wait(timeout=30)
    try:
        fd = os.open(str(lock_path), open_flags)
    except FileExistsError as exc:
        result_queue.put(("publisher", "error", repr(exc)))
        return
    result_queue.put(("publisher", "claimed", str(lock_path)))
    try:
        time.sleep(hold_seconds)
        data = payload_json.encode("utf-8")
        os.write(fd, data)
        os.fsync(fd)
    except Exception as exc:
        result_queue.put(("publisher", "error", repr(exc)))
        return
    finally:
        os.close(fd)
    result_queue.put(("publisher", "ok", str(lock_path)))
