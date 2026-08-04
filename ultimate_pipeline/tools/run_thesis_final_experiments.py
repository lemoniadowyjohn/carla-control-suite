#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.osm.osm_to_xodr_wrapper import OSMToXODRConfig, convert_osm_to_xodr
from ultimate_pipeline.osm.osm_downloader import ensure_osm_exists

from ultimate_pipeline.quality.check_lane_link_targets_exist import check_lane_link_targets_exist
from ultimate_pipeline.experiments.thesis.manual_refs import resolve_manual_town
from ultimate_pipeline.tools.thesis_protocol_postprocess import postprocess_thesis_artifacts
from ultimate_pipeline.quality.map_acceptance import build_map_acceptance
from ultimate_pipeline.determinism.stage_digest import generate_stage_hashes
from ultimate_pipeline.tools.system_metrics_monitor import start_system_metrics_monitor

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "ultimate_pipeline_out"
DEFAULT_MANUAL_MAP = REPO_ROOT / "manual_maps" / "manual_ingolstadt_grid0828.xodr"
DEFAULT_MANUAL_TOWN = "Grid0828"
DEFAULT_CALIB = REPO_ROOT / "ultimate_pipeline" / "sensors" / "calib_data.json"
DEFAULT_CARLA_HOST = os.getenv("UP_CARLA_HOST", "127.0.0.1")
DEFAULT_CARLA_PORT = int(os.getenv("UP_CARLA_PORT", "2000"))
DEFAULT_RECORD_FRAMES = 200
DEFAULT_RECORD_FPS = 20
MAX_AUTO_REPEATS = 2
DEFAULT_ARTIFACT_SAMPLE = 50

SUBDIR_ORDER = [
    "00_env",
    "01_manual_baseline",
    "02_auto_repeat_1",
    "03_auto_repeat_2",
    "04_auto_repeat_3",
    "05_visual_qa",
    "06_perception_manual",
    "07_perception_auto_best",
    "08_summary_tables",
]

INGOLSTADT_BBOX = {
    "lat_min": 48.74935649548228,
    "lat_max": 48.77444431571603,
    "lon_min": 11.422268084715878,
    "lon_max": 11.47882091528412,
}

AUTO_PERCEPTION_SKIP_REASON = "no_auto_map_passed_lane_link_gate"


def _resolve_osm_path() -> Path:
    env_path = os.getenv("UP_OSM_FILE", "").strip()
    if env_path:
        return Path(env_path).expanduser()
    cfg_path = getattr(SETTINGS, "OSM_FILE", "")
    if cfg_path:
        return Path(cfg_path).expanduser()
    return Path("")


def _read_git_info(repo: Path) -> Dict[str, str]:
    result: Dict[str, str] = {}
    try:
        result["sha"] = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo)
            .strip()
            .decode("utf-8")
        )
        status = (
            subprocess.check_output(["git", "status", "--porcelain"], cwd=repo)
            .strip()
        )
        result["dirty"] = "yes" if status else "no"
    except Exception:
        result["sha"] = "unknown"
        result["dirty"] = "unknown"
    return result


def _ensure_dirs(base: Path) -> Dict[str, Path]:
    dirs: Dict[str, Path] = {}
    for name in SUBDIR_ORDER:
        target = base / name
        target.mkdir(parents=True, exist_ok=True)
        (target / "logs").mkdir(exist_ok=True)
        dirs[name] = target
    return dirs


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 16):
            digest.update(chunk)
    return digest.hexdigest()


def _structural_counts(xodr_path: Path) -> Dict[str, int]:
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    return {
        "roads": len(root.findall(".//road")),
        "junctions": len(root.findall(".//junction")),
        "lane_sections": len(root.findall(".//laneSection")),
        "coor_points": len(root.findall(".//planView/geometry")),
    }


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_report_from_dirs(name: str, search_dirs: Sequence[Path]) -> Optional[Dict[str, Any]]:
    for d in search_dirs:
        if not d:
            continue
        candidate = d / name
        report = _load_json(candidate)
        if isinstance(report, dict):
            report.setdefault("artifact_path", str(candidate))
            return report
    return None


def _build_map_acceptance_for_run(
    *,
    final_xodr: Path,
    run_dir: Path,
    lane_link_report: Optional[Dict[str, Any]],
    search_dirs: Sequence[Path],
) -> Dict[str, Any]:
    reports: Dict[str, Any] = {}
    if isinstance(lane_link_report, dict):
        reports["lane_connectivity"] = dict(lane_link_report)
        reports["lane_connectivity"].setdefault(
            "artifact_path",
            str(run_dir / "lane_link_target_report.json"),
        )
    report_map = {
        "dem_coverage": "dem_coverage.json",
        "elevation_seams": "elevation_seam_report.json",
        "geometric_continuity": "geometric_continuity.json",
        "origin_sanity": "origin_sanity.json",
        "lane_section_successors": "lane_section_successors.json",
    }
    for key, fname in report_map.items():
        rep = _load_report_from_dirs(fname, search_dirs)
        if rep:
            reports[key] = rep

    return build_map_acceptance(
        reports,
        run_id=run_dir.name,
        final_xodr_path=str(final_xodr),
        out_dir=str(run_dir),
    )

def _find_default_manual_map(manual_town: str = DEFAULT_MANUAL_TOWN) -> Tuple[Optional[Path], List[str]]:
    preferred_town = str(manual_town or DEFAULT_MANUAL_TOWN).strip() or DEFAULT_MANUAL_TOWN
    fallback_towns = [preferred_town] + [t for t in ("Grid0828", "Grid0821") if t != preferred_town]
    resolver_notes: List[str] = []
    for town in fallback_towns:
        try:
            ref = resolve_manual_town(town)
            candidate = Path(str(ref.get("manual_xodr_path", ""))).expanduser().resolve()
            if candidate.is_file():
                return candidate, []
        except Exception as exc:
            resolver_notes.append(f"{town}:{exc}")

    manual_root = REPO_ROOT / "manual_maps"
    candidates: List[Path] = []
    for town in fallback_towns:
        town_lower = town.lower()
        candidates.extend(
            [
                p
                for p in manual_root.rglob("*.xodr")
                if town_lower in p.name.lower() or town_lower in str(p.parent).lower()
            ]
        )
    if candidates:
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0], []

    all_xodr = sorted(manual_root.rglob("*.xodr"))
    sample = [str(p) for p in all_xodr[:5]]
    sample.extend(resolver_notes[:5])
    return None, sample


