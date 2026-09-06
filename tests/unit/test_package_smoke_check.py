"""scripts/package_smoke_check.py::check_wheel_contents -- regression guard
for the pyproject.toml packaging bug (packages = ["ultimate_pipeline"]
silently excluded opendrive_geometry/ and phase_q/, both actively imported
elsewhere in the live pipeline). Uses synthetic in-memory wheels so this
runs at normal unit-test speed; the full build+install+import check lives in
scripts/package_smoke_check.py itself (network/venv-dependent, run manually).
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from package_smoke_check import check_wheel_contents  # noqa: E402


def _make_wheel(tmp_path: Path, top_level_dirs: list[str]) -> Path:
    wheel_path = tmp_path / "fake-0.0.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel_path, "w") as z:
        for d in top_level_dirs:
            z.writestr(f"{d}/__init__.py", "")
        z.writestr("fake-0.0.0.dist-info/METADATA", "Metadata-Version: 2.1\n")
    return wheel_path


def test_check_wheel_contents_passes_with_all_three_packages(tmp_path):
    wheel = _make_wheel(tmp_path, ["ultimate_pipeline", "opendrive_geometry", "phase_q"])
    check_wheel_contents(wheel)  # must not raise


def test_check_wheel_contents_rejects_missing_opendrive_geometry(tmp_path):
    """The exact bug this guards against: packages = ["ultimate_pipeline"]
    alone builds a wheel missing opendrive_geometry/ and phase_q/."""
    wheel = _make_wheel(tmp_path, ["ultimate_pipeline"])
    with pytest.raises(AssertionError, match="missing expected package"):
        check_wheel_contents(wheel)


def test_check_wheel_contents_rejects_missing_phase_q(tmp_path):
    wheel = _make_wheel(tmp_path, ["ultimate_pipeline", "opendrive_geometry"])
    with pytest.raises(AssertionError, match="missing expected package"):
        check_wheel_contents(wheel)


def test_check_wheel_contents_rejects_leaked_tests_dir(tmp_path):
    wheel = _make_wheel(
        tmp_path, ["ultimate_pipeline", "opendrive_geometry", "phase_q", "tests"]
    )
    with pytest.raises(AssertionError, match="tests/"):
        check_wheel_contents(wheel)
