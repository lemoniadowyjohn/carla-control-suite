"""Test B6 failure recovery campaign."""
from __future__ import annotations

import pytest

from tests.quality._b6_failure_injection import run_campaign


def test_failure_recovery_campaign() -> None:
    rows = run_campaign()
    for r in rows:
        assert r["PASS/FAIL"] == "PASS", f"Stage {r['stage']} failed: {r['observed']}"
    # Report summary
    print("B6 campaign completed successfully.")
    print(f"Total stages: {len(rows)}")
    passed = sum(1 for r in rows if r["PASS/FAIL"] == "PASS")
    print(f"Passed: {passed}, Failed: {len(rows)-passed}")