def _run_subprocess(
    cmd: Sequence[str],
    log_path: Path,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[Path] = None,
    dry_run: bool = False,
) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if dry_run:
        log_path.write_text(f"[DRY-RUN] {' '.join(cmd)}\n", encoding="utf-8")
        return 0
    # Windows console encoding guard: force UTF-8 decoding of child output
    env_eff = (env or os.environ).copy()
    env_eff.setdefault("PYTHONUTF8", "1")
    env_eff.setdefault("PYTHONIOENCODING", "utf-8")
    with log_path.open("w", encoding="utf-8") as logfile:
        logfile.write(f"$ {' '.join(cmd)}\n\n")
        process = subprocess.run(
            cmd,
            cwd=cwd or REPO_ROOT,
            env=env_eff,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        logfile.write(process.stdout)
    return process.returncode


def _ensure_artifacts_dir(run_dir: Path) -> Path:
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    return artifacts


def _run_osm_stats(osm_path: Path, run_dir: Path, *, dry_run: bool) -> None:
    if not osm_path.is_file():
        return
    artifacts = _ensure_artifacts_dir(run_dir)
    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.osm_stats",
        "--osm",
        str(osm_path),
        "--out",
        str(artifacts),
    ]
    _run_subprocess(cmd, artifacts / "osm_stats.log", dry_run=dry_run)


def _run_carla_smoke_suite(
    xodr_path: Path,
    run_dir: Path,
    *,
    host: str,
    port: int,
    timeout: float,
    dry_run: bool,
) -> None:
    artifacts = _ensure_artifacts_dir(run_dir)
    out_dir = artifacts / "carla_smoke_suite"
    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.carla_smoke_suite",
        "--xodr",
        str(xodr_path),
        "--out",
        str(out_dir),
        "--host",
        host,
        "--port",
        str(port),
        "--timeout",
        str(timeout),
    ]
    _run_subprocess(cmd, artifacts / "carla_smoke_suite.log", dry_run=dry_run)


def _run_artifact_integrity(run_dir: Path, *, sample: int, dry_run: bool) -> None:
    artifacts = _ensure_artifacts_dir(run_dir)
    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.artifact_integrity_check",
        "--run-dir",
        str(run_dir),
        "--sample",
        str(sample),
    ]
    _run_subprocess(cmd, artifacts / "artifact_integrity.log", dry_run=dry_run)


def _summary_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _apply_stage_hashes(stage_dir: Path, manifest: Dict[str, Any]) -> None:
    digest = generate_stage_hashes(stage_dir)
    manifest["hash_sources"] = [entry["relpath"] for entry in digest["files"]]
    manifest["stage_digest_sha256"] = digest["stage_digest_sha256"]


def _existing_run_dirs() -> Set[str]:
    if not OUTPUT_ROOT.exists():
        return set()
    names = set()
    for p in OUTPUT_ROOT.iterdir():
        if not p.is_dir():
            continue
        if p.name == "thesis_final_runs" or p.name.startswith("thesis_final_runs"):
            continue
        names.add(p.name)
    return names


def _find_latest_run_dir(exclude: Set[str]) -> Path:
    candidates = []
    if OUTPUT_ROOT.exists():
        for p in OUTPUT_ROOT.iterdir():
            if not p.is_dir():
                continue
            if p.name in exclude:
                continue
            if p.name.startswith("thesis_final_runs"):
                continue
            if p.name == "thesis_final_runs":
                continue
            candidates.append(p)
    if not candidates:
        raise FileNotFoundError("No run directories found under ultimate_pipeline_out.")
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _find_final_xodr(run_dir: Path) -> Path:
    patterns = list(run_dir.glob("**/08_final*.xodr"))
    if not patterns:
        raise FileNotFoundError(f"No 08_final*.xodr found in {run_dir}")
    patterns.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return patterns[0]


def _run_carla_probe(
    xodr_path: Path,
    out_dir: Path,
    host: str,
    port: int,
    frames: int,
    dry_run: bool,
) -> Dict[str, Any]:
    probe_out = out_dir / "probe_result.json"
    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.carla_probe_map",
        "--xodr",
        str(xodr_path),
        "--out",
        str(out_dir),
        "--host",
        host,
        "--port",
        str(port),
        "--frames",
        str(frames),
    ]
    ret = _run_subprocess(cmd, out_dir / "carla_probe.log", dry_run=dry_run)
    if dry_run:
        return {
            "status": "SKIP",
            "failure_reason": "dry_run",
            "host": host,
            "port": port,
            "frames": frames,
        }
    if probe_out.exists():
        return json.loads(probe_out.read_text(encoding="utf-8"))
    return {
        "status": "FAIL",
        "failure_reason": f"probe_exit_{ret}",
        "host": host,
        "port": port,
        "frames": frames,
    }


def _run_capture_rgb(
    xodr_path: Path,
    calib_path: Path,
    out_dir: Path,
    host: str,
    port: int,
    frames: int,
    fps: int,
    dry_run: bool,
) -> Dict[str, Any]:
    summary_path = out_dir / "recording_summary.json"
    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.capture_rgb_200frames",
        "--xodr",
        str(xodr_path),
        "--calib",
        str(calib_path),
        "--out",
        str(out_dir),
        "--host",
        host,
        "--port",
        str(port),
        "--frames",
        str(frames),
        "--fps",
        str(fps),
    ]
    ret = _run_subprocess(cmd, out_dir / "perception_capture.log", dry_run=dry_run)
    if dry_run:
        return {
            "status": "SKIP",
            "failure_reason": "dry_run",
            "host": host,
            "port": port,
            "frames": frames,
            "fps": fps,
        }
    if summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))
    return {
        "status": "FAIL",
        "failure_reason": f"capture_exit_{ret}",
        "host": host,
        "port": port,
        "frames": frames,
        "fps": fps,
    }


