import subprocess
import sys
import pytest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "tools" / "probe_tile_fbx_densest.py"

def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH)] + list(args),
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT)
    )

def test_help():
    result = run_cli("--help")
    assert result.returncode == 0
    assert "cook the single densest 1 km tile" in result.stdout

def test_invalid_argument():
    result = run_cli("--unknown-flag")
    assert result.returncode != 0
    assert "unrecognized arguments: --unknown-flag" in result.stderr

def test_invalid_tile_format():
    # Script expects 'tx,ty'
    result = run_cli("--tile", "invalid")
    # This might fail during parsing or early execution.
    # split(') might raise ValueError if no comma.
    assert result.returncode != 0

def test_non_existent_osm2world():
    # Should fail during execution when it tries to use OSM2World
    result = run_cli("--osm2world-home", "/tmp/non_existent_osm2world")
    # It will probably fail with FileNotFoundError or similar which script catches or bubbles up
    # In main() it returns 2 if result.status != "ok"
    assert result.returncode != 0

def test_out_dir_creation(tmp_path):
    out_dir = tmp_path / "artifacts"
    # Even if it fails later, it should create the out_dir
    run_cli("--out-dir", str(out_dir), "--osm2world-home", "/tmp/non_existent")
    assert out_dir.exists()
