from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from typing import Callable


@dataclass
class GateRunRecord:
    stage: str
    gate: str
    ok: bool
    detail: dict
    elapsed_s: float


class CumulativeGateRunner:
    """
    Tally-all, fail-at-end gate runner.

    Every gate runs regardless of prior failures.  When *finalize()* is called
    and the runner is in strict mode, a single RuntimeError is raised listing
    every gate that failed.
    """

    def __init__(self, strict: bool = False):
        self.results: list[GateRunRecord] = []
        self.strict = strict

    def run(self, stage: str, gate: str, fn: Callable[[], dict]) -> dict:
        t0 = time.perf_counter()
        try:
            report = fn()
            if isinstance(report, dict):
                ok = bool(report.get("ok", False))
            else:
                # A gate function is contractually Callable[[], dict]. A
                # non-dict return (e.g. a gate implementation missing its
                # `return rep` statement) is a broken gate, not a passing
                # one -- fail closed instead of silently tallying it as ok.
                ok = False
                report = {
                    "ok": False,
                    "error": f"gate function returned non-dict: {report!r}",
                }
            elapsed = time.perf_counter() - t0
            self.results.append(GateRunRecord(stage, gate, ok, report, elapsed))
            return report
        except Exception as e:
            elapsed = time.perf_counter() - t0
            report = {"ok": False, "error": str(e)}
            self.results.append(GateRunRecord(stage, gate, False, report, elapsed))
            return report

    def finalize(self) -> dict:
        failed = [r for r in self.results if not r.ok]
        if self.strict and failed:
            lines = "\n".join(
                f"  FAIL  {r.stage}/{r.gate}: {r.detail}"
                for r in failed
            )
            raise RuntimeError(
                f"Cumulative gate runner: {len(failed)}/{len(self.results)} gates failed\n{lines}"
            )
        return {
            "total": len(self.results),
            "passed": len(self.results) - len(failed),
            "failed": len(failed),
            "results": [asdict(r) for r in self.results],
        }
