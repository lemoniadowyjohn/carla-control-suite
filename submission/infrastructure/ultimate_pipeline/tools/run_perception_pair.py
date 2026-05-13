#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
Two-arm perception experiment runner.

Orchestrates paired recording sessions on:
  A) Manual map (Grid0821 or Grid0828 via --town)
  B) Auto-generated map (08_final*.xodr via --xodr-in, hardened then loaded as OpenDriveMap)

Produces deterministic, comparable datasets for thesis domain-gap analysis.

Subprocess-based orchestration: calls run_perception_safe.py for each arm to avoid
import-time CARLA usage in the pair orchestrator.

Optional CRS comparability gate:
  - If env UP_MANUAL_XODR is set to a valid file path, compare args.xodr_in (auto)
    against UP_MANUAL_XODR (manual) using ultimate_pipeline.tools.xodr_compare_gate.
  - Writes xodr_compare_report.json into the pair output directory.
  - If --strict and not comparable: abort run with RuntimeError.
  - If not strict: warn and continue.

Example:
  python -m ultimate_pipeline.tools.run_perception_pair \
    --manual-town Grid0821 \
    --xodr-in ultimate_pipeline_out/run_001/08_final_tile_001.xodr \
    --calib calib_data.json \
    --out-root recordings/pairs

  # With manual XODR comparability check:
  set UP_MANUAL_XODR=path\to\manual_reference.xodr
  python -m ultimate_pipeline.tools.run_perception_pair ...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

from ultimate_pipeline.config.thesis_contract import (
    classify_pair_perception_result,
    classify_single_perception_result,
)
from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors
def _configure_windows_encoding() -> None:
    """Best-effort UTF-8 encoding for Windows stdout/stderr to prevent mojibake."""
    if sys.platform != "win32":
        return
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass  # silently ignore on older Python or restricted environments

from ultimate_pipeline.core.carla_preflight import carla_preflight, classify_carla_crash, write_crash_report
from ultimate_pipeline.core.return_codes import PerceptionReturnCode
from ultimate_pipeline.optional.carla_api import get_carla
from ultimate_pipeline.tools import xodr_compare_gate
from ultimate_pipeline.carla_tools.carla_readiness import wait_for_carla_ready_bounded
from ultimate_pipeline.perception.perception_metrics import compute_perception_metrics

# Schema version for pair_manifest.json
# v3: Added experiment_mode, profile, policy_decisions, explicit low_mem_enabled
MANIFEST_SCHEMA_VERSION = 3

# Hardware profile names (machine-parseable)
PROFILE_RESEARCH = "research"      # HPC / workstation (>=12GB VRAM)
PROFILE_GAMING = "gaming"          # Gaming GPU (8-12GB VRAM)
PROFILE_LAPTOP = "laptop"          # Laptop / integrated (4-8GB VRAM)
PROFILE_LOW_END = "low_end"        # Low-end / OOM-prone (<4GB VRAM)
PROFILE_AUTO = "auto"              # Auto-detect (default)

# Arm status codes (machine-parseable)
STATUS_SUCCESS = "SUCCESS"
STATUS_CARLA_NOT_REACHABLE = "CARLA_NOT_REACHABLE"
STATUS_CARLA_CRASHED = "CARLA_CRASHED_DURING_LOAD_OR_RECORD"
STATUS_STRICT_MAP_IDENTITY_FAIL = "STRICT_MAP_IDENTITY_FAIL"
STATUS_SAFE_RUNNER_FAILED = "SAFE_RUNNER_FAILED"
STATUS_RECORD_ROUTE_FAILED = STATUS_SAFE_RUNNER_FAILED  # backward-compat alias
STATUS_SAFE_RUNNER_MAP_LOAD_RISK = "SAFE_RUNNER_MAP_LOAD_RISK"
STATUS_PREFLIGHT_FAILED = "CARLA_PREFLIGHT_FAILED"
STATUS_SAFE_RUNNER_EXIT_PREFIX = "SAFE_RUNNER_EXIT_"

# Max lines for stderr tail (deterministic truncation)
STDERR_TAIL_LINES = 60

_WARN_ONCE: set[str] = set()


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on", "y")


def _warn_once(message: str) -> None:
    if message in _WARN_ONCE:
        return
    _WARN_ONCE.add(message)
    print(f"[WARNING] {message}")


def _normalize_path(path: str) -> str:
    """Normalize path to forward slashes for consistent JSON output."""
    return path.replace("\\", "/")


def _flag_was_passed(flag: str) -> bool:
    """Check if the exact flag (or flag=value) was provided."""
    argv = sys.argv[1:]
    return any(arg == flag or arg.startswith(flag + "=") for arg in argv)


def _format_vram_text(vram: Optional[float]) -> str:
    if vram is None:
        return "VRAM unknown (hybrid GPU or detection unavailable)"
    from decimal import Decimal, ROUND_HALF_UP

    quantized = Decimal(str(vram)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{quantized}GB"


def _smoke_checklist_hint() -> str:
    return (
        "Smoke checklist: run `powershell -c \"Get-ChildItem -Filter calib_data.json -Recurse\"` "
        "and avoid placeholder paths like '...'."
    )


def _validate_file_exists(path: str, label: str, *, recommended_path: str = "") -> None:
    if not os.path.isfile(path):
        msg = f"{label} not found: {path!r}. {_smoke_checklist_hint()}"
        if recommended_path:
            msg += f"\n  Recommended path: {recommended_path}"
        raise FileNotFoundError(msg)


def _validate_exe_path(path: str, label: str) -> None:
    """Validate executable path: must exist and not contain placeholders."""
    if "..." in path:
        raise ValueError(f"{label} contains placeholder '...': {path!r}")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{label} not found: {path!r}")


_KNOWN_MANUAL_TOWNS = {"Grid0821", "Grid0828"}


def _validate_manual_town(town: str) -> None:
    if not str(town or "").strip():
        raise ValueError("--manual-town must be a non-empty town name")
    if str(town).strip() not in _KNOWN_MANUAL_TOWNS:
        raise ValueError(
            f"Unknown --manual-town '{town}'. "
            f"Known towns: Grid0821, Grid0828"
        )


def _truncate_stderr(stderr: str, max_lines: int = STDERR_TAIL_LINES) -> str:
    """Truncate stderr to last N lines, deterministically."""
    if not stderr:
        return ""
    lines = stderr.strip().split("\n")
    if len(lines) <= max_lines:
        return stderr.strip()
    truncated = lines[-max_lines:]
    return f"[...truncated {len(lines) - max_lines} lines...]\n" + "\n".join(truncated)


def _truncate_stdout(stdout: str, max_lines: int = STDERR_TAIL_LINES) -> str:
    """Truncate stdout to last N lines, deterministically (parallel to stderr)."""
    if not stdout:
        return ""
    lines = stdout.strip().split("\n")
    if len(lines) <= max_lines:
        return stdout.strip()
    truncated = lines[-max_lines:]
    return f"[...truncated {len(lines) - max_lines} lines...]\n" + "\n".join(truncated)


def _write_json_deterministic(path: str, payload: Dict[str, Any]) -> None:
    """Deterministic JSON writer: sort keys, stable indent, ASCII-only, newline-terminated."""
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)
    if not text.endswith("\n"):
        text += "\n"
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _hash_file(path: str, algorithm: str = "sha256") -> Optional[str]:
    try:
        h = hashlib.new(algorithm)
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _git_commit_hash() -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3.0,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _get_carla_version() -> Optional[str]:
    try:
        carla = get_carla()
    except Exception:
        return None
    try:
        return getattr(carla, "__version__", None) or getattr(carla, "VERSION", None)
    except Exception:
        return None


def _write_protocol_snapshot(
    out_dir: str,
    args: argparse.Namespace,
    *,
    calib_hash: Optional[str],
    hw_detection: Dict[str, Any],
    policy: Dict[str, Any],
    seeds: Dict[str, Any],
) -> str:
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_commit": _git_commit_hash(),
        "python": {
            "version": sys.version,
            "executable": sys.executable,
        },
        "carla": {
            "pythonapi_version": _get_carla_version(),
        },
        "calib": {
            "path": _normalize_path(str(Path(args.calib).resolve())),
            "sha256": calib_hash,
        },
        "cli_args": list(sys.argv[1:]),
        "flags": vars(args),
        "system": {
            "platform": platform.platform(),
            "os": platform.system(),
            "node": platform.node(),
            "gpu_name": hw_detection.get("gpu_name"),
        },
        "seeds": seeds,
        "policy": policy,
    }
    out_path = os.path.join(out_dir, "protocol_snapshot.json")
    _write_json_deterministic(out_path, payload)
    return out_path


def _build_config_dict(
    args: argparse.Namespace,
    effective_low_mem: bool,
    xodr_hash: Optional[str],
    hash_algo: str,
) -> Dict[str, Any]:
    auto_xodr_basename = (
        _normalize_path(os.path.basename(args.xodr_in)) if args.xodr_in else ""
    )
    auto_xodr_full = (
        _normalize_path(str(Path(args.xodr_in).resolve())) if args.xodr_in else ""
    )
    return {
        "manual_town": args.manual_town,
        "auto_town": str(args.town or ""),
        "xodr_in": auto_xodr_basename,
        "xodr_in_full": auto_xodr_full,
        "spawn_index": args.spawn_index,
        "fps": args.fps,
        "duration": args.duration,
        "seed": args.seed,
        "strict": args.strict,
        "low_mem_explicit": args.low_mem,
        "low_mem_enabled": effective_low_mem,
        "vehicle": args.vehicle,
        "weather": args.weather,
        "seg": bool(args.seg),
        "seg_converter": str(args.seg_converter),
        "repair_parampoly3_to_line": args.repair_parampoly3_to_line,
        "host": args.host,
        "port": args.port,
        "autostart_windowed": args.autostart_windowed,
        "autostart_res_x": args.autostart_res_x,
        "autostart_res_y": args.autostart_res_y,
        "experiment_standard": args.experiment_standard,
        "max_performance": args.max_performance,
        "profile_requested": args.profile,
        "carla_wait": args.carla_wait,
        "carla_probe_timeout": args.carla_probe_timeout,
        "autostart_carla_exe": args.autostart_carla_exe,
        "xodr_hash": xodr_hash,
        "xodr_hash_algo": hash_algo if xodr_hash else None,
        "out": args.out,
        "out_root": args.out_root,
        "spawn_enrichments": args.spawn_enrichments,
        "spawn_enrichments_limit": args.spawn_enrichments_limit,
        "spawn_enrichments_seed": args.spawn_enrichments_seed,
        "spawn_enrichments_filter": args.spawn_enrichments_filter,
        "qa_capture": args.qa_capture,
        "no_carla": args.no_carla,
    }


