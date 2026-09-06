"""Entrypoint modules must never mutate `builtins.print` at import time.

Root cause (confirmed 2026-09-06): `ultimate_pipeline/run_pipeline.py`,
`ultimate_pipeline/cli.py`, `ultimate_pipeline/run_quality_gates.py`, and
`ultimate_pipeline/run_determinism_audit.py` all called
`enable_timestamped_print()` at module scope. Because Python caches imports
process-wide, the *first* test in a pytest session that imports any of these
modules (directly or transitively) permanently monkeypatches `builtins.print`
for every other test that runs afterward in the same process -- corrupting
any later test that does `print(json.dumps(...))` and parses the captured
stdout (e.g. `test_find_broken_roads_cli.py`'s JSON-mode test failed in CI
with this exact signature: a `[YYYY-MM-DD HH:MM:SS] ` prefix breaking the
JSON parser). Each check here runs in a fresh subprocess because the bug is
about process-global state that a same-process test cannot observe cleanly
once any other test has already imported one of these modules.
"""
from __future__ import annotations

import subprocess
import sys

_CHECK_TEMPLATE = """
import builtins
import sys
_orig = builtins.print
import {module}
# Use sys.stdout.write (not print()) for the verdict itself: print() resolves
# `print` at call time, so if the import under test already patched it, a
# print()-based verdict would come back wrapped in a timestamp prefix too and
# silently mask the very mutation being detected.
sys.stdout.write("CHANGED" if builtins.print is not _orig else "SAME")
"""

_ENTRYPOINT_MODULES = [
    "ultimate_pipeline.run_pipeline",
    "ultimate_pipeline.cli",
    "ultimate_pipeline.run_quality_gates",
    "ultimate_pipeline.run_determinism_audit",
]


def _import_mutates_print(module: str) -> bool:
    code = _CHECK_TEMPLATE.format(module=module)
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"importing {module} crashed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    return result.stdout.strip() == "CHANGED"


def test_importing_run_pipeline_does_not_mutate_builtins_print() -> None:
    assert not _import_mutates_print("ultimate_pipeline.run_pipeline")


def test_importing_cli_does_not_mutate_builtins_print() -> None:
    assert not _import_mutates_print("ultimate_pipeline.cli")


def test_importing_run_quality_gates_does_not_mutate_builtins_print() -> None:
    assert not _import_mutates_print("ultimate_pipeline.run_quality_gates")


def test_importing_run_determinism_audit_does_not_mutate_builtins_print() -> None:
    assert not _import_mutates_print("ultimate_pipeline.run_determinism_audit")


def test_json_output_survives_prior_entrypoint_imports_in_same_process() -> None:
    """The concrete CI failure this guards against: importing an entrypoint
    module earlier in a process must not corrupt later print(json.dumps(...))
    calls in that same process."""
    code = """
import json
import ultimate_pipeline.run_pipeline  # noqa: F401 -- simulate prior import in the same process
import ultimate_pipeline.cli  # noqa: F401
print(json.dumps({"ok": True, "value": 42}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    last_line = result.stdout.strip().splitlines()[-1]
    parsed = __import__("json").loads(last_line)
    assert parsed == {"ok": True, "value": 42}
