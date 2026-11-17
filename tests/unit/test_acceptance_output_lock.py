from __future__ import annotations

import multiprocessing

from _acceptance_output_lock_worker import acquire_nested, hold_output_lock


def test_separate_processes_serialize_acceptance_writes_to_same_directory(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    ready = ctx.Queue()
    active = ctx.Value("i", 0)
    maximum = ctx.Value("i", 0)
    results = ctx.Queue()
    workers = [
        ctx.Process(
            target=hold_output_lock,
            args=(str(tmp_path), start, ready, active, maximum, results),
        )
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    try:
        assert [ready.get(timeout=5) for _ in workers] == ["ready", "ready"]
        start.set()
        for worker in workers:
            worker.join(10)
        assert all(worker.exitcode == 0 for worker in workers)
        assert [results.get(timeout=1) for _ in workers] == ["released", "released"]
        assert maximum.value == 1
        assert active.value == 0
    finally:
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
