from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest


def _safe_addoption(parser: Any, *args: Any, **kwargs: Any) -> None:
    # Pytest may load multiple conftest.py files; duplicates should not crash test startup.
    try:
        parser.addoption(*args, **kwargs)
    except ValueError as e:
        if "already added" not in str(e):
            raise


def pytest_addoption(parser) -> None:
    # IMPORTANT: signature must be (parser), not a default value, not a string.
    _safe_addoption(
        parser,
        "--import-all",
        action="store_true",
        default=False,
        help="Import all entrypoint modules to ensure they are import-safe.",
    )


@pytest.fixture(scope="session")
def repo_root() -> Path:
    # Walk upwards until we find the repository root that contains "ultimate_pipeline/"
    here = Path(__file__).resolve()
    for p in [here.parent] + list(here.parents):
        if (p / "ultimate_pipeline").is_dir():
            return p
    # Fallback: parent of tests/
    return here.parents[1]

@pytest.fixture(autouse=True, scope="session")
def _ensure_subprocess_can_import_repo(repo_root: Path) -> None:
    # Ensure subprocess calls (python -m ultimate_pipeline...) can import the repo
    root = str(repo_root)
    cur = os.environ.get("PYTHONPATH", "")
    parts = [p for p in cur.split(os.pathsep) if p]
    if root not in parts:
        parts.insert(0, root)
        os.environ["PYTHONPATH"] = os.pathsep.join(parts)

