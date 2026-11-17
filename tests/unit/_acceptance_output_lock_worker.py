from __future__ import annotations

import time
from pathlib import Path

from scripts.measure_candidate_acceptance import _exclusive_acceptance_output


def hold_output_lock(directory: str, start, ready, active, maximum, results) -> None:
    ready.put("ready")
    if not start.wait(10):
        raise TimeoutError("parent did not release start barrier")
    with _exclusive_acceptance_output(Path(directory)):
        with active.get_lock():
            active.value += 1
            maximum.value = max(maximum.value, active.value)
        time.sleep(0.2)
        with active.get_lock():
            active.value -= 1
    results.put("released")


def acquire_nested(directory: str, results) -> None:
    with _exclusive_acceptance_output(Path(directory)):
        with _exclusive_acceptance_output(Path(directory)):
            results.put("nested")