def _build_manifest_payload(
    *,
    pair_name: str,
    timestamp: str,
    config: Dict[str, Any],
    hardware_detection: Dict[str, Any],
    policy: Dict[str, Any],
    preflight: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "pair_name": pair_name,
        "timestamp": timestamp,
        "config": config,
        "hardware_detection": hardware_detection,
        "policy_decisions": policy,
        "carla_preflight": preflight,
        "carla_preflight_after_autostart": None,
        "carla_status_initial": {},
        "success": False,
        "arms": {},
    }


def _write_pair_manifest(pair_dir: str, results: Dict[str, Any]) -> str:
    manifest_path = os.path.join(pair_dir, "pair_manifest.json")
    _write_json_deterministic(manifest_path, results)
    return manifest_path


def _write_run_status(out_dir: str, payload: Dict[str, Any]) -> str:
    status_path = os.path.join(out_dir, "run_status.json")
    _write_json_deterministic(status_path, payload)
    return status_path


def _ensure_arm_audit_files(arm_dir: str, *, arm_label: str) -> Dict[str, str]:
    """
    Ensure key per-arm artifacts exist even if the subprocess never runs.

    Returns dict of normalized relative paths (within pair dir).
    """
    os.makedirs(arm_dir, exist_ok=True)
    stdout_path = os.path.join(arm_dir, "record_route_stdout.txt")
    stderr_path = os.path.join(arm_dir, "record_route_stderr.txt")
    sensor_report_path = os.path.join(arm_dir, "sensor_spawn_report.json")
    run_status_path = os.path.join(arm_dir, "run_status.json")

    if not os.path.exists(stdout_path):
        Path(stdout_path).write_text("", encoding="utf-8", errors="replace")
    if not os.path.exists(stderr_path):
        Path(stderr_path).write_text("", encoding="utf-8", errors="replace")
    if not os.path.exists(sensor_report_path):
        _write_json_deterministic(
            sensor_report_path,
            {
                "schema_version": 1,
                "arm": arm_label,
                "status": "not_run",
                "sensors": [],
                "summary": {"attempted": 0, "spawned": 0, "missing": []},
            },
        )
    if not os.path.exists(run_status_path):
        _write_run_status(
            arm_dir,
            {
                "arm": arm_label,
                "stage": "init",
                "success": False,
                "exit_code": None,
                "error": None,
            },
        )

    return {
        "stdout_path": _normalize_path(stdout_path),
        "stderr_path": _normalize_path(stderr_path),
        "sensor_spawn_report": _normalize_path(sensor_report_path),
        "run_status_path": _normalize_path(run_status_path),
    }


def _write_perception_status(pair_dir: str, results: Dict[str, Any]) -> str:
    """Write a focused perception_status.json artifact for thesis artifact completeness."""
    status_path = os.path.join(pair_dir, "perception_status.json")
    arms = results.get("arms", {})
    arm_a = arms.get("A_manual", {})
    arm_b = arms.get("B_auto", {})

    def _read_arm_perception_status(arm_payload: Dict[str, Any]) -> Dict[str, Any]:
        sensors_dir = str(arm_payload.get("sensors_dir", "") or "").strip()
        if not sensors_dir:
            return {}
        path = os.path.join(sensors_dir, "perception_status.json")
        if not os.path.isfile(path):
            return {}
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    arm_a_status = _read_arm_perception_status(arm_a)
    arm_b_status = _read_arm_perception_status(arm_b)
    arm_a_class = classify_single_perception_result(
        success=arm_a.get("success", False),
        frames_recorded=arm_a_status.get("frames_recorded", 0),
        failure_reason=arm_a_status.get("failure_reason") or arm_a.get("status"),
        manual_town=results.get("config", {}).get("manual_town"),
        expected_map_name=results.get("config", {}).get("manual_town"),
        xodr_in="",
        first_frame_received=arm_a_status.get("first_measurement_ok"),
        evidence_written=arm_a_status.get("evidence_pack_ok"),
        sensors_attached=arm_a_status.get("sensors_attached"),
    )
    arm_b_class = classify_single_perception_result(
        success=arm_b.get("success", False),
        frames_recorded=arm_b_status.get("frames_recorded", 0),
        failure_reason=arm_b_status.get("failure_reason") or arm_b.get("status"),
        manual_town=results.get("config", {}).get("manual_town"),
        auto_town=results.get("config", {}).get("auto_town"),
        expected_map_name=results.get("config", {}).get("auto_town"),
        xodr_in=results.get("config", {}).get("xodr_in_full"),
        first_frame_received=arm_b_status.get("first_measurement_ok"),
        evidence_written=arm_b_status.get("evidence_pack_ok"),
        sensors_attached=arm_b_status.get("sensors_attached"),
    )
    pair_class = classify_pair_perception_result(
        manual_town=results.get("config", {}).get("manual_town"),
        auto_town=results.get("config", {}).get("auto_town"),
        xodr_in=results.get("config", {}).get("xodr_in_full"),
        manual_success=arm_a.get("success", False),
        auto_success=arm_b.get("success", False),
        manual_frames_recorded=arm_a_status.get("frames_recorded", 0),
        auto_frames_recorded=arm_b_status.get("frames_recorded", 0),
    )
    status_payload = {
        "status": "ran" if results.get("success") else "fail",
        "reason": results.get("failure_reason", ""),
        "timestamp": results.get("timestamp", ""),
        "result_class": pair_class.value,
        "result_class_reason": pair_class.reason,
        "arms": {
            "A_manual": {
                "status": arm_a.get("status", "unknown"),
                "success": arm_a.get("success", False),
                "result_class": arm_a_class.value,
                "result_class_reason": arm_a_class.reason,
                "frames_recorded": arm_a_status.get("frames_recorded", 0),
            },
            "B_auto": {
                "status": arm_b.get("status", "unknown"),
                "success": arm_b.get("success", False),
                "result_class": arm_b_class.value,
                "result_class_reason": arm_b_class.reason,
                "frames_recorded": arm_b_status.get("frames_recorded", 0),
            },
        },
        "return_code": results.get("return_code", ""),
        "manifest_path": _normalize_path(os.path.join(pair_dir, "pair_manifest.json")),
    }
    _write_json_deterministic(status_path, status_payload)
    return status_path


def _write_run_manifest(arm_dir: str, payload: Dict[str, Any]) -> str:
    manifest_path = os.path.join(arm_dir, "run_manifest.json")
    _write_json_deterministic(manifest_path, payload)
    return manifest_path


def _write_determinism_links(pair_dir: str, manual_dir: str, auto_dir: str) -> str:
    links = {
        "manual": None,
        "auto": None,
    }
    manual_path = os.path.join(manual_dir, "determinism_fingerprint.json")
    auto_path = os.path.join(auto_dir, "determinism_fingerprint.json")
    if os.path.isfile(manual_path):
        links["manual"] = _normalize_path(manual_path)
    if os.path.isfile(auto_path):
        links["auto"] = _normalize_path(auto_path)
    out_path = os.path.join(pair_dir, "determinism_links.json")
    _write_json_deterministic(out_path, links)
    return out_path


def _frames_from_duration(duration_s: int, fps: int) -> int:
    safe_duration = max(1, int(duration_s))
    safe_fps = max(1, int(fps))
    return max(1, int(round(float(safe_duration) * float(safe_fps))))


def _collect_unmapped_pair_flags(
    *,
    spawn_index: int,
    seed: int,
    vehicle: str,
    weather: str,
    repair_parampoly3_to_line: bool,
    seg: bool,
    seg_converter: str,
) -> Dict[str, Any]:
    unmapped: Dict[str, Any] = {}
    if int(spawn_index) != 0:
        unmapped["spawn_index"] = {
            "value": int(spawn_index),
            "reason": "run_perception_safe has no --spawn-index flag",
        }
    if str(vehicle).strip() and str(vehicle).strip() != "vehicle.audi.a2":
        unmapped["vehicle"] = {
            "value": str(vehicle),
            "reason": "run_perception_safe has no --vehicle flag",
        }
    if bool(repair_parampoly3_to_line):
        unmapped["repair_parampoly3_to_line"] = {
            "value": True,
            "reason": "run_perception_safe has no --repair-parampoly3-to-line flag",
        }
    if str(seg_converter).strip() != "cityscapes":
        unmapped["seg_converter"] = {
            "value": str(seg_converter),
            "reason": "run_perception_safe has no --seg/--seg-converter flags",
        }
    return unmapped


def _build_safe_runner_env_overrides(*, seed: int, weather: str, seg: bool) -> Dict[str, str]:
    env_overrides: Dict[str, str] = {
        "UP_TM_SEED": str(int(seed)),
        "UP_ENABLE_SEMSEG": "1" if bool(seg) else "0",
    }
    weather_value = str(weather or "").strip()
    if weather_value:
        env_overrides["UP_WEATHER_PRESET"] = weather_value
    return env_overrides


def _build_safe_runner_command(
    *,
    manual_town: str,
    out_dir: str,
    calib: str,
    fps: int,
    duration_s: int,
    host: str,
    port: int,
    low_mem: bool,
    map_town: Optional[str],
    map_xodr: Optional[str],
    spawn_enrichments_path: str,
    spawn_enrichments_limit: int,
    spawn_enrichments_seed: int,
    spawn_enrichments_filter: str,
    qa_capture_after_enrichment: bool,
    seg: bool,
) -> List[str]:
    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.run_perception_safe",
        "--manual-town",
        str(manual_town),
        "--out",
        str(out_dir),
        "--calib",
        str(calib),
        "--frames",
        str(_frames_from_duration(duration_s, fps)),
        "--fps",
        str(int(fps)),
        "--host",
        str(host),
        "--port",
        str(int(port)),
        "--fail-nonzero",
    ]
    if map_town:
        cmd.extend(["--town", str(map_town)])
    elif map_xodr:
        cmd.extend(["--xodr-in", str(map_xodr)])
    else:
        raise ValueError("Either map_town or map_xodr must be provided")

    if bool(low_mem):
        cmd.append("--lowres")

    if str(spawn_enrichments_path or "").strip():
        cmd.append("--spawn-enrichments")
        cmd.extend(["--enrichments-json", str(spawn_enrichments_path)])
        cmd.extend(["--spawn-enrichments-limit", str(int(spawn_enrichments_limit))])
        cmd.extend(["--spawn-enrichments-seed", str(int(spawn_enrichments_seed))])
        if str(spawn_enrichments_filter or "").strip():
            cmd.extend(
                ["--spawn-enrichments-filter", str(spawn_enrichments_filter).strip()]
            )

    if bool(qa_capture_after_enrichment):
        cmd.append("--qa-capture-after-enrichment")

    if not bool(seg):
        cmd.append("--no-seg")

    return cmd


