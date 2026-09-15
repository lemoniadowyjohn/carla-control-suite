import subprocess
import sys
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "tools" / "stage_large_map_import_package.py"

def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH)] + list(args),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT)
    )

def test_missing_required_args_behavior():
    # This script actually has defaults for everything, so "missing args" won't fail parsing
    # but might fail execution if files don't exist.
    # Let's test --help first to ensure it's a valid argparse script.
    result = run_cli("--help")
    assert result.returncode == 0
    assert "Stage a CARLA Large-Map" in result.stdout

def test_invalid_argument():
    result = run_cli("--non-existent-argument")
    assert result.returncode != 0
    assert "unrecognized arguments: --non-existent-argument" in result.stderr

def test_invalid_xodr_path():
    # Pointing to a non-existent XODR should fail execution (exit code 2 as per script)
    result = run_cli("--xodr", "non_existent.xodr")
    assert result.returncode == 2
    assert "FAILED" in result.stdout

def test_invalid_sha256():
    # If we pass a real XODR but wrong SHA, it should fail.
    # Using the pinned XODR but passing a dummy SHA.
    result = run_cli("--expected-xodr-sha256", "wrong_sha")
    assert result.returncode == 2
    assert "FAILED" in result.stdout
    assert "sha256" in result.stdout.lower() or "sha256" in result.stderr.lower()

def test_import_root_creation_dry_run(tmp_path):
    # Test that it respects --import-root and fails gracefully if XODR is missing.
    import_root = tmp_path / "Import"
    result = run_cli("--import-root", str(import_root), "--xodr", "non_existent.xodr")
    assert result.returncode == 2
    assert "FAILED: xodr not found" in result.stdout
