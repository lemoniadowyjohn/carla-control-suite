# tests/unit/test_record_route_authority.py
# -*- coding: utf-8 -*-
"""P13/NEW-223: record_route_fixed is the single production capture authority."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY = "ultimate_pipeline.perception.record_route"
FIXED = "ultimate_pipeline.perception.record_route_fixed"

# Production scopes scanned for legacy capture-path references.
_SCOPES = [
    REPO_ROOT / "ultimate_pipeline",
    REPO_ROOT / "tools",
    REPO_ROOT / "scripts",
]

# Grandfathered legacy references (submission preservation / primitive reuse).
# - smoke_check_spawn.py imports tick/teardown helper primitives only, never
#   the legacy capture path (record_route_fixed does not export them).
# - smoke_check_all.py only smoke-imports the legacy module string.
_ALLOWLIST = {
    "ultimate_pipeline/tools/smoke_check_spawn.py",
    "ultimate_pipeline/tools/smoke_check_all.py",
}


def _production_files():
    for scope in _SCOPES:
        if not scope.is_dir():
            continue
        for path in sorted(scope.rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if "submission/" in rel:
                continue
            if rel in ("ultimate_pipeline/perception/record_route.py",
                       "ultimate_pipeline/perception/record_route_fixed.py"):
                continue
            yield rel, path


def _legacy_hits(text: str) -> list[str]:
    hits = []
    for pat in (r"-m\s+ultimate_pipeline\.perception\.record_route(?![\w_])",
                r"perception\s+import\s+record_route(?![\w_])",
                r"perception\.record_route\s+import",
                r"perception\.record_route\.(?!fixed)"):
        hits.extend(re.findall(pat, text))
    return hits


def test_no_new_legacy_capture_callers():
    offenders = {}
    for rel, path in _production_files():
        if rel in _ALLOWLIST:
            continue
        hits = _legacy_hits(path.read_text(encoding="utf-8", errors="ignore"))
        if hits:
            offenders[rel] = hits
    assert offenders == {}, f"new legacy record_route callers: {offenders}"


def test_allowlisted_files_do_not_invoke_legacy_capture():
    spawn = (REPO_ROOT / "ultimate_pipeline/tools/smoke_check_spawn.py").read_text(encoding="utf-8")
    assert "-m" not in spawn or "perception.record_route\"" not in spawn.replace(" ", "")
    assert "record_route_fixed" in spawn or "record_route import" in spawn


def test_run_auto_xodr_record_uses_fixed_authority():
    text = (REPO_ROOT / "ultimate_pipeline/tools/run_auto_xodr_record.py").read_text(encoding="utf-8")
    assert FIXED in text
    assert "perception.record_route\"" not in text


def test_auto_xodr_argv_parses_under_fixed():
    from ultimate_pipeline.perception.record_route_fixed import parse_args
    argv = ["--xodr", "m.xodr", "--calib", "c.json", "--out-dir", "o",
            "--spawn-index", "0", "--fps", "10", "--duration", "5",
            "--host", "h", "--port", "2000"]
    args = parse_args(argv)
    assert args.xodr == "m.xodr"
    assert args.fps == 10


def test_legacy_main_emits_deprecation():
    from ultimate_pipeline.perception import record_route
    with pytest.warns(DeprecationWarning):
        try:
            record_route.main(["--help"])
        except SystemExit:
            pass