def _build_manual_arm_safe_command(
    *,
    manual_town: str,
    out_dir: str,
    calib: str,
    fps: int,
    duration_s: int,
    host: str,
    port: int,
    low_mem: bool,
    spawn_enrichments_path: str,
    spawn_enrichments_limit: int,
    spawn_enrichments_seed: int,
    spawn_enrichments_filter: str,
    qa_capture_after_enrichment: bool,
    seg: bool,
) -> List[str]:
    return _build_safe_runner_command(
        manual_town=manual_town,
        out_dir=out_dir,
        calib=calib,
        fps=fps,
        duration_s=duration_s,
        host=host,
        port=port,
        low_mem=low_mem,
        map_town=manual_town,
        map_xodr=None,
        spawn_enrichments_path=spawn_enrichments_path,
        spawn_enrichments_limit=spawn_enrichments_limit,
        spawn_enrichments_seed=spawn_enrichments_seed,
        spawn_enrichments_filter=spawn_enrichments_filter,
        qa_capture_after_enrichment=qa_capture_after_enrichment,
        seg=seg,
    )


def _build_auto_arm_safe_command(
    *,
    manual_town: str,
    auto_town: Optional[str],
    auto_xodr: Optional[str],
    out_dir: str,
    calib: str,
    fps: int,
    duration_s: int,
    host: str,
    port: int,
    low_mem: bool,
    spawn_enrichments_path: str,
    spawn_enrichments_limit: int,
    spawn_enrichments_seed: int,
    spawn_enrichments_filter: str,
    qa_capture_after_enrichment: bool,
    seg: bool,
) -> List[str]:
    return _build_safe_runner_command(
        manual_town=manual_town,
        out_dir=out_dir,
        calib=calib,
        fps=fps,
        duration_s=duration_s,
        host=host,
        port=port,
        low_mem=low_mem,
        map_town=auto_town,
        map_xodr=auto_xodr,
        spawn_enrichments_path=spawn_enrichments_path,
        spawn_enrichments_limit=spawn_enrichments_limit,
        spawn_enrichments_seed=spawn_enrichments_seed,
        spawn_enrichments_filter=spawn_enrichments_filter,
        qa_capture_after_enrichment=qa_capture_after_enrichment,
        seg=seg,
    )


def _compute_pair_metrics_diff(manual: Dict[str, Any], auto: Dict[str, Any]) -> Dict[str, Any]:
    def _safe_mean(values: List[float]) -> Optional[float]:
        if not values:
            return None
        return float(sum(values) / len(values))

    manual_cam_counts = manual.get("camera", {}).get("total_frames")
    auto_cam_counts = auto.get("camera", {}).get("total_frames")

    manual_intensities = list((manual.get("camera", {}).get("mean_intensity") or {}).values())
    auto_intensities = list((auto.get("camera", {}).get("mean_intensity") or {}).values())
    manual_intensity_mean = _safe_mean([v for v in manual_intensities if isinstance(v, (int, float))])
    auto_intensity_mean = _safe_mean([v for v in auto_intensities if isinstance(v, (int, float))])

    manual_lidar_median = manual.get("lidar", {}).get("point_counts", {}).get("median")
    auto_lidar_median = auto.get("lidar", {}).get("point_counts", {}).get("median")

    return {
        "delta_frame_counts": (
            auto_cam_counts - manual_cam_counts
            if isinstance(auto_cam_counts, int) and isinstance(manual_cam_counts, int)
            else None
        ),
        "delta_mean_intensity": (
            auto_intensity_mean - manual_intensity_mean
            if isinstance(auto_intensity_mean, (int, float)) and isinstance(manual_intensity_mean, (int, float))
            else None
        ),
        "delta_lidar_point_count_median": (
            auto_lidar_median - manual_lidar_median
            if isinstance(auto_lidar_median, (int, float)) and isinstance(manual_lidar_median, (int, float))
            else None
        ),
    }
def _maybe_run_xodr_compare_gate(
    *,
    auto_xodr_path: str,
    pair_dir: str,
    strict: bool,
    results: Dict[str, Any],
) -> None:
    """
    Optional CRS comparability gate.
    Uses env UP_MANUAL_XODR as manual reference XODR path.

    Writes xodr_compare_report.json into pair_dir, records in results.
    In strict mode: abort if not comparable.
    In non-strict: warn and continue.
    """
    manual_xodr = os.environ.get("UP_MANUAL_XODR", "").strip()
    if not manual_xodr:
        return

    report_path = os.path.join(pair_dir, "xodr_compare_report.json")

    if not os.path.isfile(manual_xodr):
        # Do not hard-fail: env var may be set accidentally.
        print(f"[WARNING] UP_MANUAL_XODR is set but file not found: {manual_xodr!r}")
        results["xodr_compare"] = {
            "comparable": False,
            "reason": f"missing_file: manual:{manual_xodr}",
        }
        results["xodr_compare_report"] = _normalize_path(os.path.basename(report_path))
        results["xodr_compare_report_full"] = _normalize_path(str(Path(report_path).resolve()))
        _write_json_deterministic(report_path, results["xodr_compare"])
        if strict:
            raise RuntimeError(
                "XODR comparability gate cannot run under strict mode because UP_MANUAL_XODR file is missing. "
                f"manual={manual_xodr!r} report={report_path}"
            )
        return

    report = xodr_compare_gate.build_report(auto_xodr_path, manual_xodr)
    _write_json_deterministic(report_path, report)

    # Record into manifest for provenance
    results["xodr_compare"] = report
    results["xodr_compare_report"] = _normalize_path(os.path.basename(report_path))
    results["xodr_compare_report_full"] = _normalize_path(str(Path(report_path).resolve()))
    results["config"]["manual_xodr_env"] = _normalize_path(manual_xodr)

    if strict and not report.get("comparable", False):
        raise RuntimeError(
            "XODR comparability gate failed under strict mode. "
            f"reason={report.get('reason')} report={report_path}"
        )
    if not report.get("comparable", False):
        print(
            "[WARNING] XODR comparability gate failed (non-strict). "
            f"reason={report.get('reason')} report={report_path}"
        )


# =============================================================================
# Hardware profile detection (lightweight, no heavy deps)
# =============================================================================

def detect_hardware_profile() -> Dict[str, Any]:
    """
    Detect hardware capabilities for auto-profile.
    Returns dict with: vram_gb, profile, detection_method, is_integrated.

    No heavy deps; uses platform-specific lightweight queries.
    """
    result = {
        "vram_gb": None,
        "profile": PROFILE_LAPTOP,  # safe default
        "detection_method": "fallback",
        "is_integrated": False,
        "gpu_name": None,
        "vram_status": "unknown",
        "hybrid_graphics": False,
    }
    detected_names: List[str] = []
    max_vram: Optional[float] = None

    # Try Windows CIM query via PowerShell (no shell invocation, no deprecated wmic).
    if sys.platform == "win32":
        try:
            cmd = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name,AdapterRAM | ConvertTo-Json -Compress",
            ]
            out = subprocess.check_output(cmd, text=True, timeout=5)
            payload = json.loads((out or "").strip() or "[]")
            rows = payload if isinstance(payload, list) else [payload]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    raw = row.get("AdapterRAM")
                    gpu_name = str(row.get("Name", "") or "").strip()
                    if raw not in (None, ""):
                        vram_bytes = int(float(raw))
                        vram_gb = vram_bytes / (1024**3)
                        if max_vram is None or vram_gb > max_vram:
                            max_vram = vram_gb
                    if gpu_name:
                        detected_names.append(gpu_name)
                        lower_name = gpu_name.lower()
                        if any(x in lower_name for x in ["intel", "integrated", "uhd", "iris"]):
                            result["is_integrated"] = True
                    result["detection_method"] = "cim_powershell"
                except (TypeError, ValueError):
                    pass
        except Exception:
            pass

    if detected_names:
        unique_names = sorted(set(detected_names))
        lower_names = [name.lower() for name in unique_names]
        if any("intel" in name for name in lower_names) and any(
            any(x in name for x in ("nvidia", "amd")) for name in lower_names
        ):
            result["hybrid_graphics"] = True
        result["gpu_name"] = unique_names[-1]

    if max_vram is not None:
        result["vram_gb"] = round(max_vram, 1)
        result["vram_status"] = "detected"
    else:
        result["vram_gb"] = None
        result["vram_status"] = "unknown"

    # Classify profile based on VRAM (only when detection succeeded)
    vram = result["vram_gb"]
    if vram is not None and result["vram_status"] == "detected":
        if vram >= 12:
            result["profile"] = PROFILE_RESEARCH
        elif vram >= 8:
            result["profile"] = PROFILE_GAMING
        elif vram >= 4:
            result["profile"] = PROFILE_LAPTOP
        else:
            result["profile"] = PROFILE_LOW_END

    # Integrated GPUs always get laptop profile max
    if result["is_integrated"] and result["profile"] in (PROFILE_RESEARCH, PROFILE_GAMING):
        result["profile"] = PROFILE_LAPTOP

    return result


