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

def test_invalid_tile_format(tmp_path):
    # Script expects 'tx,ty'. Route the report/artifact dirs into tmp_path so
    # this doesn't leave a stray "<run_id>_TILE_BASED_FBX_GENERATION_PROBE"
    # directory behind in the live repo tree (see
    # test_no_stray_report_dir_created_in_repo_tree below).
    result = run_cli(
        "--tile", "invalid",
        "--out-dir", str(tmp_path / "artifacts"),
        "--report-dir", str(tmp_path / "report"),
    )
    # This might fail during parsing or early execution.
    # split(') might raise ValueError if no comma.
    assert result.returncode != 0

def test_non_existent_osm2world(tmp_path):
    # Should fail during execution when it tries to use OSM2World. Route the
    # report/artifact dirs into tmp_path -- without --report-dir this test
    # used to leave a "<run_id>_TILE_BASED_FBX_GENERATION_PROBE" directory
    # (with a partial PROBE_RESULT.json) behind under
    # reports/production_readiness/ in the live repo tree on every run.
    result = run_cli(
        "--osm2world-home", "/tmp/non_existent_osm2world",
        "--out-dir", str(tmp_path / "artifacts"),
        "--report-dir", str(tmp_path / "report"),
    )
    # It will probably fail with FileNotFoundError or similar which script catches or bubbles up
    # In main() it returns 2 if result.status != "ok"
    assert result.returncode != 0

def test_out_dir_creation(tmp_path):
    out_dir = tmp_path / "artifacts"
    report_dir = tmp_path / "report"
    # Even if it fails later, it should create the out_dir
    run_cli(
        "--out-dir", str(out_dir),
        "--report-dir", str(report_dir),
        "--osm2world-home", "/tmp/non_existent",
    )
    assert out_dir.exists()

def test_no_stray_report_dir_created_in_repo_tree(tmp_path):
    """Regression test for a test-hygiene bug: probe_tile_fbx_densest.py
    always resolved its top-level report_dir (used for PROBE_RESULT.json)
    relative to the repo root, even when --out-dir redirected the tile
    artifacts elsewhere. Every failing/erroring CLI run -- including from
    this very test module -- left a real
    "<run_id>_TILE_BASED_FBX_GENERATION_PROBE" directory behind under
    reports/production_readiness/ in the live working tree. --report-dir
    now makes that fully injectable; this asserts no new directory shows up
    under reports/production_readiness/ after running CLI invocations that
    previously triggered the bug.
    """
    probe_root = REPO_ROOT / "reports" / "production_readiness"
    before = set(probe_root.iterdir()) if probe_root.exists() else set()

    out_dir = tmp_path / "artifacts"
    report_dir = tmp_path / "report"
    run_cli(
        "--osm2world-home", "/tmp/non_existent_osm2world",
        "--out-dir", str(out_dir),
        "--report-dir", str(report_dir),
    )
    run_cli(
        "--tile", "invalid",
        "--out-dir", str(out_dir),
        "--report-dir", str(report_dir),
    )

    after = set(probe_root.iterdir()) if probe_root.exists() else set()
    new_entries = after - before
    new_probe_dirs = {p for p in new_entries if p.name.endswith("_TILE_BASED_FBX_GENERATION_PROBE")}
    assert not new_probe_dirs, (
        f"stray probe report dir(s) created in live repo tree: {new_probe_dirs}"
    )