def _write_lane_link_report(xodr_path: Path, out_path: Path) -> Dict[str, Any]:
    report = check_lane_link_targets_exist(str(xodr_path))
    _write_json(out_path, report)
    return report


def _run_osm_determinism(
    osm_path: Path,
    summary_dir: Path,
    cfg: OSMToXODRConfig,
    *,
    dry_run: bool,
) -> None | dict[str, str | dict[str, float]] | dict[str | Any, str | dict[str, float] | bool | Any]:
    summary_path = summary_dir / "osm_to_xodr_determinism.json"
    if dry_run:
        payload = {
            "status": "SKIP",
            "failure_reason": "dry_run",
            "osm_path": str(osm_path),
            "tool_path": cfg.tool_path or "",
            "bbox": INGOLSTADT_BBOX,
        }
        _write_json(summary_path, payload)
        return payload

    if not osm_path.is_file():
        payload = {
            "status": "FAIL",
            "failure_reason": "osm_missing",
            "osm_path": str(osm_path),
            "tool_path": cfg.tool_path or "",
            "bbox": INGOLSTADT_BBOX,
        }
        _write_json(summary_path, payload)
        return payload

    ts1 = datetime.utcnow().isoformat() + "Z"
    out1 = summary_dir / "_osm_to_xodr_det_1.xodr"
    out2 = summary_dir / "_osm_to_xodr_det_2.xodr"
    payload = {
        "status": "FAIL",
        "failure_reason": "",
        "osm_path": str(osm_path),
        "tool_path": cfg.tool_path or "",
        "bbox": INGOLSTADT_BBOX,
        "input_osm_sha256": "",
        "output1_sha256": "",
        "output2_sha256": "",
        "identical": False,
        "timestamp_1": ts1,
        "timestamp_2": "",
    }
    try:
        payload["input_osm_sha256"] = _hash_path(osm_path)
        convert_osm_to_xodr(osm_path, out1, cfg=cfg)
        payload["output1_sha256"] = _hash_path(out1)
        payload["timestamp_2"] = datetime.utcnow().isoformat() + "Z"
        convert_osm_to_xodr(osm_path, out2, cfg=cfg)
        payload["output2_sha256"] = _hash_path(out2)
        payload["identical"] = payload["output1_sha256"] == payload["output2_sha256"]
        payload["status"] = "PASS"
    except Exception as exc:  # noqa: BLE001
        payload["failure_reason"] = str(exc)
        _write_json(summary_path, payload)
        return payload


def collect_manual_summary(manual_map: Path) -> Dict[str, Any]:
    return {
        "map_id": manual_map.stem,
        "map_type": "manual",
        "xodr_path": str(manual_map),
        "sha256": _hash_path(manual_map),
        **_structural_counts(manual_map),
    }