def compute_policy_decisions(
    *,
    explicit_low_mem: bool,
    explicit_profile: Optional[str],
    experiment_standard: bool,
    max_performance: bool,
    detected_profile: str,
    detected_vram_gb: Optional[float],
    vram_status: str = "unknown",
) -> Dict[str, Any]:
    """
    Pure function: compute policy decisions given CLI args and detected specs.

    Returns dict with:
        effective_profile: str - final profile used
        low_mem_enabled: bool - whether low-mem mode is active
        policy_reason: str - human-readable explanation
        auto_adjusted: bool - whether profile was auto-adjusted

        vram_status: str - "detected" when VRAM is validated, otherwise "unknown" (used to gate numeric comparisons)

    Rules:
        1. Explicit CLI flags always win (--low-mem, --profile)
        2. If --experiment-standard (default): never auto-INCREASE settings
        3. If --max-performance and high-end: allow higher settings
        4. Auto-adjust only DECREASES settings for safety
    """
    result = {
        "effective_profile": detected_profile,
        "low_mem_enabled": explicit_low_mem,
        "policy_reason": "",
        "auto_adjusted": False,
        "experiment_standard": experiment_standard,
        "max_performance": max_performance,
    }

    # Rule 1: Explicit profile wins
    if explicit_profile and explicit_profile != PROFILE_AUTO:
        result["effective_profile"] = explicit_profile
        result["policy_reason"] = f"explicit --profile {explicit_profile}"
        return result

    # Rule 2: Explicit --low-mem wins
    if explicit_low_mem:
        result["policy_reason"] = "explicit --low-mem"
        return result

    # Rule 3: Auto-profile adjustments
    vram_detected = (vram_status == "detected") and (detected_vram_gb is not None)
    vram_text = _format_vram_text(detected_vram_gb)

    if experiment_standard:
        if vram_detected and detected_vram_gb < 4:
            result["low_mem_enabled"] = True
            result["auto_adjusted"] = True
            result["policy_reason"] = f"auto-enabled low-mem ({vram_text} < 4GB, standard mode)"
        elif vram_detected and detected_vram_gb < 6:
            result["low_mem_enabled"] = True
            result["auto_adjusted"] = True
            result["policy_reason"] = f"auto-enabled low-mem ({vram_text} < 6GB, standard mode)"
        elif detected_profile == PROFILE_LOW_END:
            result["low_mem_enabled"] = True
            result["auto_adjusted"] = True
            result["policy_reason"] = f"auto-enabled low-mem (profile={detected_profile}, {vram_text}, standard mode)"
        elif detected_profile == PROFILE_LAPTOP and not vram_detected:
            result["low_mem_enabled"] = True
            result["auto_adjusted"] = True
            result["policy_reason"] = f"auto-enabled low-mem (profile={detected_profile}, {vram_text}, standard mode)"
        else:
            result["policy_reason"] = f"standard mode, no auto-adjustment needed ({vram_text})"

    elif max_performance:
        if detected_profile in (PROFILE_RESEARCH, PROFILE_GAMING):
            result["policy_reason"] = f"max-performance mode, high-end profile ({detected_profile}, {vram_text})"
        else:
            if vram_detected and detected_vram_gb < 4:
                result["low_mem_enabled"] = True
                result["auto_adjusted"] = True
                result["policy_reason"] = f"max-performance but {vram_text} < 4GB, auto-enabled low-mem"
            elif not vram_detected and detected_profile in (PROFILE_LOW_END, PROFILE_LAPTOP):
                result["low_mem_enabled"] = True
                result["auto_adjusted"] = True
                result["policy_reason"] = f"max-performance but {vram_text}, profile={detected_profile}, auto-enabled low-mem"
            else:
                result["policy_reason"] = f"max-performance mode, profile={detected_profile} ({vram_text})"

    else:
        result["policy_reason"] = f"default policy ({vram_text})"

    return result


# =============================================================================
# CARLA probe helpers (no import-time carla)
# =============================================================================

