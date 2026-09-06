#!/usr/bin/env python3
"""Package-smoke check for pyproject.toml's packaging config.

Builds a real wheel, installs it into a throwaway venv, and verifies the
three top-level packages (ultimate_pipeline, opendrive_geometry, phase_q)
import from the *installed wheel*, not from this source checkout.

Background: pyproject.toml previously declared `packages =
["ultimate_pipeline"]`, silently excluding opendrive_geometry/ (imported by
ultimate_pipeline.domain_gap/enrichment/tiling) and phase_q/ (imported by
the root-level govern_load_payload.py). A wheel built from that config would
raise ImportError on first use of either package. This script is the
regression guard for that packaging bug -- run it after any pyproject.toml
packaging change.

IMPORTANT: must run with PYTHONPATH unset/empty. A PYTHONPATH pointing at
this repo (common in this project's dev shells) shadows the installed
wheel with the source tree, making a broken package look fine. This script
clears its own PYTHONPATH for the subprocess calls it makes, but if you
import this module's functions directly in a process that already has the
repo on sys.path, the checks below will not be meaningful.

Usage:
    python scripts/package_smoke_check.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PACKAGES = ["ultimate_pipeline", "opendrive_geometry", "phase_q"]


def _clean_env() -> dict:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return env


def build_wheel(out_dir: Path) -> Path:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(out_dir), str(REPO_ROOT)],
        capture_output=True,
        text=True,
        env=_clean_env(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"wheel build failed:\n{result.stdout}\n{result.stderr}")
    wheels = list(out_dir.glob("*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly 1 wheel, found {wheels}")
    return wheels[0]


def check_wheel_contents(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as z:
        names = z.namelist()
    top_level = {n.split("/")[0] for n in names if "/" in n}
    missing = [p for p in EXPECTED_PACKAGES if p not in top_level]
    if missing:
        raise AssertionError(f"wheel is missing expected package(s): {missing} (found: {sorted(top_level)})")
    leaked_tests = [n for n in names if n.split("/")[0] == "tests"]
    if leaked_tests:
        raise AssertionError(f"wheel unexpectedly includes tests/ ({len(leaked_tests)} files)")


def install_and_verify(wheel_path: Path, venv_dir: Path) -> None:
    venv.create(venv_dir, with_pip=True)
    venv_python = venv_dir / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python"
    )
    env = _clean_env()

    result = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel_path)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(venv_dir),  # run outside the repo so cwd can't shadow the install
    )
    if result.returncode != 0:
        raise RuntimeError(f"wheel install failed:\n{result.stdout}\n{result.stderr}")

    check_code = (
        "import sys, json\n"
        f"expected = {EXPECTED_PACKAGES!r}\n"
        "result = {}\n"
        "for name in expected:\n"
        "    mod = __import__(name)\n"
        "    result[name] = mod.__file__\n"
        "print(json.dumps(result))\n"
    )
    result = subprocess.run(
        [str(venv_python), "-c", check_code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(venv_dir),
    )
    if result.returncode != 0:
        raise RuntimeError(f"import check failed:\n{result.stdout}\n{result.stderr}")

    import json

    locations = json.loads(result.stdout.strip().splitlines()[-1])
    venv_dir_str = str(venv_dir)
    repo_root_str = str(REPO_ROOT)
    for name, file_path in locations.items():
        if repo_root_str in file_path:
            raise AssertionError(
                f"{name} resolved to the source checkout ({file_path}), not the "
                f"installed wheel -- PYTHONPATH is likely leaking into the check"
            )
        if venv_dir_str not in file_path:
            raise AssertionError(f"{name} resolved to an unexpected location: {file_path}")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="up_package_smoke_") as tmp:
        tmp_path = Path(tmp)
        wheel_dir = tmp_path / "wheel"
        venv_dir = tmp_path / "venv"
        wheel_dir.mkdir()

        print("Building wheel (no deps)...")
        wheel_path = build_wheel(wheel_dir)
        print(f"  built {wheel_path.name}")

        print("Checking wheel contents...")
        check_wheel_contents(wheel_path)
        print(f"  OK: all of {EXPECTED_PACKAGES} present, tests/ excluded")

        print("Installing into a fresh venv and verifying imports resolve to it...")
        install_and_verify(wheel_path, venv_dir)
        print("  OK: all packages import from the installed wheel")

    print("PACKAGE SMOKE CHECK: PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, AssertionError) as exc:
        print(f"PACKAGE SMOKE CHECK: FAIL\n{exc}", file=sys.stderr)
        raise SystemExit(1)