def run_auto_repeats(
    manual_map: Path,
    subdirs: Dict[str, Path],
    base_tag: str,
    repeats: int,
    *,
    carla_host: str,
    carla_port: int,
    artifact_sample: int | None = 25,
    refresh_osm: bool = False,
    dry_run: bool,
) -> List[Dict[str, Any]]:
    global final_copy
    runs: List[Dict[str, Any]] = []
    names = ["02_auto_repeat_1", "03_auto_repeat_2"][: min(repeats, MAX_AUTO_REPEATS)]
    osm_path = _resolve_osm_path()
    if not str(osm_path):
        osm_path = (REPO_ROOT / 'ultimate_pipeline' / 'cities' / 'ingolstadt' / 'osm' / 'ingolstadt.osm')
    # Optionally refresh/download OSM when requested
    if refresh_osm or (os.getenv('UP_FORCE_OSM_DOWNLOAD','').strip() or os.getenv('UP_REFRESH_OSM','').strip()):
        ensure_osm_exists(INGOLSTADT_BBOX, osm_path)
    osm_exists = osm_path.is_file()
    cfg = OSMToXODRConfig(
        carla_root=os.getenv("CARLA_ROOT") or os.getenv("CARLA_HOME"),
        tool_path=getattr(SETTINGS, "OSM_TO_XODR_TOOL", None),
        overwrite=True,
    )
    for idx, subdir_name in enumerate(names):
        run_dir = subdirs[subdir_name]
        log_path = run_dir / "logs" / "pipeline.log"
        env = os.environ.copy()
        pipeline_out_dir = run_dir / "pipeline_out"
        env["UP_OUTPUT_DIR"] = str(pipeline_out_dir)
                run_tag = f"{base_tag}_auto_{idx+1}"
        map_id = f"auto_repeat_{idx+1}"
        generated_xodr = run_dir / f"generated_from_osm_{idx+1}.xodr"
        osm_manifest_path = run_dir / "osm_to_xodr_manifest.json"

        osm_manifest = {
            "status": "FAIL",
            "failure_reason": "",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "osm_path": str(osm_path),
            "osm_sha256": _hash_path(osm_path) if osm_exists else "",
            "xodr_path": str(generated_xodr),
            "xodr_sha256": "",
            "bbox": INGOLSTADT_BBOX,
            "tool_path": cfg.tool_path or "",
        }

        if dry_run:
            osm_manifest["status"] = "SKIP"
            osm_manifest["failure_reason"] = "dry_run"
            _write_json(osm_manifest_path, osm_manifest)
            runs.append(
                {
                    "tag": run_tag,
                    "summary": {"map_id": map_id, "status": "SKIP", "failure_reason": "dry_run"},
                    "output_dir": Path("dry_run_output"),
                    "probe": {"status": "SKIP", "failure_reason": "dry_run"},
                    "failure_stage": "dry_run",
                    "run_dir": run_dir,
                }
            )
            _run_osm_stats(osm_path, run_dir, dry_run=dry_run)
            _run_artifact_integrity(run_dir, sample=int(artifact_sample or 25), dry_run=dry_run)
            continue

        if not osm_exists:
            osm_manifest["failure_reason"] = "osm_missing"
            _write_json(osm_manifest_path, osm_manifest)
            _write_json(
                run_dir / "structural_summary.json",
                {"map_id": map_id, "status": "FAIL", "failure_reason": "conversion_missing"},
            )
            runs.append(
                {
                    "tag": run_tag,
                    "summary": {"map_id": map_id, "status": "FAIL", "failure_reason": "conversion_missing"},
                    "output_dir": None,
                    "probe": {"status": "FAIL", "failure_reason": "conversion_missing"},
                    "failure_stage": "conversion_missing",
                    "run_dir": run_dir,
                }
            )
            _run_osm_stats(osm_path, run_dir, dry_run=dry_run)
            _run_artifact_integrity(run_dir, sample=int(artifact_sample or 25), dry_run=dry_run)
            continue

        try:
            convert_osm_to_xodr(osm_path, generated_xodr, cfg=cfg)
            osm_manifest["status"] = "PASS"
            osm_manifest["xodr_sha256"] = _hash_path(generated_xodr)
        except Exception as exc:  # noqa: BLE001
            osm_manifest["failure_reason"] = str(exc)
            _write_json(osm_manifest_path, osm_manifest)
            _write_json(
                run_dir / "structural_summary.json",
                {"map_id": map_id, "status": "FAIL", "failure_reason": "conversion_missing"},
            )
            runs.append(
                {
                    "tag": run_tag,
                    "summary": {"map_id": map_id, "status": "FAIL", "failure_reason": "conversion_missing"},
                    "output_dir": None,
                    "probe": {"status": "FAIL", "failure_reason": "conversion_missing"},
                    "failure_stage": "conversion_missing",
                    "run_dir": run_dir,
                }
            )
            _run_osm_stats(osm_path, run_dir, dry_run=dry_run)
            _run_artifact_integrity(run_dir, sample=int(artifact_sample or 25), dry_run=dry_run)
            continue
        _write_json(osm_manifest_path, osm_manifest)

        env["UP_INPUT_XODR"] = str(generated_xodr)
        before = _existing_run_dirs()
        cmd = [sys.executable, "-m", "ultimate_pipeline.run_pipeline"]
        ret = _run_subprocess(cmd, log_path, env=env, dry_run=dry_run)
        newest_dir = None
        final_xodr = None
        try:
            newest_dir = _find_latest_run_dir(before)
            final_xodr = _find_final_xodr(newest_dir)
        except Exception:
            final_xodr = None

        summary: Dict[str, Any]
        probe_result: Dict[str, Any]
        failure_stage = ""
        lane_link_ok = False

        if final_xodr and final_xodr.exists():
            drop_candidates = list(pipeline_out_dir.glob("**/*DROP_BAD_LINKS*.xodr"))
            if drop_candidates:
                drop_candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                final_xodr = drop_candidates[0]
            final_copy = run_dir / "final_map.xodr"
            final_copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(final_xodr, final_copy)

            postprocess_thesis_artifacts(
                run_dir,
                final_copy,
                pipeline_out_dir=pipeline_out_dir,
                cli_args=sys.argv,
                bbox=INGOLSTADT_BBOX,
                osm_source=str(_resolve_osm_path()),
            )

            lane_link_report = _write_lane_link_report(final_copy, run_dir / "lane_link_target_report.json")
            lane_link_ok = bool(lane_link_report.get("ok"))

            summary = _structural_counts(final_copy)
            summary.update(
                {
                    "map_id": map_id,
                    "map_type": "auto",
                    "xodr_path": str(final_copy),
                    "sha256": _hash_path(final_copy),
                    "generated_from_osm_sha256": _hash_path(generated_xodr),
                    "status": "PASS" if ret == 0 and lane_link_ok else "FAIL",
                    "failure_reason": "",
                }
            )
            if ret != 0:
                summary["failure_reason"] = f"pipeline_exit_{ret}"
                failure_stage = "pipeline_failed"
            elif not lane_link_ok:
                summary["failure_reason"] = "lane_link_targets_failed"
                failure_stage = "quality_gate_failed"

            acceptance = _build_map_acceptance_for_run(
                final_xodr=final_copy,
                run_dir=run_dir,
                lane_link_report=lane_link_report,
                search_dirs=[
                    newest_dir if isinstance(newest_dir, Path) else pipeline_out_dir,
                    pipeline_out_dir,
                    run_dir,
                ],
            )
            summary["map_acceptance_valid"] = acceptance.get("valid_for_experiments")

            probe_result = {"status": "SKIP", "failure_reason": "lane_link_targets_failed"}
            if lane_link_ok and not acceptance.get("valid_for_experiments", False):
                probe_result = {"status": "SKIP", "failure_reason": "map_acceptance_failed"}
                if not summary.get("failure_reason"):
                    summary["failure_reason"] = "map_acceptance_failed"
                    failure_stage = "quality_gate_failed"
            elif lane_link_ok:
                probe_result = _run_carla_probe(
                    final_copy,
                    run_dir / "qa",
                    host=carla_host,
                    port=carla_port,
                    frames=50,
                    dry_run=dry_run,
                )
        else:
            summary = {
                "map_id": map_id,
                "map_type": "auto",
                "xodr_path": "",
                "sha256": "",
                "generated_from_osm_sha256": _hash_path(generated_xodr),
                "status": "FAIL",
                "failure_reason": "no_final_xodr_found_after_pipeline",
            }
            probe_result = {"status": "FAIL", "failure_reason": "no_final_xodr_found_after_pipeline"}
            failure_stage = "no_final_xodr"

        runs.append(
            {
                "tag": run_tag,
                "summary": summary,
                "output_dir": newest_dir or pipeline_out_dir,
                "probe": probe_result,
                "failure_stage": failure_stage,
                "run_dir": run_dir,
            }
        )
        _write_json(run_dir / "structural_summary.json", summary)
        manifest = {
            "git": _read_git_info(REPO_ROOT),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "command": cmd,
            "manual_map": str(manual_map),
            "output_dir": str(pipeline_out_dir),
            "generated_from_osm": str(generated_xodr),
            "tile_qa_allowed_for_thesis": True,
        }
        _apply_stage_hashes(run_dir, manifest)
        _write_json(run_dir / "run_manifest.json", manifest)
        if lane_link_ok:
            _run_osm_stats(osm_path, run_dir, dry_run=dry_run)
            if final_copy.exists():
                _run_carla_smoke_suite(
                    final_copy,
                    run_dir,
                    host=carla_host,
                    port=carla_port,
                    timeout=120.0,
                    dry_run=dry_run,
                )
            _run_artifact_integrity(run_dir, sample=int(artifact_sample or 25), dry_run=dry_run)
    return runs