def _check_tcp_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """Check if TCP port is open."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _probe_carla_rpc(host: str, port: int, timeout: float = 10.0) -> Tuple[bool, Optional[str]]:
    """
    Probe CARLA RPC. Returns (success, server_version_or_error).

    Non-fatal when CARLA Python API is missing: the repo should remain offline-safe.
    """
    try:
        carla = get_carla()
    except RuntimeError as exc:
        return False, str(exc)

    try:
        client = carla.Client(host, port)
        client.set_timeout(timeout)
        version = client.get_server_version()
        return True, version
    except Exception as e:
        return False, str(e)


def _get_current_map_name(host: str, port: int, timeout: float = 5.0) -> Optional[str]:
    """Get current world map name. Returns None on failure."""
    try:
        carla = get_carla()
        client = carla.Client(host, port)
        client.set_timeout(timeout)
        world = client.get_world()
        if world:
            carla_map = world.get_map()
            if carla_map:
                return carla_map.name
    except Exception:
        pass
    return None


def _force_opendrive_map_world(host: str, port: int, timeout: float = 30.0) -> Tuple[bool, str]:
    """
    Force CARLA to load OpenDriveMap world before XODR loading.
    Returns (success, message).
    """
    try:
        carla = get_carla()
        client = carla.Client(host, port)
        client.set_timeout(timeout)
        current_map_name = ""
        try:
            world = client.get_world()
            carla_map = world.get_map() if world else None
            current_map_name = str(getattr(carla_map, "name", "") or "")
        except Exception:
            current_map_name = ""
        if "OpenDriveMap" in current_map_name:
            return True, f"OpenDriveMap already active ({current_map_name}); skipping forced load"
        try:
            _reload_ready_for_sensors(client, map_name="OpenDriveMap", tm_port=8000)
            time.sleep(1.0)
            return True, "Loaded OpenDriveMap"
        except Exception:
            return True, "OpenDriveMap not available as named world (will use generate_opendrive_world)"
    except Exception as e:
        return False, str(e)


def wait_for_carla_ready(host: str, port: int, max_wait_s: float = 60.0, first_timeout_s: float = 5.0) -> Dict[str, Any]:
    """Wait until CARLA is reachable via RPC (with exponential backoff on RPC timeout)."""
    t0 = time.time()
    attempt = 0
    last: Dict[str, Any] = {}
    sleep_interval = 0.5
    while time.time() - t0 < max_wait_s:
        attempt += 1
        timeout = min(first_timeout_s * (2 ** (attempt - 1)), 30.0)
        last = _probe_carla_status(host, port)
        last["attempts"] = attempt
        last["wait_s"] = round(time.time() - t0, 3)

        if last.get("tcp_reachable") and last.get("rpc_ok"):
            tick_ok, tick_error = _ensure_carla_ticks(host, port, timeout=timeout)
            last["tick_ok"] = tick_ok
            last["tick_error"] = tick_error
            if tick_ok:
                return last
        remaining = max_wait_s - (time.time() - t0)
        if remaining <= 0:
            break
        time.sleep(min(sleep_interval, remaining))
        sleep_interval = min(sleep_interval * 2, 3.0)
    last["wait_s"] = round(time.time() - t0, 3)
    last["attempts"] = attempt
    return last


def _probe_carla_status(host: str, port: int) -> Dict[str, Any]:
    """
    Full CARLA status probe.
    Returns dict with: reachable, rpc_ok, server_version, map_name.
    """
    result: Dict[str, Any] = {
        "tcp_reachable": False,
        "rpc_ok": False,
        "server_version": None,
        "map_name": None,
    }

    result["tcp_reachable"] = _check_tcp_port(host, port)
    if not result["tcp_reachable"]:
        return result

    rpc_ok, version_or_error = _probe_carla_rpc(host, port)
    result["rpc_ok"] = rpc_ok
    if rpc_ok:
        result["server_version"] = version_or_error
        result["map_name"] = _get_current_map_name(host, port)
    else:
        result["rpc_error"] = version_or_error

    return result


def _ensure_carla_ticks(host: str, port: int, timeout: float, target_ticks: int = 2) -> Tuple[bool, Optional[str]]:
    try:
        carla = get_carla()
    except RuntimeError as exc:
        return False, str(exc)

    try:
        client = carla.Client(host, port)
        # Client timeout must exceed tick timeout (CARLA 0.9.16 requirement)
        client.set_timeout(max(10.0, float(timeout) * 2.0))
        world = client.get_world()
        for _ in range(target_ticks):
            # CARLA 0.9.16: must use positional float, not keyword arg
            world.wait_for_tick(float(timeout))
        return True, None
    except Exception as exc:
        return False, str(exc)


# =============================================================================
# CARLA auto-start (Windows)
# =============================================================================

def _autostart_carla(
    exe_path: str,
    port: int = 2000,
    max_wait_sec: float = 90.0,
    *,
    windowed: bool = False,
    res_x: int = 1024,
    res_y: int = 768,
) -> Dict[str, Any]:
    """
    Start CARLA on Windows via subprocess.Popen.
    Waits for RPC to become available.
    Returns dict with: success, pid, error.
    """
    result: Dict[str, Any] = {
        "success": False,
        "pid": None,
        "error": None,
    }

    cmd = [
        exe_path,
        f"-carla-rpc-port={port}",
        "-quality-level=Low",
        "-fps=20",
    ]

    if windowed:
        cmd.extend(["-windowed", f"-ResX={res_x}", f"-ResY={res_y}"])
    else:
        cmd.append("-RenderOffScreen")

    print(f"[AUTOSTART] Launching CARLA: {exe_path}")
    print(f"[AUTOSTART] Mode: {'windowed ' + str(res_x) + 'x' + str(res_y) if windowed else 'offscreen'}")
    print(f"[AUTOSTART] Command: {' '.join(cmd)}")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        result["pid"] = proc.pid
        print(f"[AUTOSTART] CARLA started with PID {proc.pid}")
    except Exception as e:
        result["error"] = f"Failed to start CARLA: {e}"
        return result

    print(f"[AUTOSTART] Waiting for CARLA RPC (max {max_wait_sec}s)...")
    t0 = time.time()
    last_status = ""

    while (time.time() - t0) < max_wait_sec:
        if proc.poll() is not None:
            result["error"] = f"CARLA process exited with code {proc.returncode}"
            return result

        status = _probe_carla_status("127.0.0.1", port)

        if status["rpc_ok"]:
            elapsed = time.time() - t0
            print(f"[AUTOSTART] CARLA ready in {elapsed:.1f}s (version: {status['server_version']})")
            result["success"] = True
            result["server_version"] = status["server_version"]
            return result

        current = "tcp" if status["tcp_reachable"] else "no_tcp"
        if current != last_status:
            if status["tcp_reachable"]:
                print("[AUTOSTART] TCP port open, waiting for RPC...")
            else:
                print("[AUTOSTART] Waiting for TCP port...")
            last_status = current

        time.sleep(1.0)

    result["error"] = f"CARLA did not become ready within {max_wait_sec}s"
    return result


# =============================================================================
# Arm status classification
# =============================================================================

def _classify_arm_status(
    returncode: int,
    stderr: str,
    carla_status_before: Dict[str, Any],
    carla_status_after: Dict[str, Any],
) -> Tuple[str, bool, Optional[str]]:
    """
    Classify arm failure status.
    Returns (status_code, crash_suspected, crash_classification).
    """
    classification = classify_carla_crash(
        stderr or "",
        status_before=carla_status_before,
        status_after=carla_status_after,
    )

    if returncode == 0:
        return STATUS_SUCCESS, False, None

    if returncode == 2 and stderr and "carla readiness failed" in stderr.lower():
        return STATUS_PREFLIGHT_FAILED, False, classification

    if not carla_status_after["tcp_reachable"]:
        if carla_status_before["tcp_reachable"]:
            return STATUS_CARLA_CRASHED, True, classification
        return STATUS_CARLA_NOT_REACHABLE, False, classification

    if carla_status_before["rpc_ok"] and not carla_status_after["rpc_ok"]:
        return STATUS_CARLA_CRASHED, True, classification

    if stderr and ("HARD STOP" in stderr or "UP_THESIS_STRICT" in stderr):
        return STATUS_STRICT_MAP_IDENTITY_FAIL, False, classification

    if returncode == 3:
        return STATUS_SAFE_RUNNER_MAP_LOAD_RISK, False, classification
    return f"{STATUS_SAFE_RUNNER_EXIT_PREFIX}{int(returncode)}", False, classification


_STATUS_TO_RETURN_CODE = {
    STATUS_SUCCESS: PerceptionReturnCode.OK,
    STATUS_CARLA_NOT_REACHABLE: PerceptionReturnCode.CARLA_NOT_REACHABLE,
    STATUS_CARLA_CRASHED: PerceptionReturnCode.CAPTURE_FAILED,
    STATUS_STRICT_MAP_IDENTITY_FAIL: PerceptionReturnCode.MAP_LOAD_FAILED,
    STATUS_SAFE_RUNNER_MAP_LOAD_RISK: PerceptionReturnCode.MAP_LOAD_FAILED,
    STATUS_SAFE_RUNNER_FAILED: PerceptionReturnCode.CAPTURE_FAILED,
    STATUS_PREFLIGHT_FAILED: PerceptionReturnCode.CAPTURE_FAILED,
}


def _return_code_for_arm(status: str, arm_result: Dict[str, Any]) -> PerceptionReturnCode:
    if status == STATUS_SUCCESS:
        return PerceptionReturnCode.OK

    if isinstance(status, str) and status.startswith(STATUS_SAFE_RUNNER_EXIT_PREFIX):
        try:
            safe_rc = int(status[len(STATUS_SAFE_RUNNER_EXIT_PREFIX) :])
        except Exception:
            safe_rc = -1
        if safe_rc == 3:
            return PerceptionReturnCode.MAP_LOAD_FAILED
        return PerceptionReturnCode.CAPTURE_FAILED

    tick_ok = arm_result.get("carla_status_before", {}).get("tick_ok")
    if status == STATUS_CARLA_CRASHED and tick_ok is False:
        return PerceptionReturnCode.CARLA_HUNG_NO_TICK

    return _STATUS_TO_RETURN_CODE.get(status, PerceptionReturnCode.CAPTURE_FAILED)


def _derive_return_code_from_arms(arms: Dict[str, Any]) -> PerceptionReturnCode:
    for arm in arms.values():
        if not arm.get("success"):
            return _return_code_for_arm(arm.get("status", ""), arm)
    return PerceptionReturnCode.OK


# =============================================================================
# CLI
# =============================================================================

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Two-arm perception experiment runner for thesis domain-gap analysis."
    )

    ap.add_argument(
        "--manual-town",
        required=True,
        help="Manual/reference town passed to both safe-runner arms",
    )
    auto_map_group = ap.add_mutually_exclusive_group(required=True)
    auto_map_group.add_argument(
        "--xodr-in",
        required=False,
        help="Path to auto-generated XODR (08_final*.xodr) for arm B",
    )
    auto_map_group.add_argument(
        "--town",
        required=False,
        help="Cooked town name for arm B (alternative to --xodr-in)",
    )
    # Default calib path: repo-relative ultimate_pipeline/sensors/calib_data.json
    _default_calib = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "sensors",
        "calib_data.json",
    )
    ap.add_argument(
        "--calib",
        required=False,
        default=_default_calib,
        help=(
            "Path to Dominik calib_data.json. "
            f"Default: ultimate_pipeline/sensors/calib_data.json (resolved: {_default_calib})"
        ),
    )
    ap.add_argument(
        "--out-root",
        required=False,
        default=None,
        help="Base output folder (pair subfolder will be created if --out is not set)",
    )
    ap.add_argument(
        "--out",
        required=False,
        default=None,
        help="Explicit output folder for this run (preferred for standardized layout)",
    )
    ap.add_argument(
        "--spawn-index",
        type=int,
        default=0,
        help="Spawn point index (must exist in both maps). Default: 0",
    )
    ap.add_argument(
        "--fps",
        type=int,
        default=10,
        help="FPS for synchronous capture. Default: 10",
    )
    ap.add_argument(
        "--duration",
        type=int,
        default=5,
        help="Recording duration in seconds. Default: 5",
    )
    ap.add_argument(
        "--weather",
        default="ClearNoon",
        help="Weather preset (optional). Default: ClearNoon",
    )
    ap.add_argument(
        "--repair-parampoly3-to-line",
        action="store_true",
        help="Repair invalid paramPoly3 geometries to line during XODR hardening",
    )
    ap.add_argument(
        "--strict",
        dest="strict",
        action="store_true",
        default=True,
        help="Enable UP_THESIS_STRICT=1 (blocks Town* fallback). Default: enabled.",
    )
    ap.add_argument(
        "--no-strict",
        dest="strict",
        action="store_false",
        help="Disable UP_THESIS_STRICT",
    )
    ap.add_argument(
        "--host",
        default="127.0.0.1",
        help="CARLA host. Default: 127.0.0.1",
    )
    ap.add_argument(
        "--port",
        type=int,
        default=2000,
        help="CARLA port. Default: 2000",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=42,
        help="TrafficManager random seed. Default: 42",
    )
    ap.add_argument(
        "--vehicle",
        default="vehicle.audi.a2",
        help="Vehicle blueprint ID. Default: vehicle.audi.a2",
    )
    ap.add_argument(
        "--autostart-carla-exe",
        help="Optional: path to CarlaUE4.exe for auto-start if CARLA not running",
    )
    ap.add_argument(
        "--autostart-wait",
        type=float,
        default=90.0,
        help="Max seconds to wait for CARLA auto-start. Default: 90",
    )
    ap.add_argument(
        "--autostart-windowed",
        action="store_true",
        help="Use windowed mode for auto-start (lower VRAM than -RenderOffScreen)",
    )
    ap.add_argument(
        "--autostart-res-x",
        type=int,
        default=1024,
        help="Window width for windowed auto-start. Default: 1024",
    )
    ap.add_argument(
        "--autostart-res-y",
        type=int,
        default=768,
        help="Window height for windowed auto-start. Default: 768",
    )

    ap.add_argument(
        "--low-mem",
        action="store_true",
        help="Enable low-memory mode: RGB cameras 800x600. Use for 4-6GB GPUs or OOM scenarios.",
    )

    ap.add_argument(
        "--experiment-standard",
        dest="experiment_standard",
        action="store_true",
        default=True,
        help="Standard experiment mode (default): never auto-INCREASE settings on high-end hardware. "
             "Only auto-DECREASE on low-end for safety. Ensures reproducibility across machines.",
    )
    ap.add_argument(
        "--no-experiment-standard",
        dest="experiment_standard",
        action="store_false",
        help="Disable standard experiment mode.",
    )
    ap.add_argument(
        "--max-performance",
        action="store_true",
        default=False,
        help="Allow higher settings on high-end hardware (research/gaming profiles). "
             "Mutually exclusive intent with --experiment-standard for auto-increases.",
    )

    ap.add_argument(
        "--profile",
        choices=["auto", "research", "gaming", "laptop", "low_end"],
        default="auto",
        help="Hardware profile. 'auto' detects VRAM. 'research' = HPC/workstation (>=12GB), "
             "'gaming' = 8-12GB, 'laptop' = 4-8GB, 'low_end' = <4GB. Default: auto",
    )

    ap.add_argument(
        "--auto-profile",
        dest="auto_profile",
        action="store_true",
        default=True,
        help="Enable hardware auto-profiling (default).",
    )
    ap.add_argument(
        "--no-auto-profile",
        dest="auto_profile",
        action="store_false",
        help="Disable hardware auto-profiling.",
    )
    ap.add_argument(
        "--print-hardware",
        action="store_true",
        help="Print detected hardware profile details before running.",
    )

    # -------------------------------------------------------------------------
    # FIX: CLI schema completeness for readiness/wait knobs
    # -------------------------------------------------------------------------
    ap.add_argument(
        "--carla-wait",
        type=float,
        default=60.0,
        help="Max seconds to wait for CARLA readiness before each arm. Default: 60.0",
    )
    ap.add_argument(
        "--carla-probe-timeout",
        type=float,
        default=5.0,
        help="RPC timeout (seconds) used during CARLA readiness probes and preflight. Default: 5.0",
    )

    # Semantic segmentation capture options
    ap.add_argument(
        "--seg",
        action="store_true",
        help="Also record semantic segmentation cameras",
    )
    ap.add_argument(
        "--seg-converter",
        choices=["raw", "cityscapes"],
        default="cityscapes",
        help="Semantic segmentation label converter. Default: cityscapes",
    )

    ap.add_argument(
        "--spawn-enrichments",
        default="",
        help="Optional enrichments.json path; if provided, spawn proxy actors before recording",
    )
    ap.add_argument(
        "--spawn-enrichments-limit",
        type=int,
        default=500,
        help="Max number of enrichment actors to spawn (default: 500)",
    )
    ap.add_argument(
        "--spawn-enrichments-seed",
        type=int,
        default=1337,
        help="Deterministic sampling seed for enrichment actors (default: 1337)",
    )
    ap.add_argument(
        "--spawn-enrichments-filter",
        default="",
        help='Optional comma-separated types filter (e.g., "building,bench")',
    )
    ap.add_argument(
        "--qa-capture",
        action="store_true",
        help="Capture one frame per camera and one LiDAR snapshot into qa_bundle/ after each arm",
    )
    ap.add_argument(
        "--no-carla",
        action="store_true",
        help="Skip CARLA capture (writes artifacts only, for dry-run/testing)",
    )

    args = ap.parse_args()
    if not args.out and not args.out_root:
        ap.error("Either --out or --out-root is required.")
    return args


def run_safe_runner_arm(
    *,
    arm_label: str,
    out_dir: str,
    safe_runner_cmd: List[str],
    host: str,
    port: int,
    strict: bool,
    low_mem: bool = False,
    carla_wait_s: float = 60.0,
    carla_probe_timeout_s: float = 5.0,
    unsupported_flags: Optional[Dict[str, Any]] = None,
    env_overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Run run_perception_safe.py as subprocess for one arm.

    Returns dict with detailed status including crash classification.
    """
    artifacts = _ensure_arm_audit_files(out_dir, arm_label=arm_label)
    cmd = list(safe_runner_cmd)

    env = os.environ.copy()
    if strict:
        env["UP_THESIS_STRICT"] = "1"
    else:
        env.pop("UP_THESIS_STRICT", None)
    if low_mem:
        env["UP_LOW_MEMORY_PROFILE"] = "1"
    env["UP_RPC_TIMEOUT_S"] = str(float(carla_probe_timeout_s))
    env["UP_STREAM_TIMEOUT_S"] = str(float(carla_probe_timeout_s))
    if env_overrides:
        for key, value in env_overrides.items():
            env[str(key)] = str(value)

    print(f"\n[{arm_label}] Starting run_perception_safe...")
    print(f"[{arm_label}] Command: {' '.join(cmd)}")
    if unsupported_flags:
        print(
            f"[{arm_label}] INFO: pair-only flags not mapped to safe runner: "
            f"{json.dumps(unsupported_flags, sort_keys=True, ensure_ascii=True)}"
        )
    if env_overrides:
        print(
            f"[{arm_label}] INFO: safe-runner env overrides: "
            f"{json.dumps(env_overrides, sort_keys=True, ensure_ascii=True)}"
        )

    # Use bounded readiness check with artifact writing
    carla_ready_result = wait_for_carla_ready_bounded(
        host,
        port,
        max_retries=10,
        sleep_s=0.5,
        tick_timeout_s=carla_probe_timeout_s,
        out_dir=out_dir,
    )

    # Also run the full wait_for_carla_ready for detailed status
    carla_status_before = wait_for_carla_ready(
        host, port,
        max_wait_s=carla_wait_s,
        first_timeout_s=carla_probe_timeout_s,
    )

    if not carla_status_before.get("tick_ok"):
        tick_error = carla_status_before.get("tick_error", "CARLA readiness timeout")
        print(f"[{arm_label}] CARLA readiness failed: {tick_error}")
        try:
            Path(os.path.join(out_dir, "record_route_stderr.txt")).write_text(
                f"CARLA readiness failed: {tick_error}\n",
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            pass
        failure_result: Dict[str, Any] = {
            "success": False,
            "status": STATUS_CARLA_CRASHED,
            "exit_code": -1,
            "elapsed_sec": round(carla_status_before.get("wait_s", 0.0), 2),
            "crash_suspected": True,
            "carla_reachable_after": carla_status_before.get("tcp_reachable", False)
            and carla_status_before.get("rpc_ok", False),
            "carla_status_before": carla_status_before,
            "carla_status_after": dict(carla_status_before),
            "tick_error": tick_error,
            "carla_ready_bounded": carla_ready_result,
        }
        failure_result.update(artifacts)
        _write_run_status(
            out_dir,
            {
                "arm": arm_label,
                "stage": "carla_readiness",
                "success": False,
                "exit_code": -1,
                "error": tick_error,
            },
        )
        return failure_result

    t0 = time.time()
    result = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.time() - t0

    # Always persist full stdout/stderr for post-mortem debugging (Arm A/B).
    try:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "record_route_stdout.txt").write_text(result.stdout or "", encoding="utf-8", errors="replace")
        (Path(out_dir) / "record_route_stderr.txt").write_text(result.stderr or "", encoding="utf-8", errors="replace")
    except Exception:
        pass

    carla_status_after = _probe_carla_status(host, port)

    status_code, crash_suspected, crash_classification = _classify_arm_status(
        result.returncode,
        result.stderr,
        carla_status_before,
        carla_status_after,
    )

    arm_result: Dict[str, Any] = {
        "success": result.returncode == 0,
        "status": status_code,
        "exit_code": result.returncode,
        "elapsed_sec": round(elapsed, 2),
        "crash_suspected": crash_suspected,
        "carla_reachable_after": carla_status_after["tcp_reachable"] and carla_status_after["rpc_ok"],
    }
    arm_result.update(artifacts)

    # Pull a small spawn summary from the arm run_status.json (if present) for the pair manifest.
    try:
        run_status_path = os.path.join(out_dir, "run_status.json")
        if os.path.isfile(run_status_path):
            status_obj = json.loads(Path(run_status_path).read_text(encoding="utf-8", errors="replace"))
            arm_result["spawn_index_selected"] = status_obj.get("spawn_index_selected")
            arm_result["spawn_transform"] = status_obj.get("spawn_transform")
            if "skip_destroy" in status_obj:
                arm_result["skip_destroy"] = status_obj.get("skip_destroy")
    except Exception:
        pass
    if crash_classification:
        arm_result["crash_classification"] = crash_classification

    if carla_status_after["rpc_ok"]:
        arm_result["carla_server_version_after"] = carla_status_after.get("server_version")

    if result.returncode != 0:
        print(f"[{arm_label}] FAILED (status={status_code}, exit_code={result.returncode})")
        if crash_suspected:
            print(f"[{arm_label}] CRASH SUSPECTED: CARLA may have crashed during load/record")
        stderr_tail = _truncate_stderr(result.stderr, STDERR_TAIL_LINES)
        stdout_tail = _truncate_stdout(result.stdout, STDERR_TAIL_LINES)
        arm_result["stderr_tail"] = stderr_tail
        arm_result["stdout_tail"] = stdout_tail
        crash_payload = {
            "arm": arm_label,
            "status": status_code,
            "classification": crash_classification
            or classify_carla_crash(
                result.stderr,
                status_before=carla_status_before,
                status_after=carla_status_after,
            ),
            "exit_code": result.returncode,
            "stderr_tail": stderr_tail,
            "stdout_tail": stdout_tail,
            "carla_status_before": carla_status_before,
            "carla_status_after": carla_status_after,
            "crash_suspected": crash_suspected,
        }
        crash_report_path = write_crash_report(out_dir, crash_payload)
        arm_result["crash_report"] = _normalize_path(crash_report_path)
        _write_run_status(
            out_dir,
            {
                "arm": arm_label,
                "stage": "safe_runner_subprocess",
                "success": False,
                "exit_code": int(result.returncode),
                "error": crash_payload.get("classification")
                or f"{STATUS_SAFE_RUNNER_FAILED}:{result.returncode}",
            },
        )
    else:
        meta_path = None
        for root, _dirs, files in os.walk(out_dir):
            if "meta.json" in files:
                meta_path = os.path.join(root, "meta.json")
                break

        print(f"[{arm_label}] SUCCESS ({elapsed:.1f}s)")
        if meta_path:
            arm_result["meta_path"] = _normalize_path(meta_path)
            print(f"[{arm_label}] meta.json: {meta_path}")
        _write_run_status(
            out_dir,
            {
                "arm": arm_label,
                "stage": "safe_runner_subprocess",
                "success": True,
                "exit_code": 0,
                "error": None,
            },
        )

    arm_result["safe_runner_return_code"] = int(result.returncode)
    arm_result["safe_runner_command"] = cmd
    if env_overrides:
        arm_result["safe_runner_env_overrides"] = dict(env_overrides)
    if unsupported_flags:
        arm_result["unmapped_pair_flags"] = unsupported_flags

    return arm_result


