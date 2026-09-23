"""Module-level multiprocessing worker for the GAP-024 WriterLock regression
tests (tests/unit/test_writer_lock_concurrency.py).

This must live in its own importable module (not nested inside the test
function) because Windows' default multiprocessing start method is
"spawn": the child interpreter re-imports the target function by module
path, so it has to be a real top-level module, not a closure.
"""
from __future__ import annotations

from pathlib import Path

from ultimate_pipeline.contracts.writer_lock import WriterLock


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