def run_manual_baseline(
    manual_map: Path,
    auto_run_dir: Optional[Path],
    subdir: Path,
    *,
    carla_host: str,
    carla_port: int,
    artifact_sample: int,
    dry_run: bool,
) -> Dict[str, Any]:
    log_path = subdir / "logs" / "manual_baseline.log"
    env = os.environ.copy()
    env["UP_MANUAL_XODR"] = str(manual_map)
    if auto_run_dir:
        env["UP_AUTO_RUN_DIR"] = str(auto_run_dir)
    env["UP_OUTPUT_DIR"] = str(subdir)
    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.run_full_domain_gap",
        "--manual_xodr",
        str(manual_map),
        "--output_dir",
        str(subdir),
    ]
    ret = _run_subprocess(cmd, log_path, env=env, dry_run=dry_run)
    if not dry_run and ret != 0:
        raise RuntimeError(f"Manual baseline run failed, see {log_path}")
    summary = collect_manual_summary(manual_map)
    if auto_run_dir:
        summary["auto_reference_dir"] = "dry_run" if dry_run else str(auto_run_dir)
    lane_report = _write_lane_link_report(manual_map, subdir / "lane_link_target_report.json")
    postprocess_thesis_artifacts(
        subdir,
        manual_map,
        pipeline_out_dir=None,
        cli_args=sys.argv,
        bbox=INGOLSTADT_BBOX,
        osm_source=str(_resolve_osm_path()),
    )
    acceptance = _build_map_acceptance_for_run(
        final_xodr=manual_map,
        run_dir=subdir,
        lane_link_report=lane_report,
        search_dirs=[subdir],
    )
    summary["map_acceptance_valid"] = acceptance.get("valid_for_experiments")
    if lane_report.get("ok", False) and acceptance.get("valid_for_experiments", False):
        summary["carla_probe"] = _run_carla_probe(
            manual_map,
            subdir / "qa",
            host=carla_host,
            port=carla_port,
            frames=50,
            dry_run=dry_run,
        )
    elif not acceptance.get("valid_for_experiments", False):
        summary["carla_probe"] = {
            "status": "SKIP",
            "failure_reason": "map_acceptance_failed",
            "host": carla_host,
            "port": carla_port,
            "frames": 50,
        }
    else:
        summary["carla_probe"] = {
            "status": "FAIL",
            "failure_reason": "lane_link_targets_failed",
            "host": carla_host,
            "port": carla_port,
            "frames": 50,
        }
    _write_json(subdir / "structural_summary.json", summary)
    manifest = {
        "git": _read_git_info(REPO_ROOT),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "command": cmd,
        "manual_map": str(manual_map),
        "auto_run_dir": str(auto_run_dir) if auto_run_dir else "",
    }
    _apply_stage_hashes(subdir, manifest)
    _write_json(subdir / "run_manifest.json", manifest)
    _run_osm_stats(_resolve_osm_path(), subdir, dry_run=dry_run)
    _run_carla_smoke_suite(
        manual_map,
        subdir,
        host=carla_host,
        port=carla_port,
        timeout=120.0,
        dry_run=dry_run,
    )
    _run_artifact_integrity(subdir, sample=artifact_sample, dry_run=dry_run)
    return summary


def write_summary_tables(
    summary_dir: Path,
    manual_summary: Dict[str, Any],
    auto_runs: List[Dict[str, Any]],
    perception_results: List[Dict[str, Any]],
) -> None:
    determinism = []
    base_hash = None
    for run in auto_runs:
        run_summary = run.get("summary", {})
        if base_hash is None:
            base_hash = run_summary.get("sha256")
        determinism.append(
            {
                "run_tag": run["tag"],
                "xodr_path": run_summary.get("xodr_path", ""),
                "sha256": run_summary.get("sha256", ""),
                "hash_changed_vs_run1": False if base_hash is None else run_summary.get("sha256") != base_hash,
            }
        )
    determinism_data = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "auto_runs": determinism,
        "auto_repeats_status": {},
    }
    status_counts = {
        "success": 0,
        "conversion_missing": 0,
        "pipeline_failed": 0,
        "quality_gate_failed": 0,
        "other_failed": 0,
    }
    for run in auto_runs:
        summary = run.get("summary", {})
        if summary.get("status") == "PASS":
            status_counts["success"] += 1
            continue
        stage = run.get("failure_stage", "")
        if stage == "conversion_missing":
            status_counts["conversion_missing"] += 1
        elif stage == "pipeline_failed":
            status_counts["pipeline_failed"] += 1
        elif stage == "quality_gate_failed":
            status_counts["quality_gate_failed"] += 1
        else:
            status_counts["other_failed"] += 1
    determinism_data["auto_repeats_status"] = status_counts
    _write_json(summary_dir / "determinism_summary.json", determinism_data)

    comparison_rows = [
        {
            "map_id": manual_summary["map_id"],
            "map_type": manual_summary["map_type"],
            "roads": manual_summary.get("roads", 0),
            "junctions": manual_summary.get("junctions", 0),
            "lane_sections": manual_summary.get("lane_sections", 0),
            "sha256": manual_summary.get("sha256", ""),
        }
    ]
    for run in auto_runs:
        row = run.get("summary", {})
        comparison_rows.append(
            {
                "map_id": row.get("map_id", ""),
                "map_type": row.get("map_type", "auto"),
                "roads": row.get("roads", 0),
                "junctions": row.get("junctions", 0),
                "lane_sections": row.get("lane_sections", 0),
                "sha256": row.get("sha256", ""),
            }
        )
    _summary_csv(
        summary_dir / "structural_comparison.csv",
        comparison_rows,
        ["map_id", "map_type", "roads", "junctions", "lane_sections", "sha256"],
    )

    carla_rows = []
    sources = [
        {
            "map_id": manual_summary["map_id"],
            "xodr_path": manual_summary["xodr_path"],
            "probe": manual_summary.get("carla_probe", {}),
        }
    ]
    for run in auto_runs:
        sources.append(
            {
                "map_id": run.get("summary", {}).get("map_id", ""),
                "xodr_path": run.get("summary", {}).get("xodr_path", ""),
                "probe": run.get("probe", {}),
            }
        )
    for src in sources:
        probe = src.get("probe") or {}
        carla_rows.append(
            {
                "map_id": src.get("map_id", ""),
                "xodr_path": src.get("xodr_path", ""),
                "PASS_FAIL": probe.get("status", "FAIL"),
                "failure_reason": probe.get("failure_reason", ""),
                "screenshot_paths": probe.get("screenshot_path", ""),
            }
        )
    _summary_csv(
        summary_dir / "carla_loadability.csv",
        carla_rows,
        ["map_id", "xodr_path", "PASS_FAIL", "failure_reason", "screenshot_paths"],
    )

    proxy_rows: List[Dict[str, Any]] = []
    for res in perception_results:
        proxy_rows.append(
            {
                "map_id": res.get("map_id", ""),
                "frames": res.get("frames_recorded", 0),
                "rgb_brightness_mean": res.get("brightness_mean", 0.0),
                "rgb_brightness_std": res.get("brightness_std", 0.0),
                "laplacian_variance": res.get("laplacian_variance", 0.0),
                "screenshot_paths": ";".join(res.get("screenshot_paths") or []),
                "note": res.get("note")
                or res.get("failure_reason")
                or res.get("status", ""),
            }
        )
    if not proxy_rows:
        proxy_rows.append(
            {
                "map_id": manual_summary["map_id"],
                "frames": 0,
                "rgb_brightness_mean": "",
                "rgb_brightness_std": "",
                "laplacian_variance": "",
                "screenshot_paths": "",
                "note": "perception pending",
            }
        )
    _summary_csv(
        summary_dir / "perception_proxy.csv",
        proxy_rows,
        [
            "map_id",
            "frames",
            "rgb_brightness_mean",
            "rgb_brightness_std",
            "laplacian_variance",
            "screenshot_paths",
            "note",
        ],
    )


