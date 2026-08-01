from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_run_full_perception_collect_dry_run(tmp_path: Path) -> None:
    tiles_dir = tmp_path / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    out_root = tmp_path / "collect_out"

    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.run_full_perception_collect",
        "--dry-run",
        "--tiles-dir",
        str(tiles_dir),
        "--out-root",
        str(out_root),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert "RQ3 STATUS: DRY_RUN" in proc.stdout

    summary_path = out_root / "collection_summary.json"
    assert summary_path.is_file()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert payload.get("dry_run") is True
    assert payload.get("manual_grid0821", {}).get("status") == "skipped"


def test_run_gnn_pipeline_dry_run_report(tmp_path: Path) -> None:
    tiles_dir = tmp_path / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    out_dir = tmp_path / "gnn_out"

    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.run_gnn_pipeline",
        "--dry-run",
        "--tiles-dir",
        str(tiles_dir),
        "--out-dir",
        str(out_dir),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr

    report_path = out_dir / "gnn_training_report.json"
    assert report_path.is_file()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert "torch_available" in payload
    assert payload.get("status") in {"DRY_RUN", "DEFERRED_MISSING_PYTORCH"}