def run_record_route(
    *,
    arm_label: str,
    out_dir: str,
    town: str,
    calib: str,
    spawn_index: int = 0,
    fps: float = 10.0,
    duration: float = 30.0,
    seed: int = 42,
    host: str = "127.0.0.1",
    port: int = 2000,
    vehicle: str = "vehicle.lincoln.mkz_2017",
    strict: bool = False,
    seg: bool = False,
    seg_converter: str = "raw",
    use_current_world: bool = False,
    rig: str = "thesis",
    xodr: Optional[str] = None,
    low_mem: bool = False,
    carla_wait_s: float = 60.0,
    carla_probe_timeout_s: float = 5.0,
) -> Dict[str, Any]:
    """Backward-compatible wrapper used by legacy tests and older integrations."""
    _ = spawn_index  # retained for compatibility; safe runner has no direct spawn-index flag
    _ = xodr         # retained for compatibility; map selection is passed through --town here
    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.run_perception_safe",
        "--manual-town",
        str(town),
        "--town",
        str(town),
        "--calib",
        str(calib),
        "--out",
        str(out_dir),
        "--frames",
        str(int(float(fps) * float(duration))),
        "--fps",
        str(float(fps)),
        "--rig",
        str(rig),
        "--host",
        str(host),
        "--port",
        str(int(port)),
        "--vehicle",
        str(vehicle),
        "--seed",
        str(int(seed)),
    ]
    if bool(use_current_world):
        cmd.append("--use-current-world")
    if bool(seg):
        cmd.append("--seg")
        cmd.extend(["--seg-converter", str(seg_converter)])

    return run_safe_runner_arm(
        arm_label=arm_label,
        out_dir=out_dir,
        safe_runner_cmd=cmd,
        host=host,
        port=int(port),
        strict=bool(strict),
        low_mem=bool(low_mem),
        carla_wait_s=float(carla_wait_s),
        carla_probe_timeout_s=float(carla_probe_timeout_s),
    )