def _load_lane_link_report(run_dir: Path) -> Optional[Dict[str, Any]]:
    report_path = run_dir / "lane_link_target_report.json"
    if not report_path.is_file():
        return None
    try:
        return json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _has_valid_auto_perception_candidate(run: Dict[str, Any]) -> bool:
    run_dir = run.get("run_dir")
    if not isinstance(run_dir, Path):
        return False
    if not (run_dir / "structural_summary.json").is_file():
        return False
    report = _load_lane_link_report(run_dir)
    return bool(report and report.get("ok"))


def _select_best_auto_run(auto_runs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    candidates = [run for run in auto_runs if _has_valid_auto_perception_candidate(run)]
    if not candidates:
        return None
    candidates.sort(key=lambda run: run.get("summary", {}).get("map_id", ""))
    return candidates[0]


def _record_auto_perception_skip(
    target_dir: Path,
    frames: int,
    fps: int,
    host: str,
    port: int,
    reason: str,
    map_id: str = "auto_best",
) -> Dict[str, Any]:
    payload = {
        "status": "SKIP",
        "failure_reason": reason,
        "frames_recorded": 0,
        "frames_requested": frames,
        "frames": frames,
        "fps": fps,
        "host": host,
        "port": port,
        "camera": "",
        "image_size": {"width": 0, "height": 0},
        "brightness_mean": 0.0,
        "brightness_std": 0.0,
        "laplacian_variance": 0.0,
        "screenshot_paths": [],
    }
    target_dir.mkdir(parents=True, exist_ok=True)
    _write_json(target_dir / "recording_summary.json", payload)
    return {
        "map_id": map_id,
        "frames": 0,
        "brightness_mean": 0.0,
        "brightness_std": 0.0,
        "laplacian_variance": 0.0,
        "screenshot_paths": [],
        "status": "SKIP",
        "failure_reason": reason,
        "note": reason,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Thesis orchestrator: manual baseline + auto repeats + CARLA QA + perception proxies."
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Explicit base directory for final thesis run (default: ultimate_pipeline_out/thesis_final_runs/<timestamp>_thesis_final)",
    )
    parser.add_argument(
        "--manual-map",
        type=Path,
        default=DEFAULT_MANUAL_MAP,
        help="Manual reference OpenDRIVE used for domain gap",
    )
    parser.add_argument(
        "--manual-town",
        choices=["Grid0828", "Grid0821"],
        default=DEFAULT_MANUAL_TOWN,
        help="Manual Ingolstadt reference selector used for default/fallback map discovery.",
    )
    parser.add_argument(
        "--manual-xodr",
        type=Path,
        help="Explicit manual XODR path (overrides --manual-map).",
    )
    parser.add_argument(
        "--timestamp",
        type=str,
        default=None,
        help="Custom timestamp string used for tagging parent folder",
    )
    parser.add_argument(
        "--auto-repeats",
        type=int,
        default=2,
        help="Number of auto pipeline repeats (max 2 supported for this orchestrator)",
    )
    parser.add_argument(
        "--skip-auto",
        action="store_true",
        help="Skip running the auto pipeline repeats (use existing data)",
    )
    parser.add_argument(
        "--refresh-osm",
        action="store_true",
        help="Force re-download of OSM extract before OSM→XODR conversion (also respects UP_FORCE_OSM_DOWNLOAD/UP_REFRESH_OSM).",
    )

    parser.add_argument(
        "--skip-manual",
        action="store_true",
        help="Skip running the manual baseline (domain gap) step",
    )
    parser.add_argument(
        "--skip-perception",
        action="store_true",
        help="Skip CARLA-based perception QA and proxy recording",
    )
    parser.add_argument(
        "--carla-host",
        default=DEFAULT_CARLA_HOST,
        help="CARLA RPC host",
    )
    parser.add_argument(
        "--carla-port",
        type=int,
        default=DEFAULT_CARLA_PORT,
        help="CARLA RPC port",
    )
    parser.add_argument(
        "--perception-frames",
        type=int,
        default=DEFAULT_RECORD_FRAMES,
        help="Number of frames to capture for perception proxy runs",
    )
    parser.add_argument(
        "--perception-fps",
        type=int,
        default=DEFAULT_RECORD_FPS,
        help="Target FPS for perception recording (synchronous tick rate)",
    )
    parser.add_argument(
        "--enable-quarantine",
        dest="enable_quarantine",
        action="store_true",
        default=True,
        help="Enable post-continuity road quarantine (default: enabled for thesis runs)",
    )
    parser.add_argument(
        "--disable-quarantine",
        dest="enable_quarantine",
        action="store_false",
        help="Disable post-continuity road quarantine",
    )
    parser.add_argument(
        "--quarantine-max-fraction",
        type=float,
        default=0.008,
        help="Max fraction of roads to quarantine",
    )
    parser.add_argument(
        "--quarantine-continuity-dxy",
        type=float,
        default=1.0,
        help="Continuity dxy threshold (meters) for quarantine",
    )
    parser.add_argument(
        "--quarantine-continuity-dhdg",
        type=float,
        default=10.0,
        help="Continuity heading threshold (deg) for quarantine",
    )
    parser.add_argument(
        "--quarantine-heading-jump-deg",
        type=float,
        default=30.0,
        help="Heading jump threshold (deg) for quarantine",
    )
    parser.add_argument(
        "--quarantine-curvature-abs",
        type=float,
        default=0.5,
        help="Absolute curvature threshold for quarantine",
    )
    parser.add_argument(
        "--quarantine-curvature-jump",
        type=float,
        default=0.5,
        help="Curvature jump threshold for quarantine",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolved commands/paths without executing.",
    )
    parser.add_argument(
        "--system-metrics",
        action="store_true",
        help="Log CPU/RAM metrics to artifacts/system_metrics.csv",
    )
    parser.add_argument(
        "--artifact-sample",
        type=int,
        default=DEFAULT_ARTIFACT_SAMPLE,
        help="Sample size for artifact integrity checks",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    os.environ["UP_ENABLE_ROAD_QUARANTINE"] = "1" if args.enable_quarantine else "0"
    os.environ["UP_QUARANTINE_MAX_FRACTION"] = str(args.quarantine_max_fraction)
    os.environ["UP_QUARANTINE_CONTINUITY_DXY"] = str(args.quarantine_continuity_dxy)
    os.environ["UP_QUARANTINE_CONTINUITY_DHDG"] = str(args.quarantine_continuity_dhdg)
    os.environ["UP_QUARANTINE_HEADING_JUMP_DEG"] = str(args.quarantine_heading_jump_deg)
    os.environ["UP_QUARANTINE_CURVATURE_ABS"] = str(args.quarantine_curvature_abs)
    os.environ["UP_QUARANTINE_CURVATURE_JUMP"] = str(args.quarantine_curvature_jump)
    timestamp = args.timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    base_out = (
        args.out_dir.expanduser()
        if args.out_dir
        else OUTPUT_ROOT / "thesis_final_runs" / f"{timestamp}_thesis_final"
    )
    subdirs = _ensure_dirs(base_out)
    manual_arg = args.manual_xodr or args.manual_map
    manual_map = manual_arg.expanduser()
    manual_town = str(args.manual_town or DEFAULT_MANUAL_TOWN).strip() or DEFAULT_MANUAL_TOWN
    if not manual_map.is_absolute():
        manual_map = (REPO_ROOT / manual_map).resolve()
    else:
        manual_map = manual_map.resolve()

    if not manual_map.is_file():
        try:
            town_ref = resolve_manual_town(manual_town)
            resolved_manual = Path(str(town_ref.get("manual_xodr_path", ""))).expanduser().resolve()
            if resolved_manual.is_file():
                manual_map = resolved_manual
        except Exception:
            pass
    if not manual_map.is_file():
        fallback, sample = _find_default_manual_map(manual_town)
        if fallback and fallback.is_file():
            manual_map = fallback.resolve()
        else:
            sample_note = f" | resolver/manual_maps hints: {sample}" if sample else ""
            raise FileNotFoundError(
                f"Manual map not found for manual-town={manual_town} at {manual_map}{sample_note}"
            )

    base_manifest = {
        "git": _read_git_info(REPO_ROOT),
        "python": sys.executable,
        "manual_map": str(manual_map),
        "manual_town": manual_town,
        "osm_path": str(_resolve_osm_path()),
        "bbox": INGOLSTADT_BBOX,
        "timestamp": timestamp,
        "auto_repeats_requested": args.auto_repeats,
        "skip_auto": args.skip_auto,
        "skip_manual": args.skip_manual,
        "carla_host": args.carla_host,
        "carla_port": args.carla_port,
        "perception_frames": args.perception_frames,
        "perception_fps": args.perception_fps,
        "skip_perception": args.skip_perception,
        "dry_run": args.dry_run,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }
    env_manifest = dict(base_manifest)
    _apply_stage_hashes(subdirs["00_env"], env_manifest)
    _write_json(subdirs["00_env"] / "run_manifest.json", env_manifest)

    monitor_ctx = start_system_metrics_monitor(base_out / "artifacts") if args.system_metrics else None
    if monitor_ctx:
        monitor_ctx.__enter__()
    try:
        auto_runs: List[Dict[str, Any]] = []
        if not args.skip_auto:
            auto_runs = run_auto_repeats(
                manual_map,
                subdirs,
                timestamp,
                repeats=min(args.auto_repeats, MAX_AUTO_REPEATS),
                carla_host=args.carla_host,
                carla_port=args.carla_port,
                artifact_sample=args.artifact_sample,
                refresh_osm=args.refresh_osm,
                dry_run=args.dry_run,
            )
        else:
            print("Skipping auto pipeline repeats (per --skip-auto).")

        manual_summary = collect_manual_summary(manual_map)
        if auto_runs and not args.skip_manual:
            auto_first_dir = auto_runs[0].get("output_dir")
            manual_summary = run_manual_baseline(
                manual_map,
                auto_first_dir if isinstance(auto_first_dir, Path) else auto_first_dir,
                subdirs["01_manual_baseline"],
                carla_host=args.carla_host,
                carla_port=args.carla_port,
                artifact_sample=args.artifact_sample,
                dry_run=args.dry_run,
            )
        else:
            if args.skip_manual:
                print("Manual baseline step skipped (--skip-manual).")
            elif not auto_runs:
                print("No auto runs available; manual baseline will skip domain gap invocation.")
            manual_manifest = dict(base_manifest)
            _apply_stage_hashes(subdirs["01_manual_baseline"], manual_manifest)
            _write_json(subdirs["01_manual_baseline"] / "run_manifest.json", manual_manifest)
            _write_json(subdirs["01_manual_baseline"] / "structural_summary.json", manual_summary)
            _run_osm_stats(_resolve_osm_path(), subdirs["01_manual_baseline"], dry_run=args.dry_run)
            _run_artifact_integrity(subdirs["01_manual_baseline"], sample=args.artifact_sample, dry_run=args.dry_run)

        perception_results: List[Dict[str, Any]] = []
        if not args.skip_perception:
            manual_lane_report = _write_lane_link_report(
                manual_map, subdirs["06_perception_manual"] / "lane_link_target_report.json"
            )
            manual_acceptance = _build_map_acceptance_for_run(
                final_xodr=manual_map,
                run_dir=subdirs["06_perception_manual"],
                lane_link_report=manual_lane_report,
                search_dirs=[subdirs["01_manual_baseline"], subdirs["06_perception_manual"]],
            )
            if manual_lane_report.get("ok", False) and manual_acceptance.get("valid_for_experiments", False):
                manual_perf = _run_capture_rgb(
                    manual_map,
                    DEFAULT_CALIB,
                    subdirs["06_perception_manual"],
                    host=args.carla_host,
                    port=args.carla_port,
                    frames=args.perception_frames,
                    fps=args.perception_fps,
                    dry_run=args.dry_run,
                )
            elif not manual_acceptance.get("valid_for_experiments", False):
                manual_perf = {
                    "status": "SKIP",
                    "failure_reason": "map_acceptance_failed",
                    "host": args.carla_host,
                    "port": args.carla_port,
                    "frames": args.perception_frames,
                    "fps": args.perception_fps,
                }
            else:
                manual_perf = {
                    "status": "FAIL",
                    "failure_reason": "lane_link_targets_failed",
                    "host": args.carla_host,
                    "port": args.carla_port,
                    "frames": args.perception_frames,
                    "fps": args.perception_fps,
                }
            manual_perf["map_id"] = manual_summary["map_id"]
            perception_results.append(manual_perf)

            best_auto = _select_best_auto_run(auto_runs)
            auto_summary = best_auto.get("summary", {}) if best_auto else {}
            auto_xodr_path = auto_summary.get("xodr_path", "")
            if best_auto and auto_xodr_path:
                selected_map_id = auto_summary.get("map_id", "")
                print(f"selected_map_id={selected_map_id}")
                auto_xodr = Path(auto_xodr_path)
                auto_lane_report = _write_lane_link_report(
                    auto_xodr, subdirs["07_perception_auto_best"] / "lane_link_target_report.json"
                )
                auto_search_dirs = [subdirs["07_perception_auto_best"]]
                auto_run_dir = best_auto.get("run_dir")
                if isinstance(auto_run_dir, Path):
                    auto_search_dirs.append(auto_run_dir)
                    auto_search_dirs.append(auto_run_dir / "pipeline_out")
                auto_acceptance = _build_map_acceptance_for_run(
                    final_xodr=auto_xodr,
                    run_dir=subdirs["07_perception_auto_best"],
                    lane_link_report=auto_lane_report,
                    search_dirs=auto_search_dirs,
                )
                if auto_lane_report.get("ok", False) and auto_acceptance.get("valid_for_experiments", False):
                    auto_perf = _run_capture_rgb(
                        auto_xodr,
                        DEFAULT_CALIB,
                        subdirs["07_perception_auto_best"],
                        host=args.carla_host,
                        port=args.carla_port,
                        frames=args.perception_frames,
                        fps=args.perception_fps,
                        dry_run=args.dry_run,
                    )
                elif not auto_acceptance.get("valid_for_experiments", False):
                    auto_perf = {
                        "status": "SKIP",
                        "failure_reason": "map_acceptance_failed",
                        "host": args.carla_host,
                        "port": args.carla_port,
                        "frames": args.perception_frames,
                        "fps": args.perception_fps,
                    }
                else:
                    auto_perf = {
                        "status": "FAIL",
                        "failure_reason": "lane_link_targets_failed",
                        "host": args.carla_host,
                        "port": args.carla_port,
                        "frames": args.perception_frames,
                        "fps": args.perception_fps,
                    }
                auto_perf["map_id"] = selected_map_id
                perception_results.append(auto_perf)
            else:
                skip_reason = AUTO_PERCEPTION_SKIP_REASON
                print(f"skipped_auto_perception_reason={skip_reason}")
                skip_entry = _record_auto_perception_skip(
                    subdirs["07_perception_auto_best"],
                    frames=args.perception_frames,
                    fps=args.perception_fps,
                    host=args.carla_host,
                    port=args.carla_port,
                    reason=skip_reason,
                )
                perception_results.append(skip_entry)
        else:
            print("Skipping CARLA perception QA (--skip-perception).")

        summary_dir = subdirs["08_summary_tables"]
        cfg = OSMToXODRConfig(
            carla_root=os.getenv("CARLA_ROOT") or os.getenv("CARLA_HOME"),
            tool_path=getattr(SETTINGS, "OSM_TO_XODR_TOOL", None),
            overwrite=True,
        )
        _run_osm_determinism(_resolve_osm_path(), summary_dir, cfg, dry_run=args.dry_run)
        write_summary_tables(summary_dir, manual_summary, auto_runs, perception_results)

        print(f"\nThesis experiment scaffolding ready at {base_out}")
        print(" - Auto repeats:", len(auto_runs))
        print(" - Manual baseline:", "executed" if auto_runs and not args.skip_manual else "pending/manual-only")
        print(" - Perception runs:", len(perception_results))
        print(" - Summary tables generated in", summary_dir)
        return 0
    finally:
        if monitor_ctx:
            monitor_ctx.__exit__(None, None, None)


if __name__ == "__main__":
    raise SystemExit(main())

