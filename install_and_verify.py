#!/usr/bin/env python3
"""
CARLA Ops Studio - Clean-room installation and verification script.

This script performs a complete installation from a clean environment and
verifies that the application launches correctly in offline mode.

Usage:
    python install_and_verify.py [--gui] [--runtime] [--dev] [--help]

Options:
    --gui       Install with GUI dependencies (PyQt6)
    --runtime   Install with CARLA runtime dependencies
    --dev       Install with development dependencies (pytest, ruff, mypy)
    --help      Show this help message

Environment:
    CARLA_GUI_TARGET    Target directory for installation (default: ./carla_ops_env)
    CARLA_GUI_PYTHON    Python executable to use (default: python3)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def verify_imports(venv_python: Path) -> tuple[bool, list[str]]:
    """Verify that all required modules can be imported."""
    checks = [
        ("carla", "import carla; print(carla.__version__)"),
        ("PyQt6", "from PyQt6 import QtCore; print(QtCore.PYQT_VERSION_STR)"),
        ("cv2", "import cv2; print(cv2.__version__)"),
        ("numpy", "import numpy; print(numpy.__version__)"),
        ("pydantic", "import pydantic; print(pydantic.VERSION)"),
        ("ultimate_pipeline", "import ultimate_pipeline; print(ultimate_pipeline.__version__)"),
        ("ultimate_pipeline.gui", "import ultimate_pipeline.gui; print('gui ok')"),
        ("ultimate_pipeline.gui.shell", "import ultimate_pipeline.gui.shell; print('shell ok')"),
        ("ultimate_pipeline.gui.cli", "import ultimate_pipeline.gui.cli; print('cli ok')"),
    ]

    results = []
    ok = True
    for name, code in checks:
        r = subprocess.run(
            [str(venv_python), "-c", code],
            capture_output=True, text=True
        )
        if r.returncode == 0:
            results.append(f"  ✓ {name}: {r.stdout.strip()}")
        else:
            results.append(f"  ✗ {name}: {r.stderr.strip()}")
            ok = False
    return ok, results


def launch_gui_offscreen(venv_python: Path) -> tuple[bool, str]:
    """Launch the GUI in offscreen mode and verify it starts."""
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    # Use a short timeout and verify the process can start
    r = subprocess.run(
        [str(venv_python), "-c",
         "import sys; sys.path.insert(0, '.'); "
         "from ultimate_pipeline.gui.cli import main; "
         "sys.exit(main(['--verify-install']))"],
        capture_output=True, text=True, timeout=30, env=env
    )
    return r.returncode == 0, r.stdout + r.stderr


def main():
    parser = argparse.ArgumentParser(
        description="CARLA Ops Studio clean-room installation and verification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--gui", action="store_true", help="Install GUI dependencies")
    parser.add_argument("--runtime", action="store_true", help="Install CARLA runtime dependencies")
    parser.add_argument("--dev", action="store_true", help="Install development dependencies")
    parser.add_argument("--target", type=Path, default=Path("carla_ops_env"),
                        help="Target directory for virtual environment")
    parser.add_argument("--python", default=sys.executable, help="Python executable to use")
    args = parser.parse_args()

    if not (args.gui or args.runtime or args.dev):
        args.gui = True
        args.runtime = True

    target = args.target.resolve()
    python = Path(args.python).resolve()

    print(f"=== CARLA Ops Studio Installation ===")
    print(f"Target: {target}")
    print(f"Python: {python}")
    print(f"GUI: {args.gui}, Runtime: {args.runtime}, Dev: {args.dev}")

    # 1. Create virtual environment
    print("\n--- Creating virtual environment ---")
    if target.exists():
        print(f"Removing existing: {target}")
        shutil.rmtree(target)
    venv.create(target, with_pip=True)

    # Determine python executable in venv
    if sys.platform == "win32":
        venv_python = target / "Scripts" / "python.exe"
        venv_pip = target / "Scripts" / "pip.exe"
    else:
        venv_python = target / "bin" / "python"
        venv_pip = target / "bin" / "pip"

    # 2. Upgrade pip
    print("\n--- Upgrading pip ---")
    run([str(venv_pip), "install", "-U", "pip", "setuptools", "wheel"])

    # 3. Install the package in editable mode
    print("\n--- Installing package ---")
    repo_root = Path(__file__).parent.resolve()
    extras = []
    if args.gui:
        extras.append("gui")
    if args.runtime:
        extras.append("runtime")
    if args.dev:
        extras.append("dev")
    if args.gui or args.runtime:
        extras.append("geometry")
        extras.append("geo")
        extras.append("visualization")

    extra_spec = f"[{','.join(extras)}]" if extras else ""
    run([str(venv_pip), "install", "-e", f".{extra_spec}"], cwd=repo_root)

    # 4. Verify imports
    print("\n--- Verifying imports ---")
    ok, results = verify_imports(venv_python)
    for r in results:
        print(r)

    # 5. Launch GUI in offscreen mode
    print("\n--- Launching GUI in offscreen mode ---")
    gui_ok, gui_output = launch_gui_offscreen(venv_python)
    if gui_ok:
        print("  ✓ GUI launch successful")
    else:
        print(f"  ✗ GUI launch failed:\n{gui_output}")
        ok = False

    # 6. Run the test suite
    print("\n--- Running regression tests ---")
    test_env = os.environ.copy()
    test_env["QT_QPA_PLATFORM"] = "offscreen"
    test_result = subprocess.run(
        [str(venv_python), "-m", "pytest",
         "tests/unit/test_gui_status_freshness_audit_mock.py",
         "tests/unit/test_gui_settings_registry_profiles.py",
         "tests/unit/test_gui_session_tick_ownership.py",
         "tests/unit/test_gui_runtime_connection_tm_weather.py",
         "tests/unit/test_gui_calibration_vectors.py",
         "tests/unit/test_gui_maps_security_cook_gates.py",
         "tests/unit/test_gui_perception_truth_gating.py",
         "tests/unit/test_gui_jobs_governance.py",
         "tests/unit/test_gui_fuzz_safety.py",
         "tests/unit/test_gui_fuzz_mutators_oracles.py",
         "tests/unit/test_gui_fuzz_replay_shrink_corpus.py",
         "tests/unit/test_gui_qt_shell.py",
         "tests/unit/test_gui_qt_runtime_pages.py",
         "tests/unit/test_gui_security_hardening.py",
         "-q", "-p", "no:cacheprovider"],
        capture_output=True, text=True, cwd=repo_root, env=test_env, timeout=300
    )
    if test_result.returncode == 0:
        print(f"  ✓ Tests passed: {test_result.stdout.strip().splitlines()[-1]}")
    else:
        print(f"  ✗ Tests failed:")
        print(test_result.stdout[-2000:])
        print(test_result.stderr[-2000:])
        ok = False

    print("\n=== Installation Summary ===")
    if ok:
        print("  ✓ ALL CHECKS PASSED")
        print(f"\nTo launch the GUI:")
        print(f"  {venv_python} -m ultimate_pipeline.gui.cli")
        print(f"Or after activating the environment:")
        print(f"  carla-ops")
        return 0
    else:
        print("  ✗ SOME CHECKS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())