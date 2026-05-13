"""Compatibility pytest bootstrap for ``ultimate_pipeline.tests.conftest`` imports."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PKG_DIR = Path(__file__).resolve().parents[1]      # .../ultimate_pipeline
REPO_ROOT = PKG_DIR.parent                         # directory containing the package

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def pytest_addoption(parser) -> None:
    """Custom CLI options used across the test suite."""
    parser.addoption(
        "--import-all",
        action="store_true",
        default=False,
        help="Import all modules in test_import_all_modules (may be slow).",
    )


@pytest.fixture
def repo_root(pytestconfig) -> Path:
    return REPO_ROOT
