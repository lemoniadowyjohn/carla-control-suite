"""Module-level multiprocessing workers for the WriterLock adversarial
stress harness (tests/unit/test_writer_lock_adversarial.py).

Top-level module (not nested inside the test) because Windows "spawn"
and Linux "forkserver" both re-import the target function by module
path, so every worker must be a real importable module.
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path

from ultimate_pipeline.contracts.writer_lock import WriterLock


def contend_worker(
    root: str,
    owner: str,
    ready_evt,
    go_evt,
    result_queue,
    lease_minutes: int = 60,
) -> None:
    ready_evt.set()
    go_evt.wait(timeout=60)
    try:
        lock = WriterLock.acquire(
            root=Path(root),
            branch="race-branch",
            head_sha="race-sha",
            owner=owner,
            lease_minutes=lease_minutes,
        )
        result_queue.put((owner, "ok", lock.lock_id))
    except RuntimeError as exc:
        result_queue.put((owner, "blocked", str(exc)))
    except Exception as exc:  # pragma: no cover - surfaced to the test
        result_queue.put(
            (owner, "error", f"{type(exc).__module__}.{type(exc).__qualname__}: {exc!r}")
        )


class _DelayedBinaryIO:
    """Wraps the O_EXCL fd so flush() can be delayed (the 'flushed' stage),
    widening the window where a concurrent reader sees an empty/partial file.
    """

    def __init__(self, inner, stage_evt, delay: float) -> None:
        self._inner = inner
        self._stage_evt = stage_evt
        self._delay = delay

    def write(self, data: bytes) -> int:
        return self._inner.write(data)

    def flush(self) -> None:
        self._stage_evt.set()
        if self._delay:
            time.sleep(self._delay)
        return self._inner.flush()

    def fileno(self) -> int:
        return self._inner.fileno()

    def close(self) -> None:
        return self._inner.close()

    def __enter__(self) -> "_DelayedBinaryIO":
        return self

    def __exit__(self, *args) -> None:
        return self._inner.__exit__(*args)


def delayed_publish_worker(
    root: str,
    owner: str,
    serialized_evt,
    created_evt,
    flushed_evt,
    fsynced_evt,
    delays: dict,
    result_queue,
) -> None:
    """Run WriterLock.acquire() with optional injected sleeps after each
    publication step, signaling each stage on the matching Event. The
    sleeps only widen the intermediate on-disk states; acquire() itself
    is the real, unmodified implementation. Staged order matches
    acquire(): serialize -> create(O_EXCL) -> write -> flush -> fsync.
    """
    import ultimate_pipeline.contracts.writer_lock as wl

    orig_dumps = json.dumps
    orig_open = os.open
    orig_fdopen = os.fdopen
    orig_fsync = os.fsync

    def _patched_dumps(*args, **kwargs):
        out = orig_dumps(*args, **kwargs)
        serialized_evt.set()
        if delays.get("serialized"):
            time.sleep(delays["serialized"])
        return out

    def _patched_open(path, flags, *args, **kwargs):
        fd = orig_open(path, flags, *args, **kwargs)
        created_evt.set()
        if delays.get("created"):
            time.sleep(delays["created"])
        return fd

    def _patched_fdopen(fd, *args, **kwargs):
        inner = orig_fdopen(fd, *args, **kwargs)
        return _DelayedBinaryIO(inner, flushed_evt, delays.get("flushed", 0.0))

    def _patched_fsync(fd):
        fsynced_evt.set()
        if delays.get("fsynced"):
            time.sleep(delays["fsynced"])
        return orig_fsync(fd)

    json.dumps = _patched_dumps
    os.open = _patched_open
    os.fdopen = _patched_fdopen
    os.fsync = _patched_fsync
    try:
        lock = WriterLock.acquire(
            root=Path(root),
            branch="race-branch",
            head_sha="race-sha",
            owner=owner,
            lease_minutes=60,
        )
        result_queue.put((owner, "ok", lock.lock_id))
    except RuntimeError as exc:
        result_queue.put((owner, "blocked", str(exc)))
    except Exception as exc:  # pragma: no cover - surfaced to the test
        result_queue.put(
            (owner, "error", f"{type(exc).__module__}.{type(exc).__qualname__}: {exc!r}")
        )
    finally:
        json.dumps = orig_dumps
        os.open = orig_open
        os.fdopen = orig_fdopen
        os.fsync = orig_fsync


def probe_worker(root: str, start_evt, stop_evt, result_queue, max_seconds: float = 20.0) -> None:
    """Repeatedly attempt WriterLock.acquire() in a tight loop until
    stop_evt is set (or a deadline passes), recording every outcome. Raw
    (uncontrolled) parse exceptions are tracked by their qualified type
    name; RuntimeError details are bucketed by whether they reported an
    unparseable/corrupt record (the widened empty-publish window) versus a
    live active owner. start_evt is set immediately before the loop so a
    parent can guarantee the probe is already sampling.
    """
    start_evt.set()
    deadline = time.monotonic() + max_seconds
    outcomes: Counter = Counter()
    raw_types: list[str] = []
    while not stop_evt.is_set() and time.monotonic() < deadline:
        try:
            lock = WriterLock.acquire(
                root=Path(root),
                branch="race-branch",
                head_sha="race-sha",
                owner="probe",
                lease_minutes=60,
            )
            outcomes["ok"] += 1
        except RuntimeError as exc:
            if "unparseable" in str(exc):
                outcomes["unparseable"] += 1
            else:
                outcomes["held_by"] += 1
        except Exception as exc:  # raw, uncontrolled exception class
            outcomes["raw"] += 1
            qname = f"{type(exc).__module__}.{type(exc).__qualname__}"
            if qname not in raw_types:
                raw_types.append(qname)
    result_queue.put((dict(outcomes), raw_types))


def releaser_worker(root: str, owner: str, lock_id: str, go_evt, result_queue) -> None:
    """A stale/current owner attempts release; re-loads the on-disk lock so
    the release re-validates against what is actually persisted (mirrors a
    real owner handle that outlived its in-memory sync).
    """
    go_evt.wait(timeout=60)
    lock_path = Path(root) / ".agent_locks" / "writer.lock"
    try:
        lock = WriterLock.load(lock_path)
        lock.release(owner=owner, lock_id=lock_id)
        result_queue.put((owner, "released", lock.lock_id))
    except RuntimeError as exc:
        result_queue.put((owner, "blocked", str(exc)))
    except Exception as exc:  # pragma: no cover - surfaced to the test
        result_queue.put(
            (owner, "error", f"{type(exc).__module__}.{type(exc).__qualname__}: {exc!r}")
        )