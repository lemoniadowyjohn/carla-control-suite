#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Thesis protocol post-processing for per-run artifacts.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from ultimate_pipeline.geometry.quarantine_bad_roads import (
    DEFAULT_THRESHOLDS,
    quarantine_bad_roads,
    write_quarantine_report,
)
from ultimate_pipeline.utils.file_hashing import safe_sha256_file
from ultimate_pipeline.utils.map_fingerprint import write_map_content_fingerprint


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _update_settings_snapshot(
    run_dir: Path,
    pipeline_out_dir: Optional[Path],
    *,
    bbox: Dict[str, float],
    osm_source: str,
    cli_args: Sequence[str],
) -> None:
    src = pipeline_out_dir / "settings_snapshot.json" if pipeline_out_dir else None
    if not src or not src.exists():
        return
    data = _load_json(src)
    if not isinstance(data, dict):
        return
    smoothing_params = {
        "MIN_GEOM_MERGE_LENGTH": data.get("MIN_GEOM_MERGE_LENGTH"),
        "MAX_GEOM_MERGE_LENGTH": data.get("MAX_GEOM_MERGE_LENGTH"),
        "CURVATURE_MAX_ALLOWED": data.get("CURVATURE_MAX_ALLOWED"),
    }
    data["_thesis_protocol"] = {
        "bbox": bbox,
        "osm_source": osm_source,
        "smoothing_params": smoothing_params,
        "quarantine_thresholds": {
            "max_fraction": os.getenv("UP_QUARANTINE_MAX_FRACTION", "0.008"),
            "continuity_dxy_max_m": os.getenv("UP_QUARANTINE_CONTINUITY_DXY", "1.0"),
            "continuity_dhdg_max_deg": os.getenv("UP_QUARANTINE_CONTINUITY_DHDG", "10.0"),
            "heading_jump_max_deg": os.getenv("UP_QUARANTINE_HEADING_JUMP_DEG", "30.0"),
            "curvature_abs_max": os.getenv("UP_QUARANTINE_CURVATURE_ABS", "0.5"),
            "curvature_jump_max": os.getenv("UP_QUARANTINE_CURVATURE_JUMP", "0.5"),
        },
        "cli_args": list(cli_args),
    }
    _write_json(run_dir / "settings_snapshot.json", data)


def _write_determinism_fingerprint(out_dir: Path, final_xodr: Path) -> None:
    payload = {
        "final_xodr": str(final_xodr),
        "final_xodr_sha256": safe_sha256_file(final_xodr) if final_xodr.exists() else "",
        "git_commit": None,
        "python_version": sys.version,
        "os_info": platform.platform(),
        "env": {k: v for k, v in os.environ.items() if k.startswith("UP_")},
        "seeds": {
            "deterministic_seed": os.getenv("UP_DETERMINISTIC_SEED"),
            "python_hash_seed": os.getenv("PYTHONHASHSEED"),
        },
    }
    try:
        payload["git_commit"] = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL)
            .decode("utf-8")
            .strip()
        )
    except Exception:
        payload["git_commit"] = None
    _write_json(out_dir / "determinism_fingerprint.json", payload)


def _load_continuity_report(search_dirs: Sequence[Path]) -> Optional[Dict[str, Any]]:
    candidates = [
        "geometric_continuity.json",
        "06_continuity__geometric_continuity.json",
    ]
    for d in search_dirs:
        if not d:
            continue
        qa_dir = d / "qa_stage_reports"
        for name in candidates:
            path = d / name
            if path.exists():
                report = _load_json(path)
                if isinstance(report, dict):
                    return report
            path = qa_dir / name
            if path.exists():
                report = _load_json(path)
                if isinstance(report, dict):
                    return report
    return None


def _apply_quarantine_if_enabled(
    final_xodr: Path,
    run_dir: Path,
    *,
    continuity_report: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    enabled = os.getenv("UP_ENABLE_ROAD_QUARANTINE", "").strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        return None
    thresholds = {
        "continuity_dxy_max_m": float(
            os.getenv("UP_QUARANTINE_CONTINUITY_DXY", DEFAULT_THRESHOLDS["continuity_dxy_max_m"])
        ),
        "continuity_dhdg_max_deg": float(
            os.getenv("UP_QUARANTINE_CONTINUITY_DHDG", DEFAULT_THRESHOLDS["continuity_dhdg_max_deg"])
        ),
        "heading_jump_max_deg": float(
            os.getenv("UP_QUARANTINE_HEADING_JUMP_DEG", DEFAULT_THRESHOLDS["heading_jump_max_deg"])
        ),
        "curvature_abs_max": float(
            os.getenv("UP_QUARANTINE_CURVATURE_ABS", DEFAULT_THRESHOLDS["curvature_abs_max"])
        ),
        "curvature_jump_max": float(
            os.getenv("UP_QUARANTINE_CURVATURE_JUMP", DEFAULT_THRESHOLDS["curvature_jump_max"])
        ),
    }
    max_fraction = float(os.getenv("UP_QUARANTINE_MAX_FRACTION", 0.008))
    report = quarantine_bad_roads(
        str(final_xodr),
        str(final_xodr),
        continuity_report=continuity_report,
        max_fraction=max_fraction,
        thresholds=thresholds,
    )
    report["continuity_issues"] = continuity_report.get("num_issues") if continuity_report else None
    report["max_fraction"] = max_fraction
    write_quarantine_report(str(run_dir / "roads_quarantined.json"), report)
    return report


def postprocess_thesis_artifacts(
    run_dir: Path,
    final_xodr: Path,
    *,
    pipeline_out_dir: Optional[Path],
    cli_args: Sequence[str],
    bbox: Dict[str, float],
    osm_source: str,
) -> None:
    continuity_report = _load_continuity_report([run_dir, pipeline_out_dir] if pipeline_out_dir else [run_dir])
    _apply_quarantine_if_enabled(final_xodr, run_dir, continuity_report=continuity_report)
    write_map_content_fingerprint(str(run_dir), str(final_xodr))
    _write_determinism_fingerprint(run_dir, final_xodr)
    _update_settings_snapshot(
        run_dir,
        pipeline_out_dir,
        bbox=bbox,
        osm_source=osm_source,
        cli_args=cli_args,
    )