def main() -> int:
    _configure_windows_encoding()
    args = parse_args()

    _validate_manual_town(args.manual_town)
    # Recommended calib path for helpful error messages
    _recommended_calib = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "sensors",
        "calib_data.json",
    )
    _validate_file_exists(args.calib, "--calib", recommended_path=_recommended_calib)
    if args.xodr_in:
        _validate_file_exists(args.xodr_in, "--xodr-in")

    carla_autostart_used = False
    carla_autostart_pid = None
    carla_autostart_result = None

    if args.autostart_carla_exe:
        _validate_exe_path(args.autostart_carla_exe, "--autostart-carla-exe")

    hw_detection = detect_hardware_profile()
    policy = compute_policy_decisions(
        explicit_low_mem=args.low_mem,
        explicit_profile=args.profile if args.profile != "auto" else None,
        experiment_standard=args.experiment_standard,
        max_performance=args.max_performance,
        detected_profile=hw_detection["profile"],
        detected_vram_gb=hw_detection["vram_gb"],
        vram_status=hw_detection["vram_status"],
    )
    effective_low_mem = policy["low_mem_enabled"]

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    if args.out:
        pair_dir = os.path.abspath(args.out)
        pair_name = os.path.basename(pair_dir.rstrip("\\/")) or f"pair_{args.manual_town}_{timestamp}"
    else:
        pair_name = f"pair_{args.manual_town}_{timestamp}"
        pair_dir = os.path.join(args.out_root, pair_name)
    os.makedirs(pair_dir, exist_ok=True)

    arm_a_dir = os.path.join(pair_dir, "manual")
    arm_b_dir = os.path.join(pair_dir, "auto")
    arm_a_sensors_dir = os.path.join(arm_a_dir, "sensors")
    arm_b_sensors_dir = os.path.join(arm_b_dir, "sensors")
    os.makedirs(arm_a_dir, exist_ok=True)
    os.makedirs(arm_b_dir, exist_ok=True)
    os.makedirs(arm_a_sensors_dir, exist_ok=True)
    os.makedirs(arm_b_sensors_dir, exist_ok=True)
    arm_a_artifacts = _ensure_arm_audit_files(arm_a_sensors_dir, arm_label="A_manual")
    arm_b_artifacts = _ensure_arm_audit_files(arm_b_sensors_dir, arm_label="B_auto")
    xodr_hash = _hash_file(args.xodr_in) if args.xodr_in else None
    hash_algo = "sha256"

    disable_carla = bool(args.no_carla or _env_bool("UP_DISABLE_CARLA"))

    # Use the same probe timeout knob for preflight (keeps behavior configurable and consistent)
    if disable_carla:
        preflight = {"ok": False, "error": "disabled", "detail": "UP_DISABLE_CARLA"}
    else:
        preflight = carla_preflight(host=args.host, port=args.port, timeout_s=float(args.carla_probe_timeout))
    preflight_after_autostart: Optional[Dict[str, Any]] = None

    config = _build_config_dict(args, effective_low_mem, xodr_hash, hash_algo)
    results = _build_manifest_payload(
        pair_name=pair_name,
        timestamp=timestamp,
        config=config,
        hardware_detection=hw_detection,
        policy=policy,
        preflight=preflight,
    )
    results["carla_status_initial"] = {}
    results["carla_autostart_used"] = False
    # Write an initial manifest immediately so the run is self-auditing even if interrupted.
    results["arms"]["A_manual"] = {
        "out_dir": _normalize_path(arm_a_dir),
        "sensors_dir": _normalize_path(arm_a_sensors_dir),
        "status": "PENDING",
        **arm_a_artifacts,
    }
    results["arms"]["B_auto"] = {
        "out_dir": _normalize_path(arm_b_dir),
        "sensors_dir": _normalize_path(arm_b_sensors_dir),
        "status": "PENDING",
        **arm_b_artifacts,
    }
    _write_pair_manifest(pair_dir, results)

    protocol_snapshot_path = _write_protocol_snapshot(
        pair_dir,
        args,
        calib_hash=_hash_file(args.calib),
        hw_detection=hw_detection,
        policy=policy,
        seeds={
            "seed": int(args.seed),
            "spawn_enrichments_seed": int(args.spawn_enrichments_seed),
        },
    )
    results["protocol_snapshot"] = _normalize_path(protocol_snapshot_path)
    safe_runner_env_overrides = _build_safe_runner_env_overrides(
        seed=int(args.seed),
        weather=str(args.weather),
        seg=bool(args.seg),
    )

    if disable_carla:
        planned_arm_a_cmd = _build_manual_arm_safe_command(
            manual_town=args.manual_town,
            out_dir=arm_a_sensors_dir,
            calib=args.calib,
            fps=int(args.fps),
            duration_s=int(args.duration),
            host=args.host,
            port=int(args.port),
            low_mem=bool(effective_low_mem),
            spawn_enrichments_path=str(args.spawn_enrichments or ""),
            spawn_enrichments_limit=int(args.spawn_enrichments_limit),
            spawn_enrichments_seed=int(args.spawn_enrichments_seed),
            spawn_enrichments_filter=str(args.spawn_enrichments_filter or ""),
            qa_capture_after_enrichment=bool(args.qa_capture),
            seg=bool(args.seg),
        )
        planned_arm_b_cmd = _build_auto_arm_safe_command(
            manual_town=args.manual_town,
            auto_town=args.town,
            auto_xodr=args.xodr_in,
            out_dir=arm_b_sensors_dir,
            calib=args.calib,
            fps=int(args.fps),
            duration_s=int(args.duration),
            host=args.host,
            port=int(args.port),
            low_mem=bool(effective_low_mem),
            spawn_enrichments_path=str(args.spawn_enrichments or ""),
            spawn_enrichments_limit=int(args.spawn_enrichments_limit),
            spawn_enrichments_seed=int(args.spawn_enrichments_seed),
            spawn_enrichments_filter=str(args.spawn_enrichments_filter or ""),
            qa_capture_after_enrichment=bool(args.qa_capture),
            seg=bool(args.seg),
        )
        results["success"] = False
        results["failure_reason"] = "carla_disabled"
        results["failure_category"] = PerceptionReturnCode.CARLA_NOT_REACHABLE.name
        results["return_code"] = PerceptionReturnCode.OK.name
        results["return_code_value"] = PerceptionReturnCode.OK.value
        results["arms"]["A_manual"]["status"] = "SKIPPED"
        results["arms"]["A_manual"]["safe_runner_command"] = planned_arm_a_cmd
        results["arms"]["A_manual"]["safe_runner_env_overrides"] = dict(safe_runner_env_overrides)
        results["arms"]["B_auto"]["status"] = "SKIPPED"
        results["arms"]["B_auto"]["safe_runner_command"] = planned_arm_b_cmd
        results["arms"]["B_auto"]["safe_runner_env_overrides"] = dict(safe_runner_env_overrides)
        _write_run_manifest(
            arm_a_dir,
            {
                "arm": "manual",
                "status": "skipped",
                "sensors_dir": _normalize_path(arm_a_sensors_dir),
                "reason": "carla_disabled",
            },
        )
        _write_run_manifest(
            arm_b_dir,
            {
                "arm": "auto",
                "status": "skipped",
                "sensors_dir": _normalize_path(arm_b_sensors_dir),
                "reason": "carla_disabled",
            },
        )
        _write_pair_manifest(pair_dir, results)
        _write_perception_status(pair_dir, results)
        _write_determinism_links(pair_dir, arm_a_dir, arm_b_dir)
        metrics_payload = {
            "enabled": False,
            "reason": "carla_disabled",
        }
        _write_json_deterministic(os.path.join(pair_dir, "perception_metrics.json"), metrics_payload)
        return PerceptionReturnCode.OK.value

    if not preflight.get("ok") and (preflight.get("error") == "import_failed" or not args.autostart_carla_exe):
        crash_report_path = write_crash_report(
            pair_dir,
            {
                "stage": "pair_preflight",
                "classification": classify_carla_crash("", preflight=preflight),
                "preflight": preflight,
            },
            filename="pair_crash_report.json",
        )
        message = preflight.get("detail") or preflight.get("error") or "CARLA preflight failed"
        print(f"[ERROR] CARLA preflight failed: {message}")
        print(f"[ERROR] Crash report: {crash_report_path}")
        results["success"] = False
        results["failure_reason"] = message
        results["failure_category"] = PerceptionReturnCode.CARLA_NOT_REACHABLE.name
        results["return_code"] = PerceptionReturnCode.CARLA_NOT_REACHABLE.name
        results["return_code_value"] = PerceptionReturnCode.CARLA_NOT_REACHABLE.value
        results["crash_report"] = _normalize_path(crash_report_path)
        manifest_path = _write_pair_manifest(pair_dir, results)
        _write_perception_status(pair_dir, results)
        print(f"Manifest: {manifest_path}")
        return PerceptionReturnCode.CARLA_NOT_REACHABLE.value

    print("=" * 60)
    print("Two-Arm Perception Experiment")
    print("=" * 60)
    print(f"Manual town (arm A): Grid0828" if args.manual_town == "Grid0828" else f"Manual town (arm A): {args.manual_town}")
    if args.xodr_in:
        print(f"Auto XODR (arm B):   {args.xodr_in}")
    else:
        print(f"Auto town (arm B):   {args.town}")
    print(f"Spawn index:         {args.spawn_index}")
    print(f"FPS:                 {args.fps}")
    print(f"Duration:            {args.duration}s")
    print(f"Seed:                {args.seed}")
    print(f"Strict mode:         {args.strict}")
    print(f"Profile:             {policy['effective_profile']} (detected: {hw_detection['profile']}, VRAM: {_format_vram_text(hw_detection['vram_gb'])})")
    print(f"Experiment mode:     {'standard' if args.experiment_standard else 'custom'}{' + max-performance' if args.max_performance else ''}")
    print(f"Low-mem mode:        {effective_low_mem}{' (auto)' if policy['auto_adjusted'] else ''}")
    print(f"Policy reason:       {policy['policy_reason']}")
    print(f"CARLA wait:          {args.carla_wait}s (probe timeout: {args.carla_probe_timeout}s)")
    print(f"Output dir:          {pair_dir}")
    if args.autostart_carla_exe:
        print(f"Auto-start exe:      {args.autostart_carla_exe}")
        if args.autostart_windowed:
            print(f"Auto-start mode:     windowed {args.autostart_res_x}x{args.autostart_res_y}")
        else:
            print("Auto-start mode:     offscreen")
    print("=" * 60)

    initial_status = _probe_carla_status(args.host, args.port)
    results["carla_status_initial"] = initial_status

    if not initial_status["rpc_ok"]:
        if args.autostart_carla_exe:
            print("\n[CARLA] Not reachable. Attempting auto-start...")
            carla_autostart_result = _autostart_carla(
                args.autostart_carla_exe,
                port=args.port,
                max_wait_sec=args.autostart_wait,
                windowed=args.autostart_windowed,
                res_x=args.autostart_res_x,
                res_y=args.autostart_res_y,
            )
            carla_autostart_used = True
            carla_autostart_pid = carla_autostart_result.get("pid")

            if not carla_autostart_result["success"]:
                print(f"[ERROR] CARLA auto-start failed: {carla_autostart_result.get('error')}")
                results["success"] = False
                results["carla_autostart_used"] = True
                results["carla_autostart_pid"] = carla_autostart_pid
                results["carla_autostart_result"] = carla_autostart_result
                results["carla_autostart_error"] = carla_autostart_result.get("error")
                results["failure_reason"] = results["carla_autostart_error"]
                results["failure_category"] = PerceptionReturnCode.CARLA_NOT_REACHABLE.name
                results["return_code"] = PerceptionReturnCode.CARLA_NOT_REACHABLE.name
                results["return_code_value"] = PerceptionReturnCode.CARLA_NOT_REACHABLE.value
                manifest_path = _write_pair_manifest(pair_dir, results)
                _write_perception_status(pair_dir, results)
                print(f"Manifest: {manifest_path}")
                return PerceptionReturnCode.CARLA_NOT_REACHABLE.value
        else:
            print(f"[ERROR] CARLA not reachable at {args.host}:{args.port}")
            print("Use --autostart-carla-exe to auto-start CARLA")
            results["success"] = False
            results["failure_reason"] = f"CARLA not reachable at {args.host}:{args.port}"
            results["failure_category"] = PerceptionReturnCode.CARLA_NOT_REACHABLE.name
            results["return_code"] = PerceptionReturnCode.CARLA_NOT_REACHABLE.name
            results["return_code_value"] = PerceptionReturnCode.CARLA_NOT_REACHABLE.value
            manifest_path = _write_pair_manifest(pair_dir, results)
            _write_perception_status(pair_dir, results)
            print(f"Manifest: {manifest_path}")
            return PerceptionReturnCode.CARLA_NOT_REACHABLE.value

    results["carla_autostart_used"] = carla_autostart_used
    if carla_autostart_used:
        results["carla_autostart_pid"] = carla_autostart_pid
        results["carla_autostart_result"] = carla_autostart_result

    if carla_autostart_used and carla_autostart_result and carla_autostart_result.get("success"):
        preflight_after_autostart = carla_preflight(
            host=args.host, port=args.port, timeout_s=float(args.carla_probe_timeout)
        )
        results["carla_preflight_after_autostart"] = preflight_after_autostart

    unmapped_pair_flags = _collect_unmapped_pair_flags(
        spawn_index=args.spawn_index,
        seed=args.seed,
        vehicle=args.vehicle,
        weather=args.weather,
        repair_parampoly3_to_line=args.repair_parampoly3_to_line,
        seg=args.seg,
        seg_converter=args.seg_converter,
    )
    if unmapped_pair_flags:
        results["unmapped_pair_flags"] = unmapped_pair_flags
        _warn_once(
            "Some run_perception_pair flags have no run_perception_safe equivalent; "
            "see pair_manifest.json -> unmapped_pair_flags."
        )

    # =========================================================================
    # Arm A: Manual map
    # =========================================================================
    arm_a_cmd = _build_manual_arm_safe_command(
        manual_town=args.manual_town,
        out_dir=arm_a_sensors_dir,
        calib=args.calib,
        fps=int(args.fps),
        duration_s=int(args.duration),
        host=args.host,
        port=int(args.port),
        low_mem=bool(effective_low_mem),
        spawn_enrichments_path=str(args.spawn_enrichments or ""),
        spawn_enrichments_limit=int(args.spawn_enrichments_limit),
        spawn_enrichments_seed=int(args.spawn_enrichments_seed),
        spawn_enrichments_filter=str(args.spawn_enrichments_filter or ""),
        qa_capture_after_enrichment=bool(args.qa_capture),
        seg=bool(args.seg),
    )
    arm_a_result = run_safe_runner_arm(
        arm_label="Arm A (manual)",
        out_dir=arm_a_sensors_dir,
        safe_runner_cmd=arm_a_cmd,
        host=args.host,
        port=int(args.port),
        strict=args.strict,
        low_mem=effective_low_mem,
        carla_wait_s=args.carla_wait,
        carla_probe_timeout_s=args.carla_probe_timeout,
        unsupported_flags=unmapped_pair_flags or None,
        env_overrides=safe_runner_env_overrides,
    )
    arm_a_result["out_dir"] = _normalize_path(arm_a_dir)
    arm_a_result["sensors_dir"] = _normalize_path(arm_a_sensors_dir)

    arm_a_run_manifest = _write_run_manifest(
        arm_a_dir,
        {
            "arm": "manual",
            "status": arm_a_result.get("status"),
            "success": arm_a_result.get("success"),
            "sensors_dir": _normalize_path(arm_a_sensors_dir),
            "qa_bundle": _normalize_path(os.path.join(arm_a_sensors_dir, "qa_bundle"))
            if args.qa_capture
            else None,
            "safe_runner_stdout": arm_a_result.get("stdout_path"),
            "safe_runner_stderr": arm_a_result.get("stderr_path"),
        },
    )
    arm_a_result["run_manifest"] = _normalize_path(arm_a_run_manifest)
    results["arms"]["A_manual"] = arm_a_result
    _write_pair_manifest(pair_dir, results)

    if not arm_a_result["success"]:
        print(f"\n[ERROR] Arm A failed (status={arm_a_result['status']}). Aborting pair experiment.")
        results["success"] = False
        return_code = _return_code_for_arm(arm_a_result["status"], arm_a_result)
        results["return_code"] = return_code.name
        results["return_code_value"] = return_code.value
        results["failure_category"] = return_code.name
        results["failure_reason"] = arm_a_result.get("tick_error") or arm_a_result.get("status")
        manifest_path = _write_pair_manifest(pair_dir, results)
        _write_perception_status(pair_dir, results)
        print(f"Manifest: {manifest_path}")
        return return_code.value

    # =========================================================================
    # Before Arm B: if using XODR, prepare OpenDrive world
    # =========================================================================
    if args.xodr_in:
        world_map_before_xodr = _get_current_map_name(args.host, args.port)
        results["world_map_name_before_xodr_load"] = world_map_before_xodr
        print("\n[XODR PREP] Preparing for XODR load...")
        odm_result = _force_opendrive_map_world(args.host, args.port)
        print(f"[XODR PREP] {odm_result[1]}")
        _maybe_run_xodr_compare_gate(
            auto_xodr_path=args.xodr_in,
            pair_dir=pair_dir,
            strict=args.strict,
            results=results,
        )
    else:
        results["world_map_name_before_xodr_load"] = None

    # =========================================================================
    # Arm B: Auto map (XODR or town)
    # =========================================================================
    arm_b_cmd = _build_auto_arm_safe_command(
        manual_town=args.manual_town,
        auto_town=args.town,
        auto_xodr=args.xodr_in,
        out_dir=arm_b_sensors_dir,
        calib=args.calib,
        fps=int(args.fps),
        duration_s=int(args.duration),
        host=args.host,
        port=int(args.port),
        low_mem=bool(effective_low_mem),
        spawn_enrichments_path=str(args.spawn_enrichments or ""),
        spawn_enrichments_limit=int(args.spawn_enrichments_limit),
        spawn_enrichments_seed=int(args.spawn_enrichments_seed),
        spawn_enrichments_filter=str(args.spawn_enrichments_filter or ""),
        qa_capture_after_enrichment=bool(args.qa_capture),
        seg=bool(args.seg),
    )
    arm_b_result = run_safe_runner_arm(
        arm_label="Arm B (auto)",
        out_dir=arm_b_sensors_dir,
        safe_runner_cmd=arm_b_cmd,
        host=args.host,
        port=int(args.port),
        strict=args.strict,
        low_mem=effective_low_mem,
        carla_wait_s=args.carla_wait,
        carla_probe_timeout_s=args.carla_probe_timeout,
        unsupported_flags=unmapped_pair_flags or None,
        env_overrides=safe_runner_env_overrides,
    )
    arm_b_result["out_dir"] = _normalize_path(arm_b_dir)
    arm_b_result["sensors_dir"] = _normalize_path(arm_b_sensors_dir)

    arm_b_run_manifest = _write_run_manifest(
        arm_b_dir,
        {
            "arm": "auto",
            "status": arm_b_result.get("status"),
            "success": arm_b_result.get("success"),
            "sensors_dir": _normalize_path(arm_b_sensors_dir),
            "qa_bundle": _normalize_path(os.path.join(arm_b_sensors_dir, "qa_bundle"))
            if args.qa_capture
            else None,
            "safe_runner_stdout": arm_b_result.get("stdout_path"),
            "safe_runner_stderr": arm_b_result.get("stderr_path"),
        },
    )
    arm_b_result["run_manifest"] = _normalize_path(arm_b_run_manifest)
    results["arms"]["B_auto"] = arm_b_result

    results["success"] = arm_a_result["success"] and arm_b_result["success"]
    results["total_elapsed_sec"] = round(
        arm_a_result.get("elapsed_sec", 0) + arm_b_result.get("elapsed_sec", 0),
        2,
    )
    return_code = _derive_return_code_from_arms(results["arms"])
    results["return_code"] = return_code.name
    results["return_code_value"] = return_code.value
    if not results["success"]:
        failed_arm = arm_a_result if not arm_a_result["success"] else arm_b_result
        results["failure_reason"] = failed_arm.get("tick_error") or failed_arm.get("status")
        results["failure_category"] = return_code.name

    manual_metrics = compute_perception_metrics(arm_a_sensors_dir)
    auto_metrics = compute_perception_metrics(arm_b_sensors_dir)
    pair_metrics_enabled = bool(manual_metrics.get("enabled") and auto_metrics.get("enabled"))
    perception_metrics_payload = {
        "enabled": pair_metrics_enabled,
        "manual": manual_metrics,
        "auto": auto_metrics,
        "diff": _compute_pair_metrics_diff(manual_metrics, auto_metrics),
    }
    _write_json_deterministic(
        os.path.join(pair_dir, "perception_metrics.json"),
        perception_metrics_payload,
    )
    _write_determinism_links(pair_dir, arm_a_dir, arm_b_dir)

    manifest_path = _write_pair_manifest(pair_dir, results)
    perception_status_path = _write_perception_status(pair_dir, results)

    print("\n" + "=" * 60)
    print("PAIR EXPERIMENT COMPLETE")
    print("=" * 60)
    print(f"Overall success: {results['success']}")
    print(f"Arm A status: {arm_a_result['status']}")
    print(f"Arm B status: {arm_b_result['status']}")
    print(f"Manifest: {manifest_path}")

    if not results["success"]:
        print("\n[WARNING] Experiment failed. Check arm statuses above.")
        return return_code.value

    print("\nTo run offline gap analysis:")
    print("  python -m ultimate_pipeline.tools.run_offline_gaps_from_pair \\")
    print(f"    --manifest {manifest_path}")

    return return_code.value


