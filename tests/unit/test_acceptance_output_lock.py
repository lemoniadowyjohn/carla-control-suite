from __future__ import annotations

import multiprocessing
from queue import Empty

from _acceptance_output_lock_worker import (
    acquire_after_holder_exit,
    acquire_nested,
    contend_for_output_lock,
    hold_lock_until_terminated,
)


def test_separate_processes_serialize_acceptance_writes_to_same_directory(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    ready = ctx.Queue()
    first_acquired = ctx.Event()
    second_attempting = ctx.Event()
    release_first = ctx.Event()
    acquired = ctx.Queue()
    workers = [ctx.Process(target=contend_for_output_lock, args=(
        str(tmp_path), role, ready, start, first_acquired, second_attempting, release_first, acquired
    )) for role in ("first", "second")]
    for worker in workers:
        worker.start()
    try:
        assert {ready.get(timeout=5) for _ in workers} == {"first", "second"}
        start.set()
        assert first_acquired.wait(5)
        assert second_attempting.wait(5)
        try:
            acquired.get(timeout=0.25)
        except Empty:
            pass
        else:
            raise AssertionError("second process entered while the first held the output lock")
        release_first.set()
        assert [acquired.get(timeout=5), acquired.get(timeout=5)] == ["first", "second"]
        for worker in workers:
            worker.join(10)
        assert all(worker.exitcode == 0 for worker in workers)
    finally:
        release_first.set()
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join()


def test_nested_same_thread_acquisition_is_reentrant_and_bounded(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    results = ctx.Queue()
    worker = ctx.Process(
        target=acquire_nested,
        args=(str(tmp_path), results),
    )
    worker.start()
    worker.join(5)
    if worker.is_alive():
        worker.terminate()
        worker.join()
    assert worker.exitcode == 0
    assert results.get(timeout=1) == "nested"


def test_os_releases_output_lock_after_process_termination(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    acquired = ctx.Event()
    holder = ctx.Process(target=hold_lock_until_terminated, args=(str(tmp_path), acquired))
    holder.start()
    assert acquired.wait(5)
    holder.terminate()
    holder.join(5)
    assert holder.exitcode is not None

    reacquired = ctx.Event()
    contender = ctx.Process(target=acquire_after_holder_exit, args=(str(tmp_path), reacquired))
    contender.start()
    contender.join(5)
    if contender.is_alive():
        contender.terminate()
        contender.join()
    assert contender.exitcode == 0
    assert reacquired.is_set()
