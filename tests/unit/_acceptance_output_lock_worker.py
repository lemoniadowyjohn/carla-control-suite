from __future__ import annotations

import time
from pathlib import Path

from scripts.measure_candidate_acceptance import _exclusive_acceptance_output


def hold_output_lock(directory: str, start, active, maximum, results) -> None:
    start.wait(10)
    with _exclusive_acceptance_output(Path(directory)):
        with active.get_lock():
            active.value += 1
            maximum.value = max(maximum.value, active.value)
        time.sleep(0.2)
        with active.get_lock():
            active.value -= 1
    results.put("released")