def _run_selftest() -> int:
    """
    Windows-safe self-test (no pytest required).
    Run with: set UP_SELFTEST=1 && python -m ultimate_pipeline.tools.run_perception_pair
    """
    print("[SELFTEST] Testing _format_vram_text...")
    result_none = _format_vram_text(None)
    assert "VRAM unknown" in result_none, f"Expected 'VRAM unknown' in {result_none!r}"
    print(f"  _format_vram_text(None) = {result_none!r} [OK]")

    result_6 = _format_vram_text(6.0)
    assert result_6 == "6.0GB", f"Expected '6.0GB', got {result_6!r}"
    print(f"  _format_vram_text(6.0) = {result_6!r} [OK]")

    print("[SELFTEST] Testing compute_policy_decisions with vram_status='unknown'...")
    for profile in ["research", "gaming", "laptop", "low_end"]:
        policy = compute_policy_decisions(
            explicit_low_mem=False,
            explicit_profile=None,
            experiment_standard=True,
            max_performance=False,
            detected_profile=profile,
            detected_vram_gb=None,
            vram_status="unknown",
        )
        assert "policy_reason" in policy, f"Missing policy_reason for profile={profile}"
        assert "VRAM unknown" in policy["policy_reason"], f"Missing 'VRAM unknown' for profile={profile}"
    print("  All profiles with vram_status='unknown' [OK]")

    print("[SELFTEST] All tests passed!")
    return 0


if __name__ == "__main__":
    if _env_bool("UP_SELFTEST"):
        sys.exit(_run_selftest())
    sys.exit(main())
