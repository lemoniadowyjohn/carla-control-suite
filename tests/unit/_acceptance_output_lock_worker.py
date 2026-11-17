from __future__ import annotations

import time
from pathlib import Path

from scripts.measure_candidate_acceptance import _exclusive_acceptance_output


def contend_for_output_lock(
    directory: str, role: str, ready, start, first_acquired, second_attempting, release_first, acquired
) -> None:
    ready.put(role)
    if not start.wait(10):
        raise TimeoutError("parent did not release start barrier")
    if role == "first":
        with _exclusive_acceptance_output(Path(directory)):
            first_acquired.set()
            if not release_first.wait(10):
                raise TimeoutError("parent did not release first lock holder")
        acquired.put("first")
        return
    if not first_acquired.wait(10):
        raise TimeoutError("first worker did not acquire lock")
    second_attempting.set()
    with _exclusive_acceptance_output(Path(directory)):
        acquired.put("second")


def acquire_nested(directory: str, results) -> None:
    with _exclusive_acceptance_output(Path(directory)):
        with _exclusive_acceptance_output(Path(directory)):
            results.put("nested")


def hold_lock_until_terminated(directory: str, acquired) -> None:
    with _exclusive_acceptance_output(Path(directory)):
        acquired.set()
        while True:
            time.sleep(0.05)


def acquire_after_holder_exit(directory: str, acquired) -> None:
    with _exclusive_acceptance_output(Path(directory)):
        acquired.set()
