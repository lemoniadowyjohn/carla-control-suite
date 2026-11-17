from __future__ import annotations

import multiprocessing

from _acceptance_output_lock_worker import hold_output_lock


def test_separate_processes_serialize_acceptance_writes_to_same_directory(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    active = ctx.Value("i", 0)
    maximum = ctx.Value("i", 0)
    results = ctx.Queue()
    workers = [
        ctx.Process(
            target=hold_output_lock,
            args=(str(tmp_path), start, active, maximum, results),
        )
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(10)
    try:
        assert all(worker.exitcode == 0 for worker in workers)
        assert [results.get(timeout=1) for _ in workers] == ["released", "released"]
        assert maximum.value == 1
        assert active.value == 0
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join()
