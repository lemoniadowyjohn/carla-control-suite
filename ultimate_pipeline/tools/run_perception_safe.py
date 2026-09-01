#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline.tools.run_perception_safe

Thesis-oriented safe perception capture wrapper.

- Supports cooked towns (--town) OR XODR (--xodr-in).
- Optionally avoids map travel via --use-current-world (critical for Grid0821/Grid0828 stability).
- Uses record_route_fixed (correct CARLA 0.9.16 sync tick semantics).
- Writes BOTH:
  - carla_status.json (high-level)
  - recording_summary.json (thesis proxy metrics + frame counts)
- Validates that frames were actually produced (no more silent 0-frame "success").

Env toggles:
- UP_DISABLE_CARLA=1 : write artifacts and SKIP (keeps tests deterministic)
- UP_MIN_FRAMES : minimum frames required to declare PASS (default 8; bounded evidence accepted)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
import traceback
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ultimate_pipeline.config.thesis_contract import (
    build_visual_qa_contract,
    classify_single_perception_result,
)
from ultimate_pipeline.config.settings import (
    LOCAL_PERCEPTION_MAX_NPCS,
    MAX_ACTIVE_CAMERAS,
    SETTINGS,
)
from ultimate_pipeline.carla_tools.reload_ready_for_sensors import (
    _reload_ready_for_sensors,
    _wait_for_streaming_port,
)
from ultimate_pipeline.carla_tools.carla_readiness import (
    wait_for_carla_ready_bounded,
)
from ultimate_pipeline.core.carla_utils import autostart_carla_if_needed
from ultimate_pipeline.quality.check_elevation_missing_and_cliffs import (
    check_elevation_missing_and_cliffs,
)
from ultimate_pipeline.sensors.transform_conventions import (
    camera_attachment_pose_from_cTv,
)
from ultimate_pipeline.tools.perception_artifacts import render_lidar_bev
from ultimate_pipeline.carla_tools.runtime_enrichments import (
    spawn_runtime_enrichments,
    destroy_runtime_enrichments,
    capture_qa_bundle,
    parse_type_filter,
)
from ultimate_pipeline.carla_tools.thesis_sensor_rig import ThesisSensorRig
import socket


# =============================================================================
# Grid Perception Robustness Constants (per GRID_PERCEPTION_RCA.md)
# =============================================================================
# Bounded frame-wait gate: max ticks/time to wait for first callback frame
FRAME_WAIT_TICKS = 10
FRAME_WAIT_TIMEOUT_S = 15.0

# Known unstable maps that should not be loaded via load_world() by default.
# These require operator pre-load and --use-current-world.
KNOWN_UNSTABLE_MAPS = frozenset({"grid0821", "grid0828"})

# Exit codes per RCA
EXIT_CODE_SUCCESS = 0
EXIT_CODE_GENERIC_FAILURE = 1
EXIT_CODE_CARLA_FAILURE = 2
EXIT_CODE_MAP_TRAVEL_RISK = 3
EXIT_CODE_INFRA_FAILURE = EXIT_CODE_CARLA_FAILURE


class _EarlyExit(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(str(code))
        self.code = int(code)


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return bool(default)
    return str(v).strip().lower() in ("1", "true", "yes", "on", "y")


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    if v is None:
        return int(default)
    try:
        return int(str(v).strip())
    except Exception:
        return int(default)


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    if v is None:
        return float(default)
    try:
        return float(str(v).strip())
    except Exception:
        return float(default)


def _repo_root_dir() -> Path:
    cwd = Path.cwd()
    for parent in (cwd, *cwd.parents):
        if (parent / "AGENT_SYNC.md").is_file():
            return parent

    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "AGENT_SYNC.md").is_file():
            return parent
    return here.parents[2]


def _portable_path_for_metadata(
    path_value: Any, *, repo_root: Optional[Path] = None
) -> str:
    text = str(path_value or "").strip()
    if not text:
        return ""
    p = Path(text)
    if not p.is_absolute():
        return p.as_posix()

    bases: List[Path] = []
    if repo_root is not None:
        bases.append(repo_root)
    try:
        bases.append(Path.cwd())
    except Exception:
        pass

    for base in bases:
        try:
            rel = p.relative_to(base)
            return rel.as_posix()
        except Exception:
            pass
        try:
            rel_text = os.path.relpath(str(p), str(base))
            if rel_text and (not rel_text.startswith("..")):
                return Path(rel_text).as_posix()
        except Exception:
            pass
    return p.as_posix()


def _resolve_output_dir(path_arg: Path) -> Tuple[Path, Path]:
    repo_root = _repo_root_dir()
    requested = Path(path_arg).expanduser()
    if requested.is_absolute():
        out_dir = requested
    else:
        out_dir = repo_root / requested
    return out_dir, repo_root


def _resolve_visual_qa_gate_path(
    *,
    explicit_path: Optional[Path],
    xodr_in: Optional[Path],
    out_dir: Path,
    repo_root: Path,
) -> Optional[Path]:
    if explicit_path is not None:
        candidate = Path(explicit_path).expanduser()
        return candidate if candidate.is_absolute() else repo_root / candidate

    env_path = os.environ.get("UP_CARLA_VISUAL_GATE_REPORT", "").strip()
    if env_path:
        candidate = Path(env_path).expanduser()
        return candidate if candidate.is_absolute() else repo_root / candidate

    candidates: List[Path] = [out_dir / "carla_visual_smoke_gate.json"]
    if xodr_in is not None:
        xodr_path = Path(xodr_in).expanduser()
        if not xodr_path.is_absolute():
            xodr_path = repo_root / xodr_path
        candidates.extend(
            [
                xodr_path.parent / "carla_visual_smoke_gate.json",
                xodr_path.parent / "final_visual_smoke" / "carla_visual_smoke_gate.json",
                xodr_path.parent / "carla_visual_smoke" / "carla_visual_smoke_gate.json",
            ]
        )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _load_visual_qa_gate_status(
    *,
    gate_path: Optional[Path],
    required: bool,
    repo_root: Path,
) -> Dict[str, Any]:
    status: Dict[str, Any] = {
        "required": bool(required),
        "path": _portable_path_for_metadata(gate_path, repo_root=repo_root)
        if gate_path is not None
        else "",
        "found": False,
        "ok": False,
        "reason": "carla_visual_smoke_gate_missing",
        "CARLA_VISUAL_READY": "no",
        "PERCEPTION_EVIDENCE_ALLOWED": False,
    }
    if gate_path is None or not Path(gate_path).exists():
        return status
    try:
        payload = json.loads(Path(gate_path).read_text(encoding="utf-8"))
    except Exception as exc:
        status["found"] = True
        status["reason"] = f"invalid_visual_gate_json:{exc}"
        return status
    if not isinstance(payload, dict):
        status["found"] = True
        status["reason"] = "invalid_visual_gate_payload"
        return status
    try:
        from ultimate_pipeline.tools.carla_visual_smoke_gate import (
            evaluate_visual_smoke_report,
        )

        evaluation = evaluate_visual_smoke_report(payload, require_files=False)
        ok = bool(evaluation.get("ok", False))
        status.update(
            {
                "found": True,
                "ok": ok,
                "reason": str(evaluation.get("reason") or ""),
                "CARLA_VISUAL_READY": "yes" if ok else "no",
                "PERCEPTION_EVIDENCE_ALLOWED": ok,
                "required_views": evaluation.get("required_views", []),
                "missing_views": evaluation.get("missing_views", []),
                "failed_views": evaluation.get("failed_views", []),
            }
        )
    except Exception as exc:
        status.update({"found": True, "reason": f"visual_gate_eval_failed:{exc}"})
    return status


# ============================================================================
# Map Registry Integration
# ============================================================================
from ultimate_pipeline.carla_tools.map_registry import (
    copy_latest_carla_log,
    get_load_world_candidates,
    get_map_type,
    map_names_match,
    normalize_map_name,
    resolve_available_load_world_targets,
    resolve_expected_names,
    safe_get_available_maps,
)


def _is_grid_map(town: str) -> bool:
    """Check if the requested town is a Grid map."""
    return str(town or "").strip().lower().startswith("grid08")


def _resolve_xodr_path_for_grid(town: str) -> Optional[Path]:
    """Resolve XODR path for Grid maps (only used if explicit XODR mode)."""
    # Check environment variable first
    env_path = os.environ.get("UP_MANUAL_XODR_GRID0828") or os.environ.get("UP_MANUAL_XODR")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
    return None


def _write_last_run_pointer(repo_root: Path, out_dir: Path) -> Path:
    pointer = repo_root / "ultimate_pipeline_out" / "_last_perception_run.txt"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(str(out_dir) + "\n", encoding="utf-8", newline="\n")
    return pointer


def _resolve_stream_port(port: int, streaming_port: Optional[int]) -> int:
    if streaming_port is not None:
        try:
            return int(streaming_port)
        except Exception:
            pass
    return int(port) + 1


def _bounded_probe_timeout_s(env_name: str, default_s: float) -> float:
    return max(0.1, min(30.0, _env_float(env_name, float(default_s))))


def _wait_for_port_open(
    host: str,
    port: int,
    *,
    wait_s: float,
    probe_timeout_s: float = 1.0,
    poll_interval_s: float = 1.0,
    required_successes: int = 1,
) -> bool:
    deadline = time.monotonic() + max(0.0, float(wait_s))
    required_successes = max(1, int(required_successes))
    consecutive_successes = 0
    while True:
        if _tcp_port_open(str(host), int(port), timeout_s=float(probe_timeout_s)):
            consecutive_successes += 1
            if consecutive_successes >= required_successes:
                return True
        else:
            consecutive_successes = 0
        if time.monotonic() >= deadline:
            return False
        remaining = max(0.05, deadline - time.monotonic())
        time.sleep(min(float(poll_interval_s), float(remaining)))


KNOWN_CAPTURE_FAILURE_REASONS = {
    "NO_FRAMES_RECEIVED",
    "LISTEN_FAILED",
    "SENSOR_SPAWN_FAILED",
    "FIRST_FRAME_TIMEOUT",
    "SENSOR_SPAWN_TIMEOUT",
    "sensor_spawn_timeout",
    "STREAMING_COLLAPSE_DURING_CAPTURE",
    "streaming_collapse_during_capture",
    "MAP_TRAVEL_RISK",
    "MAP_TRAVEL_RISK_GRID0821",
    "MAP_TRAVEL_RISK_GRID0828",
}

PRELAUNCH_CAPTURE_FAILURE_REASONS = frozenset({
    "WRONG_MAP_LOADED",
    "MAP_LOAD_FAILED",
    "MAP_NOT_AVAILABLE",
    "MAP_LOAD_ENGINE_FATAL",
    "MAP_LOAD_TIMEOUT",
    "MAP_LOAD_RPC_FAILED",
    "XODR_NOT_FOUND",
})


def _has_terminal_prelaunch_failure(
    *,
    status: Dict[str, Any],
    perception_status: Dict[str, Any],
) -> bool:
    if bool(perception_status.get("rig_attach_attempted", False)):
        return False
    reason = str(
        perception_status.get("failure_reason")
        or status.get("failure_reason")
        or ""
    ).strip().upper()
    if reason in PRELAUNCH_CAPTURE_FAILURE_REASONS:
        return True
    if reason == "ENGINE_FATAL" and bool(perception_status.get("map_probe_requested", False)):
        return True
    return bool(status.get("map_mismatch_detected", False))


LOW_MEMORY_CAMERA_CAP: Dict[str, int] = {"width": 640, "height": 480}
MAX_SPAWNED_SENSORS_PAYLOAD_CHARS = 4096
MAX_SPAWNED_SENSOR_NAMES = 128


def _compute_record_route_timeout_s(
    *,
    frames: int,
    fps: float,
    duration_s: Optional[float] = None,
    override_timeout_s: Optional[float] = None,
    env_timeout_s: Optional[float] = None,
) -> float:
    if override_timeout_s is not None:
        return max(5.0, float(override_timeout_s))
    if env_timeout_s is not None:
        return max(5.0, float(env_timeout_s))
    resolved_duration_s = float(duration_s) if duration_s is not None else (
        float(frames) / float(max(float(fps), 1.0))
    )
    return max(60.0, float(resolved_duration_s) * 4.0 + 30.0)


def _read_capture_status_payload(recording_dir: Path) -> Dict[str, Any]:
    return _read_json_if_dict(recording_dir / "capture_status.json")


def _known_capture_failure_reason(
    capture_status_payload: Optional[Dict[str, Any]],
) -> str:
    if not isinstance(capture_status_payload, dict):
        return ""
    status_text = str(capture_status_payload.get("status", "") or "").strip().upper()
    reason_text = str(capture_status_payload.get("failure_reason", "") or "").strip().upper()
    if status_text not in {"FAIL", "SKIP"}:
        return ""
    if reason_text == "SENSOR_SPAWN_TIMEOUT":
        return "sensor_spawn_timeout"
    if reason_text.startswith("MAP_TRAVEL_RISK_"):
        return reason_text
    if reason_text in KNOWN_CAPTURE_FAILURE_REASONS:
        return reason_text
    return ""


def _extract_map_travel_risk_reason(error_text: Any) -> str:
    match = re.search(r"MAP_TRAVEL_RISK_[A-Z0-9_]+", str(error_text or ""))
    return str(match.group(0)) if match else ""


def _maybe_wait_for_current_world_streaming(
    *,
    host: str,
    stream_port: int,
    route_use_current_world: bool,
    skip_stream_check: bool,
    perception_status: Dict[str, Any],
    wait_s: Optional[float] = None,
) -> Optional[bool]:
    if not bool(route_use_current_world) or bool(skip_stream_check):
        return None
    effective_wait_s = float(
        wait_s
        if wait_s is not None
        else _env_float("UP_THESIS_STREAMING_RECOVERY_WAIT_S", 30.0)
    )
    effective_wait_s = max(1.0, float(effective_wait_s))
    stream_ok = _wait_for_streaming_port(
        host=str(host),
        port=int(stream_port),
        wait_s=float(effective_wait_s),
        poll_interval_s=1.0,
    )
    if not stream_ok:
        warning = "streaming_port_not_ready_use_current_world"
        if warning not in perception_status.get("warnings", []):
            perception_status.setdefault("warnings", []).append(warning)
        print(
            f"[perception_safe] WARNING: streaming port {int(stream_port)} not ready "
            f"after {effective_wait_s:.0f}s in --use-current-world mode. "
            "Sensor callbacks may not fire. Set --skip-stream-check to suppress."
        )
        return False
    print(
        f"[perception_safe] Streaming port {int(stream_port)} confirmed ready "
        f"after current-world wait ({effective_wait_s:.0f}s budget)."
    )
    return True


def _manifest_gate_should_bypass_for_capture_failure(
    *,
    require_manifest_gate: bool,
    capture_status_payload: Optional[Dict[str, Any]],
    runtime_failure_hint: str = "",
) -> str:
    if not bool(require_manifest_gate):
        return ""
    if str(runtime_failure_hint or "").strip():
        return str(runtime_failure_hint)
    return _known_capture_failure_reason(capture_status_payload)


def _enforce_manifest_gate_for_capture(
    *,
    require_manifest_gate: bool,
    recording_dir: Path,
    out_dir: Path,
    manifest_sync: Optional[Dict[str, Any]],
    capture_status_payload: Optional[Dict[str, Any]],
    runtime_failure_hint: str = "",
) -> str:
    bypass_reason = _manifest_gate_should_bypass_for_capture_failure(
        require_manifest_gate=bool(require_manifest_gate),
        capture_status_payload=capture_status_payload,
        runtime_failure_hint=runtime_failure_hint,
    )
    if bypass_reason:
        return str(bypass_reason)
    if bool(require_manifest_gate):
        _assert_recorder_manifest_integrity(recording_dir, out_dir, manifest_sync)
    return ""


def _classify_record_route_failure(
    *,
    timed_out: bool,
    proc_returncode: int,
    outputs_present: bool,
    integrity_ok: bool,
    integrity_reason: str,
    first_measurement_ok: bool,
    frames_recorded: int,
    stdout_text: str,
    stderr_text: str,
    skip_stream_check: bool,
) -> str:
    stdout_lower = str(stdout_text or "").lower()
    stderr_lower = str(stderr_text or "").lower()
    no_callbacks_detected = (
        ("no_sensor_measurements" in stdout_lower)
        or ("no_sensor_measurements" in stderr_lower)
        or ("no_first_measurement" in stdout_lower)
        or ("no_first_measurement" in stderr_lower)
    )
    first_measurement_callbacks_missing = (
        ("first_measurement_no_callbacks" in stdout_lower)
        or ("first_measurement_no_callbacks" in stderr_lower)
    )
    sensor_spawn_timeout_detected = (
        ("sensor_spawn_timeout" in stdout_lower)
        or ("sensor_spawn_timeout" in stderr_lower)
        or ("thesis_rig_spawn_timeout" in stdout_lower)
        or ("thesis_rig_spawn_timeout" in stderr_lower)
        or ("spawn_timeout" in stdout_lower)
        or ("spawn_timeout" in stderr_lower)
    )
    first_frame_timeout_detected = (
        ("first_frame_timeout" in stdout_lower)
        or ("first_frame_timeout" in stderr_lower)
        or ("first sample timeout" in stdout_lower)
        or ("first sample timeout" in stderr_lower)
    )
    sensor_spawn_failed = (
        ("sensor_spawn_failed" in stdout_lower)
        or ("sensor_spawn_failed" in stderr_lower)
        or
        ("sensor_spawn_missing_required_modalities" in stdout_lower)
        or ("sensor_spawn_missing_required_modalities" in stderr_lower)
        or ("ego_spawn_failed_or_timeout" in stdout_lower)
        or ("ego_spawn_failed_or_timeout" in stderr_lower)
    )
    streaming_refusal_detected = (
        ("streaming client: connection failed" in stdout_lower)
        or ("streaming_unavailable" in stdout_lower)
        or ("streaming_unavailable" in stderr_lower)
    )
    streaming_collapse_during_capture = (
        ("streaming_collapse_during_capture" in stdout_lower)
        or ("streaming_collapse_during_capture" in stderr_lower)
        or ("pre_spawn_stream_unavailable" in stdout_lower)
        or ("pre_spawn_stream_unavailable" in stderr_lower)
    )
    if streaming_collapse_during_capture:
        return "streaming_collapse_during_capture"
    if sensor_spawn_timeout_detected:
        return "sensor_spawn_timeout"
    if first_frame_timeout_detected:
        return "FIRST_FRAME_TIMEOUT"
    if sensor_spawn_failed:
        return "sensor_spawn_failed"
    if first_measurement_callbacks_missing:
        return "no_callbacks"
    if no_callbacks_detected and int(proc_returncode) != 0:
        return "no_callbacks" if bool(skip_stream_check) else "streaming_unavailable"
    if streaming_refusal_detected and int(proc_returncode) != 0 and (not bool(skip_stream_check)):
        return "streaming_unavailable"
    if timed_out and bool(skip_stream_check) and (not bool(outputs_present)):
        return "no_callbacks"
    if timed_out:
        return "record_route_timeout"
    if int(proc_returncode) != 0 and not outputs_present:
        return "record_route_nonzero"
    if not integrity_ok:
        return str(integrity_reason or "")
    if not first_measurement_ok:
        return "first_measurement_missing"
    if frames_recorded == 0:
        return "no_frames"
    return ""


def _derive_sync_settings_evidence(
    *,
    capture_summary: Dict[str, Any],
    run_info_payload: Dict[str, Any],
    recorder_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    applied_settings = capture_summary.get("world_settings_applied")
    if not isinstance(applied_settings, dict):
        applied_settings = {
            "synchronous_mode": bool(
                run_info_payload.get(
                    "synchronous_mode", recorder_cfg.get("synchronous", False)
                )
            ),
            "fixed_delta_seconds": float(
                run_info_payload.get(
                    "fixed_delta_seconds", recorder_cfg.get("fixed_delta_seconds", 0.0)
                )
                or 0.0
            ),
        }
    sync_mode = bool(
        applied_settings.get(
            "synchronous_mode",
            run_info_payload.get(
                "synchronous_mode", recorder_cfg.get("synchronous", False)
            ),
        )
    )
    fixed_delta_seconds = float(
        applied_settings.get(
            "fixed_delta_seconds",
            run_info_payload.get(
                "fixed_delta_seconds", recorder_cfg.get("fixed_delta_seconds", 0.0)
            ),
        )
        or 0.0
    )
    settings_applied_before_tick = bool(
        capture_summary.get(
            "settings_applied_before_tick",
            run_info_payload.get("settings_applied_before_tick", False),
        )
    )
    return {
        "applied_settings": {
            "synchronous_mode": bool(sync_mode),
            "fixed_delta_seconds": float(fixed_delta_seconds),
        },
        "synchronous_mode": bool(sync_mode),
        "fixed_delta_seconds": float(fixed_delta_seconds),
        "settings_applied_before_tick": bool(settings_applied_before_tick),
    }


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True)
    path.write_text(
        text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8", newline="\n"
    )


def _refresh_thesis_contract_artifacts(
    out_dir: Path,
    status: Dict[str, Any],
    pair_manifest: Dict[str, Any],
    perception_status: Dict[str, Any],
) -> None:
    inputs = pair_manifest.get("inputs", {}) if isinstance(pair_manifest, dict) else {}
    if not isinstance(inputs, dict):
        inputs = {}

    frames_recorded = int(perception_status.get("frames_recorded", 0) or 0)
    evidence_written = bool(
        perception_status.get("evidence_pack_ok", False)
        or perception_status.get("recorder_manifest_written", False)
        or perception_status.get("recorder_manifest_synthesized", False)
    )
    classification = classify_single_perception_result(
        success=perception_status.get("ok", False),
        frames_recorded=frames_recorded,
        failure_reason=perception_status.get("failure_reason")
        or status.get("failure_reason"),
        manual_town=inputs.get("manual_town"),
        auto_town=inputs.get("town"),
        expected_map_name=status.get("expected_map_name") or inputs.get("expected_map_name"),
        xodr_in=inputs.get("xodr_in"),
        first_frame_received=perception_status.get("first_measurement_ok"),
        evidence_written=evidence_written,
        sensors_attached=perception_status.get("sensors_attached"),
    )
    perception_status["result_class"] = classification.value
    perception_status["result_class_reason"] = classification.reason
    perception_status["result_scope"] = "single_arm_capture"
    perception_status["capture_context"] = {
        "manual_town": str(inputs.get("manual_town", "") or ""),
        "auto_town": str(inputs.get("town", "") or ""),
        "expected_map_name": str(
            status.get("expected_map_name") or inputs.get("expected_map_name") or ""
        ),
        "xodr_in": str(inputs.get("xodr_in", "") or ""),
    }

    produced_artifacts = perception_status.get("produced_artifacts")
    if not isinstance(produced_artifacts, dict):
        produced_artifacts = {}
        perception_status["produced_artifacts"] = produced_artifacts

    actual_map_name = str(status.get("actual_map_name") or "")
    world_loaded = bool(actual_map_name) or bool(perception_status.get("map_probe_ok") is True)
    if bool(perception_status.get("map_probe_requested", False)):
        correct_world_identity = bool(perception_status.get("map_probe_ok") is True)
    else:
        correct_world_identity = bool(world_loaded and not status.get("map_mismatch_detected", False))
    ego_spawned = bool(
        perception_status.get("rig_attach_attempted", False)
        or produced_artifacts.get("ego_spawn_png", False)
        or frames_recorded > 0
    )
    thesis_sensor_attached = perception_status.get("sensors_attached") is True
    first_frame_received = bool(
        perception_status.get("first_measurement_ok", False) or frames_recorded > 0
    )
    runtime_verified = bool(
        world_loaded
        or ego_spawned
        or thesis_sensor_attached
        or first_frame_received
    )
    upstream_visual_gate = perception_status.get("upstream_visual_qa_gate", {})
    if not isinstance(upstream_visual_gate, dict):
        upstream_visual_gate = {}
    visual_qa_contract = build_visual_qa_contract(
        world_loaded=world_loaded,
        correct_world_identity=correct_world_identity,
        ego_spawned=ego_spawned,
        thesis_sensor_attached=thesis_sensor_attached,
        first_frame_received=first_frame_received,
        evidence_written=evidence_written,
        runtime_verified=runtime_verified,
        visual_smoke_gate_ok=upstream_visual_gate.get("ok"),
        visual_smoke_gate_required=upstream_visual_gate.get("required", False),
    )
    visual_qa_contract["upstream_visual_qa_gate"] = dict(upstream_visual_gate)
    perception_status["visual_qa_contract"] = visual_qa_contract
    _write_json(out_dir / "visual_qa_contract.json", visual_qa_contract)
    produced_artifacts["visual_qa_contract_json"] = True
    status["perception_result_class"] = classification.value
    status["visual_qa_contract_status"] = str(visual_qa_contract.get("status", ""))


def _write_status_bundle(
    out_dir: Path,
    status: Dict[str, Any],
    pair_manifest: Dict[str, Any],
    perception_status: Dict[str, Any],
) -> None:
    _refresh_thesis_contract_artifacts(out_dir, status, pair_manifest, perception_status)
    _write_json(out_dir / "carla_status.json", status)
    _write_json(out_dir / "pair_manifest.json", pair_manifest)
    _write_json(out_dir / "perception_status.json", perception_status)


def _write_timeout_diagnostics(
    out_dir: Path,
    payload: Dict[str, Any],
) -> Path:
    path = out_dir / "timeout_diagnostics.json"
    _write_json(path, payload)
    return path


def _acquire_run_lock(out_dir: Path) -> Tuple[bool, Path]:
    lock_path = out_dir / ".run_perception_safe.lock"
    try:
        fd = os.open(
            str(lock_path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
        with os.fdopen(fd, "w", encoding="utf-8", errors="replace") as f:
            f.write(
                json.dumps(
                    {
                        "pid": int(os.getpid()),
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    },
                    ensure_ascii=True,
                )
            )
        return True, lock_path
    except FileExistsError:
        return False, lock_path


def _release_run_lock(lock_path: Optional[Path]) -> None:
    if lock_path is None:
        return
    try:
        if lock_path.exists():
            lock_path.unlink()
    except Exception:
        pass


def _map_matches_requested(map_name: str, requested_town: str) -> bool:
    """Check if map_name matches requested_town using registry normalization."""
    # Delegate to map_registry for consistent behavior
    return map_names_match(str(map_name or ""), str(requested_town or ""))


def _is_carla_timeout_error(exc: Exception) -> bool:
    if not isinstance(exc, RuntimeError):
        return False
    message = str(exc).lower()
    return ("time-out" in message) or ("timeout" in message) or ("timed out" in message)


def _safe_load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _looks_like_engine_crash_returncode(returncode: int) -> bool:
    rc = int(returncode)
    crash_codes = {
        -1073741819,  # 0xC0000005 access violation (signed)
        -1073740791,  # 0xC0000409 stack buffer overrun (signed)
        -1073741571,  # 0xC00000FD stack overflow (signed)
        3221225477,  # 0xC0000005 access violation (unsigned)
        3221226505,  # 0xC0000409 stack buffer overrun (unsigned)
        3221225725,  # 0xC00000FD stack overflow (unsigned)
    }
    return (rc < 0) or (rc in crash_codes)


def _classify_map_probe_outcome(
    *,
    timed_out: bool,
    returncode: int,
    probe_payload: Dict[str, Any],
) -> Tuple[str, str]:
    payload = probe_payload if isinstance(probe_payload, dict) else {}
    if bool(timed_out):
        return "ENGINE_FATAL", "map_probe_timeout"
    if not payload:
        return "ENGINE_FATAL", "map_probe_result_missing"

    status = str(payload.get("status", "") or "").strip().upper()
    ok_flag = payload.get("ok", None)
    mismatch = bool(payload.get("mismatch", False))
    probe_reason = str(payload.get("failure_reason", "") or "").strip()
    probe_detail = str(
        payload.get("failure_detail", "") or payload.get("exception_text", "") or ""
    ).strip()
    if status == "PASS" or ok_flag is True:
        return "", ""
    if mismatch:
        mismatch_detail = probe_detail or (
            f"expected '{payload.get('expected_map_name', '')}', "
            f"got '{payload.get('actual_map_name', '')}'"
        )
        return "WRONG_MAP_LOADED", mismatch_detail
    if probe_reason == "WRONG_MAP_LOADED":
        return "WRONG_MAP_LOADED", (
            probe_detail
            or str(payload.get("actual_map_name", "") or payload.get("map_name", "") or "")
            or "map_probe_wrong_map"
        )
    if probe_reason:
        detail = (
            f"map_probe:{probe_reason}:{probe_detail}"
            if probe_detail
            else f"map_probe:{probe_reason}"
        )
        return "ENGINE_FATAL", detail
    if _looks_like_engine_crash_returncode(int(returncode)):
        return "ENGINE_FATAL", f"map_probe_crash_returncode:{int(returncode)}"
    if int(returncode) != 0:
        return "ENGINE_FATAL", f"map_probe_nonzero_returncode:{int(returncode)}"
    return "", ""


def _run_map_only_probe_subprocess(
    *,
    out_dir: Path,
    host: str,
    port: int,
    town: str,
    expected_map_name: str,
    use_current_world: bool,
    timeout_s: float,
) -> Dict[str, Any]:
    probe_dir = out_dir / "map_probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = probe_dir / "map_probe_stdout.txt"
    stderr_path = probe_dir / "map_probe_stderr.txt"
    probe_result_path = probe_dir / "probe_result.json"
    cmd = [
        sys.executable,
        "-m",
        "ultimate_pipeline.tools.map_only_probe",
        "--host",
        str(host),
        "--port",
        str(int(port)),
        "--town",
        str(town),
        "--out",
        str(probe_dir),
        "--timeout-s",
        str(float(timeout_s)),
    ]
    if str(expected_map_name or "").strip():
        cmd += ["--expected-map-name", str(expected_map_name)]
    if bool(use_current_world):
        cmd.append("--use-current-world")

    timed_out = False
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(timeout_s),
            env=dict(os.environ),
        )
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        proc = subprocess.CompletedProcess(
            cmd,
            124,
            str(getattr(exc, "stdout", "") or ""),
            str(getattr(exc, "stderr", "") or ""),
        )

    stdout_text = str(proc.stdout or "")
    stderr_text = str(proc.stderr or "")
    stdout_path.write_text(stdout_text, encoding="utf-8", errors="replace")
    stderr_path.write_text(stderr_text, encoding="utf-8", errors="replace")

    probe_payload = _safe_load_json(probe_result_path)
    probe_expected_map_name = str(
        probe_payload.get("expected_map_name", "") or expected_map_name or ""
    ).strip()
    probe_actual_map_name = str(
        probe_payload.get("actual_map_name", "") or probe_payload.get("map_name", "") or ""
    ).strip()
    probe_mismatch_detected = bool(
        probe_payload.get("mismatch", False)
        or str(probe_payload.get("failure_reason", "") or "").strip().upper()
        == "WRONG_MAP_LOADED"
    )
    root_probe_result_path = out_dir / "probe_result.json"
    if probe_result_path.is_file():
        try:
            shutil.copy2(probe_result_path, root_probe_result_path)
        except Exception:
            root_probe_result_path = probe_result_path
    else:
        root_probe_result_path = probe_result_path
    failure_reason, failure_detail = _classify_map_probe_outcome(
        timed_out=bool(timed_out),
        returncode=int(proc.returncode),
        probe_payload=probe_payload,
    )
    return {
        "requested": True,
        "ok": not bool(failure_reason),
        "expected_map_name": probe_expected_map_name,
        "actual_map_name": probe_actual_map_name,
        "map_mismatch_detected": bool(probe_mismatch_detected),
        "failure_reason": str(failure_reason),
        "failure_detail": str(failure_detail),
        "returncode": int(proc.returncode),
        "timed_out": bool(timed_out),
        "timeout_s": float(timeout_s),
        "elapsed_s": round(time.monotonic() - t0, 3),
        "probe_result_path": (
            str(root_probe_result_path)
            if root_probe_result_path.is_file()
            else (
                str(probe_result_path)
                if probe_result_path.is_file()
                else ""
            )
        ),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
        "raw_probe_failure_reason": str(probe_payload.get("failure_reason", "") or ""),
        "raw_probe_status": str(probe_payload.get("status", "") or ""),
    }


def _capture_map_identity(world: Any) -> Tuple[str, Dict[str, Any]]:
    map_name = "UNKNOWN"
    world_settings_payload: Dict[str, Any] = {}
    try:
        carla_map = world.get_map()
        map_name = str(getattr(carla_map, "name", "") or "UNKNOWN")
    except Exception:
        map_name = "UNKNOWN"
    try:
        settings = world.get_settings()
        world_settings_payload = {
            "synchronous_mode": bool(getattr(settings, "synchronous_mode", False)),
            "fixed_delta_seconds": float(
                getattr(settings, "fixed_delta_seconds", 0.0) or 0.0
            ),
        }
    except Exception:
        world_settings_payload = {}
    return map_name, world_settings_payload


def _tcp_port_open(host: str, port: int, timeout_s: float = 1.0) -> bool:
    """Check if a TCP port is reachable (best-effort)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(float(timeout_s))
        result = sock.connect_ex((str(host), int(port)))
        sock.close()
        return result == 0
    except Exception:
        return False


def _restart_carla_and_wait(
    carla_exe: str,
    *,
    rpc_port: int = 2000,
    stream_port: int = 2001,
    startup_wait_s: float = 20.0,
    default_map_name: str = "",
) -> bool:
    carla_exe = str(carla_exe or "").strip()
    if not carla_exe:
        print("[run_perception_safe] WARNING: CARLA restart requested but no executable configured.", flush=True)
        return False
    try:
        import psutil  # type: ignore
    except Exception:
        psutil = None
    if psutil is not None:
        try:
            for proc in psutil.process_iter(["name"]):
                name = str(proc.info.get("name") or "")
                if "CarlaUE4" in name:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        except Exception:
            pass
    else:
        for image_name in ("CarlaUE4-Win64-Shipping.exe", "CarlaUE4.exe"):
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", image_name],
                    capture_output=True,
                    check=False,
                )
            except Exception:
                pass
    time.sleep(3.0)
    cmd = [
        carla_exe,
        f"-carla-rpc-port={int(rpc_port)}",
        f"-carla-streaming-port={int(stream_port)}",
        "-RenderOffScreen",
        "-quality-level=Low",
    ]
    if str(default_map_name or "").strip():
        cmd.append(str(default_map_name).strip())
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        print(f"[run_perception_safe] WARNING: failed to restart CARLA: {exc!r}", flush=True)
        return False
    deadline = time.time() + max(5.0, float(startup_wait_s))
    while time.time() < deadline:
        if _tcp_port_open("localhost", int(rpc_port), timeout_s=1.0) and _tcp_port_open(
            "localhost",
            int(stream_port),
            timeout_s=1.0,
        ):
            return True
        time.sleep(1.0)
    return False


def _maybe_run_preload_map_script(
    *,
    out_dir: Path,
    perception_status: Dict[str, Any],
) -> Dict[str, Any]:
    script_path = str(os.environ.get("UP_PRELOAD_MAP_SCRIPT", "") or "").strip()
    if not script_path:
        return {"enabled": False}
    preload_payload: Dict[str, Any] = {
        "enabled": True,
        "script_path": script_path,
        "ok": False,
    }
    try:
        proc = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=float(_env_float("UP_PRELOAD_MAP_TIMEOUT_S", 180.0)),
            env=dict(os.environ),
        )
        stdout_path = out_dir / "preload_map_stdout.txt"
        stderr_path = out_dir / "preload_map_stderr.txt"
        stdout_path.write_text(proc.stdout or "", encoding="utf-8", errors="replace")
        stderr_path.write_text(proc.stderr or "", encoding="utf-8", errors="replace")
        preload_payload.update(
            {
                "ok": proc.returncode == 0,
                "returncode": int(proc.returncode),
                "stdout_path": str(stdout_path),
                "stderr_path": str(stderr_path),
            }
        )
        if proc.returncode != 0:
            warning = f"preload_map_script_failed:{proc.returncode}"
            if warning not in perception_status.get("warnings", []):
                perception_status.setdefault("warnings", []).append(warning)
    except Exception as exc:
        preload_payload["error"] = repr(exc)
        warning = f"preload_map_script_error:{exc.__class__.__name__}"
        if warning not in perception_status.get("warnings", []):
            perception_status.setdefault("warnings", []).append(warning)
    return preload_payload


def _maybe_restart_carla_before_run(
    *,
    args: Any,
    out_dir: Path,
    perception_status: Dict[str, Any],
    pair_manifest: Dict[str, Any],
    route_use_current_world: bool,
    stream_port: int,
) -> None:
    if not _env_bool("UP_RESTART_CARLA_BEFORE_RUN", False):
        return
    carla_exe = str(os.environ.get("UP_CARLA_EXE") or SETTINGS.CARLA_EXE or "").strip()
    requested_town = str(args.town or "").strip()
    startup_wait_s = float(_env_float("UP_RESTART_CARLA_WAIT_S", 20.0))
    default_map_name = "" if bool(route_use_current_world) else requested_town
    print(
        f"[run_perception_safe] Restarting CARLA before capture (rpc={int(args.port)}, stream={int(stream_port)})",
        flush=True,
    )
    restarted = _restart_carla_and_wait(
        carla_exe,
        rpc_port=int(args.port),
        stream_port=int(stream_port),
        startup_wait_s=float(startup_wait_s),
        default_map_name=default_map_name,
    )
    restart_payload: Dict[str, Any] = {
        "enabled": True,
        "ok": bool(restarted),
        "carla_exe": carla_exe,
        "rpc_port": int(args.port),
        "stream_port": int(stream_port),
        "route_use_current_world": bool(route_use_current_world),
    }
    if bool(route_use_current_world):
        preload_payload = _maybe_run_preload_map_script(
            out_dir=out_dir,
            perception_status=perception_status,
        )
        restart_payload["preload_map"] = preload_payload
        if not preload_payload.get("enabled", False):
            warning = (
                "carla_restarted_without_preload_map_script:"
                "reload cooked map manually before --use-current-world capture"
            )
            print(f"[run_perception_safe] WARNING: {warning}", flush=True)
            if warning not in perception_status.get("warnings", []):
                perception_status.setdefault("warnings", []).append(warning)
    pair_manifest.setdefault("status", {})["carla_restart_before_run"] = restart_payload
    perception_status["carla_restart_before_run"] = restart_payload
    if not restarted:
        raise RuntimeError(
            f"CARLA_RESTART_TIMEOUT: rpc={int(args.port)} stream={int(stream_port)}"
        )


def _is_known_unstable_map(town: str) -> bool:
    """Check if the requested town is a known-unstable map (per RCA)."""
    normalized = normalize_map_name(str(town or ""))
    return normalized in KNOWN_UNSTABLE_MAPS


def _apply_unstable_map_env_defaults(town: str) -> bool:
    """Apply runtime defaults for known-unstable cooked maps."""
    normalized = normalize_map_name(str(town or ""))
    if normalized not in KNOWN_UNSTABLE_MAPS:
        return False
    # Avoid explicit sensor destroy on unstable cooked maps. CARLA 0.9.16 can
    # crash in ASensor::EndPlay during teardown even after stop() succeeds.
    os.environ.setdefault("UP_SKIP_DESTROY", "1")
    # Grid maps (Grid0821/Grid0828) do not reliably expose the secondary
    # streaming port (2001) via load_world(). Sensor listeners register
    # directly on the RPC channel instead — skip the stream-port liveness
    # check so capture can proceed.  Override with UP_SKIP_STREAM_CHECK=0
    # to re-enable the check when the streaming port IS confirmed open.
    if os.environ.get("UP_SKIP_STREAM_CHECK", "").strip() not in ("0", "false", "no"):
        os.environ["UP_SKIP_STREAM_CHECK"] = "1"
    return True


def _handle_outer_stream_gate(
    *,
    args: Any,
    out_dir: Path,
    status: Dict[str, Any],
    pair_manifest: Dict[str, Any],
    perception_status: Dict[str, Any],
    stream_reachable: bool,
    stream_optional: bool,
    stream_port: int,
) -> Optional[str]:
    if bool(getattr(args, "skip_stream_check", False)) or bool(stream_reachable):
        return None
    if bool(stream_optional):
        perception_status.setdefault("warnings", []).append(
            f"stream_port_not_ready_optional:{int(stream_port)}"
        )
        pair_manifest.setdefault("status", {})
        pair_manifest["status"]["streaming_port"] = int(stream_port)
        pair_manifest["status"]["streaming_status"] = "optional_unreachable"
        pair_manifest["status"]["streaming_error"] = (
            f"carla_streaming_unreachable:{args.host}:{int(stream_port)}"
        )
        print(
            f"[perception_safe] WARNING: streaming port {int(stream_port)} not ready "
            "but stream_optional=True; continuing (sensor callbacks may not fire)"
        )
        return None
    failure_reason = f"carla_streaming_unreachable:{args.host}:{int(stream_port)}"
    status["carla_failed"] = True
    status["failure_reason"] = failure_reason
    perception_status["ok"] = False
    perception_status["failure_reason"] = failure_reason
    pair_manifest.setdefault("status", {})
    pair_manifest["status"]["streaming_port"] = int(stream_port)
    pair_manifest["status"]["streaming_status"] = "unreachable"
    pair_manifest["status"]["streaming_error"] = failure_reason
    _write_status_bundle(out_dir, status, pair_manifest, perception_status)
    _write_json(
        out_dir / "recording_summary.json",
        {
            "status": "FAIL",
            "failure_reason": failure_reason,
            "frames_recorded": 0,
            "frames_requested": int(args.frames),
            "fps": float(args.fps),
            "host": args.host,
            "port": int(args.port),
            "camera": "",
            "image_size": {"width": 0, "height": 0},
            "brightness_mean": 0.0,
            "brightness_std": 0.0,
            "laplacian_variance": 0.0,
            "screenshot_paths": [],
        },
    )
    return failure_reason


def _capture_ego_spawn_location(ego_vehicle: Any) -> Dict[str, float]:
    """Capture ego vehicle spawn location for diagnostics."""
    try:
        loc = ego_vehicle.get_location()
        return {
            "x": float(loc.x),
            "y": float(loc.y),
            "z": float(loc.z),
        }
    except Exception:
        return {"x": 0.0, "y": 0.0, "z": 0.0}


def _capture_world_sync_settings(world: Any) -> Dict[str, Any]:
    """Capture world sync settings including no_rendering_mode for diagnostics."""
    try:
        settings = world.get_settings()
        return {
            "synchronous_mode": bool(getattr(settings, "synchronous_mode", False)),
            "fixed_delta_seconds": float(
                getattr(settings, "fixed_delta_seconds", 0.0) or 0.0
            ),
            "no_rendering_mode": bool(getattr(settings, "no_rendering_mode", False)),
        }
    except Exception:
        return {
            "synchronous_mode": False,
            "fixed_delta_seconds": 0.0,
            "no_rendering_mode": False,
        }


def _write_perception_diagnostics(
    out_dir: Path,
    *,
    failure_reason: str,
    failure_detail: str,
    sensor_spawn_status: Dict[str, Any],
    listen_errors: List[str],
    per_sensor_frame_counts: Dict[str, int],
    tick_progression: Dict[str, Any],
    map_state: Dict[str, Any],
    sync_settings: Dict[str, Any],
    ego_spawn: Dict[str, float],
    streaming_port_reachable: bool,
    carla_log_path: str,
    settle_ticks_used: int = 0,
) -> Path:
    """
    Write perception_diagnostics.json with all required fields per RCA.

    This is the structured diagnostics artifact for thesis defensibility.
    """
    payload = {
        "schema_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "failure_reason": str(failure_reason),
        "failure_detail": str(failure_detail),
        "sensor_spawn_status": dict(sensor_spawn_status),
        "listen_errors": list(listen_errors),
        "per_sensor_frame_counts": dict(per_sensor_frame_counts),
        "tick_progression": dict(tick_progression),
        "map_state": dict(map_state),
        "sync_settings": dict(sync_settings),
        "ego_spawn": dict(ego_spawn),
        "streaming_port_reachable": bool(streaming_port_reachable),
        "carla_log_path": str(carla_log_path),
        "settle_ticks_used": int(settle_ticks_used),
    }
    diagnostics_path = out_dir / "perception_diagnostics.json"
    _write_json(diagnostics_path, payload)
    return diagnostics_path


def _synthesize_minimal_recorder_manifest(
    out_dir: Path,
    *,
    failure_reason: str,
    expected_sensors: List[str],
    map_name: str = "UNKNOWN",
    world_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Synthesize a minimal recorder_manifest.json when capture fails.

    This ensures we never have a missing manifest, just an empty one with
    clear failure reason.
    """
    payload = {
        "schema_version": 1,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "closed_utc": datetime.now(timezone.utc).isoformat(),
        "manifest_source": "synthesized_on_failure",
        "error": str(failure_reason),
        "output_dir": str(out_dir),
        "counts": {
            "rgb_files": 0,
            "semseg_files": 0,
            "lidar_files": 0,
            "total_files": 0,
        },
        "sensors": [
            {"name": s, "kind": "unknown", "frame_count": 0, "spawned": False}
            for s in expected_sensors
        ],
        "per_sensor_counts": {s: {"frames": 0} for s in expected_sensors},
        "sensor_frame_counts": {s: 0 for s in expected_sensors},
        "carla_map_name": str(map_name),
        "carla_map_basename": str(map_name).split("/")[-1] if "/" in str(map_name) else str(map_name),
        "carla_world_settings": dict(world_settings or {}),
        "save_errors_tail": [],
    }
    manifest_path = out_dir / "recorder_manifest.json"
    _write_json(manifest_path, payload)
    return payload


def _provision_requested_town_map(
    *,
    client: Any,
    world: Any,
    requested_town: str,
    route_use_current_world: bool,
    pair_status: Dict[str, Any],
    xodr_path: Optional[Path] = None,
    host: str = "127.0.0.1",
    port: int = 2000,
) -> Tuple[Any, str, Dict[str, Any], bool]:
    """
    Provision the requested map using cooked or XODR loading.

    Uses map_registry for proper name normalization and type detection.
    Grid0828/Grid0821 are treated as cooked CARLA maps (load_world).
    """
    try:
        current_world = client.get_world()
        if current_world is not None:
            world = current_world
    except Exception:
        current_world = None
    map_name, world_settings_payload = _capture_map_identity(world)
    pair_status["carla_map_name"] = str(map_name)
    pair_status["carla_map_basename"] = str(map_name).split("/")[-1]
    pair_status["carla_world_settings"] = dict(world_settings_payload)

    map_load_timeout_s = max(
        60.0, float(os.environ.get("UP_CARLA_MAP_LOAD_TIMEOUT_S", "180.0"))
    )
    pair_status["map_load_timeout_s"] = float(map_load_timeout_s)
    pair_status.setdefault("map_load_applied", False)

    requested_town = str(requested_town or "").strip()
    xodr_requested = bool(xodr_path and xodr_path.exists())
    if route_use_current_world and not xodr_requested:
        return world, str(map_name), dict(world_settings_payload), bool(
            route_use_current_world
        )
    if not requested_town and not xodr_requested:
        return world, str(map_name), dict(world_settings_payload), bool(
            route_use_current_world
        )

    # Determine map type using registry
    if xodr_requested:
        map_type = "xodr"
        if not requested_town:
            # CARLA uses OpenDriveMap for generated OpenDRIVE worlds.
            requested_town = "OpenDriveMap"
    else:
        map_type = get_map_type(requested_town)
    if (
        map_type != "xodr"
        and _is_known_unstable_map(requested_town)
        and not bool(route_use_current_world)
    ):
        pair_status["map_load_applied"] = False
        pair_status["map_load_skipped_reason"] = f"MAP_TRAVEL_RISK_{requested_town.upper()}"
        raise RuntimeError(
            f"MAP_LOAD_FAILED: MAP_TRAVEL_RISK_{requested_town.upper()}: risky load_world travel is blocked by default. "
            f"Load {requested_town} manually and rerun with --use-current-world."
        )

    pair_status["map_type"] = map_type
    pair_status["requested_map_normalized"] = normalize_map_name(requested_town)

    # Check if current map already matches (using normalized comparison)
    if map_names_match(map_name, requested_town):
        route_use_current_world = True
        pair_status["map_load_applied"] = False
        pair_status["map_load_skipped_reason"] = "already_loaded"
        return world, str(map_name), dict(world_settings_payload), bool(
            route_use_current_world
        )

    pair_status["map_load_requested"] = requested_town
    try:
        try:
            client.set_timeout(float(map_load_timeout_s))
        except Exception:
            pass

        if map_type == "xodr" and xodr_path:
            # XODR loading (explicit path provided)
            print(f"[perception_safe] Loading map via XODR: {xodr_path}")
            from ultimate_pipeline.core.carla_opendrive_loader import (
                load_opendrive_world_from_file,
            )
            world = load_opendrive_world_from_file(
                client,
                xodr_path,
                timeout_s=float(map_load_timeout_s),
                retries=2,
                do_reload=True,
            )
            pair_status["xodr_loaded"] = True
            pair_status["xodr_path"] = str(xodr_path)
        else:
            # Cooked map loading (Grid0828, Grid0821, Towns, etc.)
            candidates = get_load_world_candidates(requested_town)
            pair_status["map_load_candidates"] = list(candidates)

            available_info = safe_get_available_maps(
                client,
                query_timeout_s=min(map_load_timeout_s, 30.0),
                restore_timeout_s=min(map_load_timeout_s, 30.0),
            )
            pair_status["available_maps_query_ok"] = bool(
                available_info.get("ok", False)
            )
            pair_status["available_maps_query_error"] = str(
                available_info.get("error", "") or ""
            )
            pair_status["available_maps_count"] = int(
                available_info.get("available_maps_count", 0) or 0
            )
            pair_status["available_maps_sample"] = list(
                available_info.get("available_maps_sample", []) or []
            )
            pair_status["available_maps_hash"] = str(
                available_info.get("available_maps_hash", "") or ""
            )

            resolved_targets = resolve_available_load_world_targets(
                requested_town,
                list(available_info.get("maps", []) or []),
            )
            selected_targets = list(resolved_targets.get("matched_targets", []) or [])
            pair_status["map_load_selected_candidates"] = list(selected_targets)
            if not selected_targets:
                raise RuntimeError(
                    "MAP_LOAD_FAILED: MAP_NOT_AVAILABLE: requested "
                    f"'{requested_town}' is not advertised by CARLA "
                    f"(available_maps_count={int(pair_status['available_maps_count'])})"
                )

            print(
                f"[perception_safe] Loading cooked map: {selected_targets}"
            )

            last_exc: Optional[Exception] = None
            loaded = False
            for candidate in selected_targets:
                try:
                    # safe_get_available_maps probes with a short timeout; restore full load window.
                    try:
                        client.set_timeout(float(map_load_timeout_s))
                    except Exception:
                        pass
                    world = _reload_ready_for_sensors(client, map_name=candidate, tm_port=8000)
                    loaded = True
                    break
                except Exception as e:
                    last_exc = e
                    print(f"[perception_safe] load_world failed for '{candidate}': {e}")
                    # Timeout handling keeps prior recovery behavior.
                    if _is_carla_timeout_error(e):
                        raise
                    if not _tcp_port_open(str(host), int(port), timeout_s=0.8):
                        raise RuntimeError(
                            "MAP_LOAD_FAILED: MAP_LOAD_ENGINE_FATAL: "
                            f"RPC unreachable after load_world('{candidate}')"
                        ) from e

            if not loaded:
                raise RuntimeError(
                    f"MAP_LOAD_FAILED: all candidates failed for '{requested_town}'. Last: {last_exc}"
                )

        route_use_current_world = True
        pair_status["map_load_applied"] = True
        map_name, world_settings_payload = _capture_map_identity(world)

        # Validate map identity using normalized comparison
        pair_status["actual_map_name_raw"] = str(map_name)
        pair_status["actual_map_name_normalized"] = normalize_map_name(map_name)

        if not map_names_match(map_name, requested_town):
            raise RuntimeError(
                f"MAP_LOAD_FAILED: requested '{requested_town}' "
                f"(normalized: '{normalize_map_name(requested_town)}'), "
                f"got '{map_name}' (normalized: '{normalize_map_name(map_name)}')"
            )
    except Exception as load_exc:
        if str(load_exc).startswith("MAP_LOAD_FAILED:"):
            raise
        recovered_world = None
        recovered_map_name = "UNKNOWN"
        try:
            recovered_world = client.get_world()
            recovered_map_name, _ = _capture_map_identity(recovered_world)
        except Exception:
            recovered_world = None
            recovered_map_name = "UNKNOWN"
        if _is_carla_timeout_error(load_exc):
            if _map_matches_requested(recovered_map_name, requested_town):
                world = recovered_world
                route_use_current_world = True
                pair_status["map_load_applied"] = True
                pair_status["map_load_warning"] = "load_world_timeout_but_world_matches"
                map_name, world_settings_payload = _capture_map_identity(world)
            else:
                avail_count: Optional[int] = None
                try:
                    avail_maps = client.get_available_maps()
                    if isinstance(avail_maps, list):
                        avail_count = int(len(avail_maps))
                except Exception:
                    avail_count = None
                avail_hint = (
                    ""
                    if avail_count is None
                    else f", available_maps_count={int(avail_count)}"
                )
                raise RuntimeError(
                    f"MAP_LOAD_FAILED: requested '{requested_town}', current '{recovered_map_name}', "
                    f"error='{load_exc}'{avail_hint}"
                )
        else:
            avail_count: Optional[int] = None
            try:
                avail_maps = client.get_available_maps()
                if isinstance(avail_maps, list):
                    avail_count = int(len(avail_maps))
            except Exception:
                avail_count = None
            avail_hint = (
                ""
                if avail_count is None
                else f", available_maps_count={int(avail_count)}"
            )
            raise RuntimeError(
                f"MAP_LOAD_FAILED: requested '{requested_town}', current '{recovered_map_name}', "
                f"error='{load_exc}'{avail_hint}"
            )
    finally:
        try:
            client.set_timeout(20.0)
        except Exception:
            pass

    pair_status["carla_map_name"] = str(map_name)
    pair_status["carla_map_basename"] = str(map_name).split("/")[-1]
    pair_status["carla_world_settings"] = dict(world_settings_payload)
    return world, str(map_name), dict(world_settings_payload), bool(
        route_use_current_world
    )


def _as_unique_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    out: List[str] = []
    seen: set = set()
    for item in value:
        name = str(item).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _apply_camera_claim_scope_status(
    perception_status: Dict[str, Any], forward_alignment: Optional[Dict[str, Any]]
) -> None:
    passing_names: List[str] = []
    failing_names: List[str] = []
    if isinstance(forward_alignment, dict):
        passing_names = _as_unique_str_list(
            forward_alignment.get("passing_camera_names")
        )
        failing_names = _as_unique_str_list(
            forward_alignment.get("failing_camera_names")
        )
    perception_status["passing_camera_names"] = passing_names
    perception_status["failing_camera_names"] = failing_names
    perception_status["camera_exclusion_policy"] = "exclude_failing"
    perception_status["excluded_camera_names"] = list(failing_names)
    perception_status["camera_claim_scope"] = (
        "front_rear_only" if len(failing_names) > 0 else "all_cameras"
    )


def _validate_calib_override_file(calib_override_path: str) -> str:
    path_text = str(calib_override_path or "").strip()
    if not path_text:
        return ""
    try:
        payload = json.loads(
            Path(path_text).read_text(encoding="utf-8", errors="replace")
        )
        if not isinstance(payload, dict):
            raise ValueError("calib override must be a JSON object keyed by sensor name")
    except Exception as e:
        return f"{e.__class__.__name__}:{e}"
    return ""


def _apply_calib_override_status(
    perception_status: Dict[str, Any],
    *,
    requested_path: str,
    override_info: Optional[Dict[str, Any]],
    base_calib_path: str = "",
    base_calib_applied: bool = False,
) -> None:
    path_text = str(requested_path or "").strip()
    fallback_path = str(base_calib_path or "").strip()
    perception_status["calib_override_path"] = path_text or fallback_path
    applied_to: List[str] = ["rig_calibration"] if bool(base_calib_applied) else []
    applied = bool(base_calib_applied)
    if isinstance(override_info, dict):
        applied_to = _as_unique_str_list(override_info.get("applied_sensors"))
        try:
            applied_count = int(override_info.get("applied_count", 0) or 0)
        except Exception:
            applied_count = 0
        applied = bool(applied_count > 0 or len(applied_to) > 0)
        err_text = str(override_info.get("error", "") or "").strip()
        if err_text:
            warnings = perception_status.get("warnings")
            if not isinstance(warnings, list):
                warnings = []
                perception_status["warnings"] = warnings
            warn = f"calib_override_failed:{err_text}"
            if warn not in warnings:
                warnings.append(warn)
    perception_status["calib_override_applied"] = bool(applied)
    perception_status["calib_override_applied_to"] = applied_to


def _set_rig_compliance_flags(
    verification: Dict[str, Any],
    *,
    use_K_undistortion_only: bool,
    ignored_K_and_D: bool,
    ctv_inverted: bool,
    vtl_inverted: bool,
) -> None:
    values = {
        "use_K_undistortion_only": bool(use_K_undistortion_only),
        "ignored_K_and_D": bool(ignored_K_and_D),
        "ctv_inverted": bool(ctv_inverted),
        "vtl_inverted": bool(vtl_inverted),
    }
    verification.update(values)
    verification["cTv_inverted"] = bool(ctv_inverted)
    verification["vTl_inverted"] = bool(vtl_inverted)

    compliance = verification.get("thesis_compliance")
    if not isinstance(compliance, dict):
        compliance = {}
        verification["thesis_compliance"] = compliance
    compliance.update(values)
    compliance["cTv_inverted"] = bool(ctv_inverted)
    compliance["vTl_inverted"] = bool(vtl_inverted)


def _rig_verification_stub(reason: str, note: str) -> Dict[str, Any]:
    low_memory_profile_active = _env_bool("UP_LOW_MEMORY_PROFILE", False)
    payload: Dict[str, Any] = {
        "schema_version": 1,
        "ok": False,
        "reason": str(reason),
        "compliance_notes": [str(note)],
        "low_memory_profile_active": bool(low_memory_profile_active),
        "sensors_attached": "unknown",
        "sensors_attached_status": "unknown",
        "sensors_attached_reason": str(note),
        "sensors_attached_rule": (
            "all_reported_sensors_spawned_and_required_modalities_have_frames"
        ),
    }
    if bool(low_memory_profile_active):
        payload["camera_resolution_cap"] = dict(LOW_MEMORY_CAMERA_CAP)
    _set_rig_compliance_flags(
        payload,
        use_K_undistortion_only=True,
        ignored_K_and_D=True,
        ctv_inverted=False,
        vtl_inverted=True,
    )
    return payload


def _rig_verification_strict_mode(args: argparse.Namespace) -> bool:
    return bool(
        _env_bool("UP_THESIS_STRICT", False)
        or bool(getattr(args, "strict_artifacts", False))
        or bool(getattr(args, "require_evidence_pack", False))
    )


def _rig_verification_contract_errors(rig_verification: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    ctv_inverted = rig_verification.get(
        "cTv_inverted",
        rig_verification.get("ctv_inverted"),
    )
    vtl_inverted = rig_verification.get(
        "vTl_inverted",
        rig_verification.get("vtl_inverted"),
    )
    if ctv_inverted is not False:
        errors.append("cTv_inverted must be false")
    if vtl_inverted is not True:
        errors.append("vTl_inverted must be true")
    if rig_verification.get("use_K_undistortion_only") is not True:
        errors.append("use_K_undistortion_only must be true")

    sensors = rig_verification.get("sensors")
    if not isinstance(sensors, dict) or not sensors:
        errors.append("sensors must be a non-empty object")
        sensors = {}

    applied = rig_verification.get("applied_carla_transforms")
    if not isinstance(applied, dict):
        errors.append("applied_carla_transforms missing or invalid")
        applied = {}
    applied_sensors = applied.get("sensors")
    if not isinstance(applied_sensors, dict) or not applied_sensors:
        errors.append("applied_carla_transforms.sensors missing or invalid")
        applied_sensors = {}

    for sensor_name in sensors.keys():
        sensor_entry = applied_sensors.get(str(sensor_name))
        if not isinstance(sensor_entry, dict):
            errors.append(f"missing applied transform for sensor '{sensor_name}'")
            continue
        relative_tf = sensor_entry.get("relative_to_vehicle")
        if not isinstance(relative_tf, dict):
            errors.append(
                f"missing relative_to_vehicle transform for sensor '{sensor_name}'"
            )

    return errors


def _write_canonical_rig_verification(
    *,
    out_dir: Path,
    calib_path: Path,
    rig_report_payload: Optional[Dict[str, Any]],
    existing_verification: Optional[Dict[str, Any]] = None,
    note: str = "",
) -> Tuple[Dict[str, Any], List[str]]:
    rig = ThesisSensorRig(calib_path)
    report_payload: Dict[str, Any] = (
        rig_report_payload if isinstance(rig_report_payload, dict) else {}
    )
    spawned = rig.build_spawned_from_sensor_report(report_payload)
    if not spawned:
        spawned = rig.build_spawned_from_calib_defaults()

    extra: Dict[str, Any] = {
        "source": "run_perception_safe:ThesisSensorRig.write_rig_verification",
        "spawned_sensor_count": int(len(spawned)),
    }
    if note:
        extra["note"] = str(note)
    rig_path = rig.write_rig_verification(out_dir, spawned, extra=extra)
    canonical = json.loads(rig_path.read_text(encoding="utf-8", errors="replace"))

    merged: Dict[str, Any] = {}
    if isinstance(existing_verification, dict):
        merged.update(existing_verification)
    merged.update(canonical)

    existing_notes = (
        existing_verification.get("compliance_notes", [])
        if isinstance(existing_verification, dict)
        else []
    )
    canonical_notes = canonical.get("compliance_notes", [])
    merged_notes: List[str] = []
    for source_notes in (canonical_notes, existing_notes):
        if isinstance(source_notes, list):
            for note_text in source_notes:
                note_value = str(note_text)
                if note_value not in merged_notes:
                    merged_notes.append(note_value)
    merged["compliance_notes"] = merged_notes

    errors = _rig_verification_contract_errors(merged)
    merged["rig_verification_contract_ok"] = not bool(errors)
    if errors:
        merged["ok"] = False
        for err in errors:
            msg = f"ERROR: {err}"
            if msg not in merged_notes:
                merged_notes.append(msg)
    _write_json(out_dir / "rig_verification.json", merged)
    return merged, errors


def _spawn_runtime_enrichments(
    host: str,
    port: int,
    out_dir: Path,
    enrichments_json: Optional[Path],
    limit: int,
    seed: int,
    type_filter_str: str,
    required_types_str: str,
    enabled: bool = False,
) -> Dict[str, Any]:
    """
    Generalized runtime enrichment spawning.
    """
    if not enabled:
        return {"enabled": False, "spawned_count": 0}

    # Resolve enrichment path
    candidates = []
    if enrichments_json:
        candidates.append(enrichments_json)
    
    # Defaults from pipeline layout
    candidates.append(out_dir / "enrichments" / "enrichments_runtime.json")
    candidates.append(out_dir.parent / "enrichments" / "enrichments_runtime.json")
    candidates.append(out_dir / "enrichments" / "buildings_enrichments.json")
    candidates.append(out_dir.parent / "enrichments" / "buildings_enrichments.json")

    json_path = next((p for p in candidates if p.is_file()), None)
    
    if json_path is None:
        return {
            "enabled": True,
            "error": "enrichments_file_missing",
            "candidates_tried": [str(c) for c in candidates],
            "spawned_count": 0
        }

    type_filter = parse_type_filter(type_filter_str)
    required_types = parse_type_filter(required_types_str)

    report = spawn_runtime_enrichments(
        host=host,
        port=port,
        enrichments_path=str(json_path),
        out_dir=out_dir,
        limit=limit,
        seed=seed,
        type_filter=type_filter,
        required_types=required_types,
        label="safe_runner"
    )
    
    # Write artifact
    if "selection" in report:
        _write_json(out_dir / "enrichments_selection.json", report["selection"])
    
    _write_json(out_dir / "enrichments_spawn.json", report)
    
    required_check = {
        "required_types": sorted(list(required_types or [])),
        "missing": report.get("missing_required_types", []),
        "ok": not bool(report.get("missing_required_types", []))
    }
    _write_json(out_dir / "enrichments_required_check.json", required_check)

    return report


def _collect_environment_info(host: str, port: int) -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "weather": "",
        "traffic_manager_seed": None,
        "ego_spawn_transform": "",
    }
    try:
        import carla  # type: ignore

        client = carla.Client(str(host), int(port))
        client.set_timeout(5.0)
        world = client.get_world()
        try:
            info["weather"] = str(world.get_weather())
        except Exception:
            info["weather"] = ""
        try:
            tm = client.get_trafficmanager(8000)
            getter = getattr(tm, "get_random_device_seed", None)
            info["traffic_manager_seed"] = getter() if callable(getter) else None
        except Exception:
            info["traffic_manager_seed"] = None
        try:
            ego_tf = ""
            for actor in world.get_actors().filter("vehicle.*"):
                role_name = actor.attributes.get("role_name", "")
                if role_name in ("hero", "ego"):
                    ego_tf = str(actor.get_transform())
                    break
            info["ego_spawn_transform"] = ego_tf
        except Exception:
            info["ego_spawn_transform"] = ""
    except Exception:
        pass
    return info


def _write_real_u_proxy_metrics(
    out_dir: Path, model_outputs: Optional[List[List[float]]] = None
) -> None:
    logits_rows = model_outputs or []
    entropy_values: List[float] = []
    confidences: List[float] = []
    labels: List[float] = []
    for logits in logits_rows:
        if not logits:
            continue
        try:
            true_label = None
            if isinstance(logits, dict):
                true_label = logits.get("true_label", None)
                if "confidence" in logits and "correct" in logits:
                    confidences.append(float(logits.get("confidence", 0.0)))
                    labels.append(1.0 if bool(logits.get("correct")) else 0.0)
                vals = [float(v) for v in (logits.get("logits") or [])]
            else:
                vals = [float(v) for v in logits]
            if not vals:
                continue
            max_v = max(vals)
            exps = [math.exp(v - max_v) for v in vals]
            denom = sum(exps)
            if denom <= 0.0:
                continue
            probs = [e / denom for e in exps]
            pred_idx = int(max(range(len(probs)), key=lambda i: probs[i]))
            confidences.append(float(max(probs)))
            if true_label is not None:
                labels.append(1.0 if int(true_label) == pred_idx else 0.0)
            entropy = -sum(p * math.log(p + 1e-8) for p in probs)
            entropy_values.append(float(entropy))
        except Exception:
            continue

    mean_entropy = (
        float(sum(entropy_values) / len(entropy_values)) if entropy_values else 0.0
    )
    std_entropy = float(statistics.pstdev(entropy_values)) if entropy_values else 0.0
    sorted_vals = sorted(entropy_values)
    p10 = sorted_vals[int(0.1 * len(sorted_vals))] if sorted_vals else 0.0
    p90 = sorted_vals[int(0.9 * len(sorted_vals))] if sorted_vals else 0.0
    ece = 0.0
    if confidences and labels and len(confidences) == len(labels):
        try:
            from ultimate_pipeline.perception.calibration import compute_ece

            ece = float(compute_ece(confidences, labels, n_bins=15))
        except Exception:
            ece = 0.0
    real_u_metrics = {
        "mean_entropy": mean_entropy,
        "std_entropy": std_entropy,
        "p10_entropy": float(p10),
        "p90_entropy": float(p90),
        "ece": float(ece),
        "num_frames": len(entropy_values),
    }
    _write_json(out_dir / "real_u_proxy_metrics.json", real_u_metrics)


def _assert_supported_carla_version() -> None:
    try:
        import carla  # type: ignore
    except Exception:
        return

    ver = str(getattr(carla, "__version__", ""))
    if ver and not ver.startswith("0.9."):
        raise RuntimeError(f"Unsupported CARLA version: {ver}")


# Stable screenshot filenames (thesis requirement)
_DEFAULT_CALIB_PATH = "calib_data.json"
SCREENSHOT_EGO_SPAWN = "ego_spawn.png"
SCREENSHOT_CAMERA_FRONT = "camera_front.png"
SCREENSHOT_LIDAR_BEV = "lidar_bev.png"
SCREENSHOT_LIDAR_OVERLAY = "lidar_on_rgb_overlay.png"
OBJECTS_PLACED_JSON = "objects_placed.json"
OBJECTS_PLACED_PNG = "objects_placed.png"
QA_SPAWN_REPORT_JSON = "qa_spawn_report.json"
FORWARD_ALIGNMENT_DIAGNOSTICS = "forward_alignment_diagnostics.json"
WRITE_INTEGRITY_STATUS_JSON = "write_integrity_status.json"


def _validate_evidence_pack(
    out_dir: Path, require_overlay: bool, require_objects: bool
) -> List[str]:
    missing: List[str] = []
    required = [
        "rig_verification.json",
        SCREENSHOT_EGO_SPAWN,
        SCREENSHOT_CAMERA_FRONT,
        SCREENSHOT_LIDAR_BEV,
    ]
    for name in required:
        if not (out_dir / name).is_file():
            missing.append(name)
    if require_overlay and not (out_dir / SCREENSHOT_LIDAR_OVERLAY).is_file():
        missing.append(SCREENSHOT_LIDAR_OVERLAY)
    if require_objects:
        if not (out_dir / OBJECTS_PLACED_JSON).is_file():
            missing.append(OBJECTS_PLACED_JSON)
        if not (out_dir / OBJECTS_PLACED_PNG).is_file():
            missing.append(OBJECTS_PLACED_PNG)
    return missing


def _build_rig_verification_from_report(
    rig_report_path: Path,
    recording_dir: Path,
    manifest_payload: Optional[Dict[str, Any]] = None,
    calib_override_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build thesis-compliant rig_verification.json from sensor rig report."""
    verification: Dict[str, Any] = {
        "schema_version": 1,
        "source": str(rig_report_path) if rig_report_path.exists() else "not_found",
        "ok": False,
        "sensors": {},
        "map_identity": None,
        "compliance_notes": [],
        "sensors_attached": "unknown",
        "sensors_attached_status": "unknown",
        "sensors_attached_reason": "not_evaluated",
        "sensors_attached_rule": (
            "all_reported_sensors_spawned_and_required_modalities_have_frames"
        ),
    }
    _set_rig_compliance_flags(
        verification,
        use_K_undistortion_only=False,
        ignored_K_and_D=False,
        ctv_inverted=False,
        vtl_inverted=False,
    )

    if not rig_report_path.exists():
        verification["compliance_notes"].append("ERROR: rig report not found")
        return verification

    try:
        rig_data = json.loads(
            rig_report_path.read_text(encoding="utf-8", errors="replace")
        )
    except Exception as e:
        verification["compliance_notes"].append(
            f"ERROR: failed to parse rig report: {e}"
        )
        return verification

    run_info: Dict[str, Any] = {}
    run_info_path = recording_dir / "run_info.json"
    if run_info_path.exists():
        try:
            loaded = json.loads(run_info_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(loaded, dict):
                run_info = loaded
        except Exception:
            run_info = {}
    if calib_override_path is not None:
        override_meta: Dict[str, Any] = {
            "requested_path": str(calib_override_path),
            "loaded": False,
            "applied_count": 0,
            "applied_sensors": [],
            "error": "",
        }
        try:
            override_payload = json.loads(
                calib_override_path.read_text(encoding="utf-8", errors="replace")
            )
            if not isinstance(override_payload, dict):
                raise ValueError("calib override must be a JSON object keyed by sensor name")
            override_meta["loaded"] = True

            def _resolve_override_for_sensor(sensor_name: str) -> Any:
                name = str(sensor_name)
                candidates = [name]
                if name.startswith("rgb_"):
                    candidates.append(name[4:])
                else:
                    candidates.append(f"rgb_{name}")
                for key in candidates:
                    if key in override_payload:
                        return override_payload.get(key)
                return None

            def _apply_override(sensor_name: str, sensor_data: Any) -> None:
                if not isinstance(sensor_data, dict):
                    return
                matrix = _resolve_override_for_sensor(sensor_name)
                if matrix is None:
                    return
                raw = sensor_data.get("raw")
                if not isinstance(raw, dict):
                    raw = {}
                raw["cTv"] = matrix
                sensor_data["raw"] = raw
                sensor_data["override_applied"] = True
                sensor_data["override_source"] = str(calib_override_path)
                override_meta["applied_count"] = int(override_meta["applied_count"]) + 1
                cast_names = override_meta.get("applied_sensors")
                if isinstance(cast_names, list):
                    cast_names.append(str(sensor_name))

            if isinstance(rig_data, dict) and isinstance(rig_data.get("sensors"), list):
                for item in rig_data.get("sensors", []):
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name") or item.get("id")
                    if isinstance(name, str) and name:
                        _apply_override(name, item)
            elif isinstance(rig_data, list):
                for item in rig_data:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("name") or item.get("id")
                    if isinstance(name, str) and name:
                        _apply_override(name, item)
            elif isinstance(rig_data, dict):
                for name, item in rig_data.items():
                    if isinstance(name, str):
                        _apply_override(name, item)
        except Exception as e:
            override_meta["error"] = str(e)
        verification["calibration_override"] = override_meta
        if int(override_meta.get("applied_count", 0) or 0) > 0:
            verification["compliance_notes"].append(
                f"INFO: calibration override applied to {int(override_meta.get('applied_count', 0))} camera(s)"
            )
        elif override_meta.get("error"):
            verification["compliance_notes"].append(
                f"WARN: calibration override failed: {override_meta.get('error')}"
            )

    def _read_bool(value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return str(value).strip().lower() in ("1", "true", "yes", "on", "y")
        return bool(default)

    low_memory_profile_active = _read_bool(
        run_info.get("low_memory_profile_active", False), False
    )
    synchronous_mode = _read_bool(
        run_info.get("synchronous_mode", False), False
    )
    verification["synchronous_mode"] = bool(synchronous_mode)

    rig_mode = ""
    if isinstance(rig_data, dict):
        rig_mode = str(rig_data.get("rig", "")).strip().lower()
    if not rig_mode:
        rig_mode = str(run_info.get("rig", "")).strip().lower()

    recorder_cfg = run_info.get("recorder_config", {})
    if not isinstance(recorder_cfg, dict):
        recorder_cfg = {}
    default_flip = True if rig_mode == "dominik" else False
    runtime_flip_vehicle_y = _read_bool(
        recorder_cfg.get("flip_vehicle_y"),
        default_flip,
    )
    runtime_opencv_camera_axes = _read_bool(
        recorder_cfg.get("opencv_camera_axes"),
        True,
    )

    def _parse_image_size(image_size: Any) -> Tuple[Optional[int], Optional[int]]:
        if isinstance(image_size, dict):
            try:
                return int(image_size.get("width")), int(image_size.get("height"))
            except Exception:
                return None, None
        if isinstance(image_size, (list, tuple)) and len(image_size) >= 2:
            try:
                return int(image_size[0]), int(image_size[1])
            except Exception:
                return None, None
        return None, None

    def _compute_fov_deg(K_undist: Any, width_px: Optional[int]) -> Optional[float]:
        if width_px is None:
            return None
        try:
            fx = float(K_undist[0][0])
            return 2.0 * math.degrees(math.atan(float(width_px) / (2.0 * fx)))
        except Exception:
            return None

    def _expected_forward_from_name(sensor_name: str) -> Tuple[Tuple[float, float, float], str]:
        # Vehicle frame convention: X=forward, Y=left, Z=up.
        # front/back cameras face ±X; pure lateral cameras face ±Y.
        # "front" and "back" are checked first so front_left/front_right/back_left/back_right
        # resolve to the longitudinal axis, not the lateral axis.
        name = str(sensor_name).strip().lower()
        if "front" in name:
            return (1.0, 0.0, 0.0), "name:front=>+X"
        if "back" in name or "rear" in name:
            return (-1.0, 0.0, 0.0), "name:back=>-X"
        if "left" in name:
            return (0.0, 1.0, 0.0), "name:left=>+Y"   # +Y = left in vehicle frame
        if "right" in name:
            return (0.0, -1.0, 0.0), "name:right=>-Y"  # -Y = right in vehicle frame
        return (1.0, 0.0, 0.0), "default:+X"

    def _dot3(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
        return float((a[0] * b[0]) + (a[1] * b[1]) + (a[2] * b[2]))

    def _classify_failure_mode(
        actual_forward: Optional[Tuple[float, float, float]],
        dot_to_expected: Optional[float],
        *,
        threshold: float,
    ) -> str:
        if actual_forward is None:
            return "unknown"
        if abs(float(actual_forward[2])) > 0.9:
            return "vertical_forward"
        if isinstance(dot_to_expected, float) and float(dot_to_expected) < float(threshold):
            return "direction_mismatch"
        return "none"

    def _derive_camera_pose(
        sensor_data: Dict[str, Any],
        *,
        ctv_invert: bool,
    ) -> Optional[Dict[str, Any]]:
        raw_sensor = sensor_data.get("raw", {})
        if not isinstance(raw_sensor, dict):
            return None
        ctv = raw_sensor.get("cTv")
        if ctv is None:
            return None
        try:
            return camera_attachment_pose_from_cTv(
                ctv,
                flip_vehicle_y=bool(runtime_flip_vehicle_y),
                opencv_camera_axes=bool(runtime_opencv_camera_axes),
                ctv_invert=bool(ctv_invert),
            )
        except Exception:
            return None

    def _extract_sensors(data: Any) -> Dict[str, Dict[str, Any]]:
        if isinstance(data, dict) and isinstance(data.get("sensors"), list):
            out: Dict[str, Dict[str, Any]] = {}
            for item in data.get("sensors", []):
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("id")
                if isinstance(name, str) and name:
                    out[name] = item
            return out
        if isinstance(data, list):
            out_list: Dict[str, Dict[str, Any]] = {}
            for item in data:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("id")
                if isinstance(name, str) and name:
                    out_list[name] = item
            return out_list
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(v, dict)}
        return {}

    verification["ok"] = True
    cameras_count = 0
    lidars_count = 0
    any_ctv_inverted = False
    all_vtl_inverted = True
    all_use_k_undistortion = True
    ignored_k_and_d = False
    spawned_camera_names: List[str] = []
    forward_alignment_checks: List[Dict[str, Any]] = []
    forward_alignment_diagnostics: List[Dict[str, Any]] = []
    forward_alignment_threshold = 0.5

    sensors_data = _extract_sensors(rig_data)
    attachment_eval = _evaluate_sensors_attached(
        sensors_data,
        manifest_payload if isinstance(manifest_payload, dict) else {},
        recording_dir,
        require_stream_health=False,
    )
    verification.update(attachment_eval)
    for sensor_name, sensor_data in sensors_data.items():
        if not isinstance(sensor_data, dict):
            continue

        sensor_type = sensor_data.get("type", "unknown")
        raw = sensor_data.get("raw", {}) or {}

        if sensor_type == "camera":
            cameras_count += 1
            spawned_camera_names.append(str(sensor_name))
            ctv_inv = sensor_data.get("ctv_inverted", False) or sensor_data.get(
                "inversion_applied", False
            )
            if ctv_inv:
                any_ctv_inverted = True

            k_undist = raw.get("K_undistortion")
            if k_undist is None:
                all_use_k_undistortion = False

            if k_undist is not None:
                ignored_k_and_d = True
            if "K" in raw or "D" in raw:
                ignored_k_and_d = True

            width_px, height_px = _parse_image_size(raw.get("image_size"))
            derived_fov = _compute_fov_deg(k_undist, width_px)
            if derived_fov is None:
                derived_fov = sensor_data.get("attributes", {}).get("fov")

            carla_pose = sensor_data.get("carla_transform", {})
            if not isinstance(carla_pose, dict):
                carla_pose = {}
            forward_alignment = sensor_data.get("forward_alignment", {})
            if not isinstance(forward_alignment, dict):
                forward_alignment = {}
            expected_forward_vec, expected_rule = _expected_forward_from_name(sensor_name)
            ctv_matrix = raw.get("cTv")
            forward_alignment_ok = forward_alignment.get(
                "forward_alignment_ok",
                carla_pose.get("forward_alignment_ok", sensor_data.get("forward_alignment_ok")),
            )
            forward_alignment_dot_x = forward_alignment.get(
                "forward_alignment_to_vehicle_x",
                carla_pose.get(
                    "forward_alignment_to_vehicle_x",
                    sensor_data.get("forward_alignment_to_vehicle_x"),
                ),
            )
            inferred_pose = _derive_camera_pose(
                sensor_data,
                ctv_invert=bool(ctv_inv),
            )
            actual_forward: Optional[Tuple[float, float, float]] = None
            inferred_dot_x: Optional[float] = None
            if isinstance(inferred_pose, dict):
                try:
                    actual_forward = (
                        float(inferred_pose.get("forward_vehicle_x", 0.0)),
                        float(inferred_pose.get("forward_vehicle_y", 0.0)),
                        float(inferred_pose.get("forward_vehicle_z", 0.0)),
                    )
                except Exception:
                    actual_forward = None
                try:
                    inferred_dot_x = float(
                        inferred_pose.get("forward_alignment_to_vehicle_x", 0.0)
                    )
                except Exception:
                    inferred_dot_x = None
            if not isinstance(forward_alignment_dot_x, (int, float)) and isinstance(
                inferred_dot_x, float
            ):
                forward_alignment_dot_x = inferred_dot_x

            expected_dot: Optional[float] = None
            expected_ok: Optional[bool] = None
            if actual_forward is not None:
                expected_dot = _dot3(actual_forward, expected_forward_vec)
                expected_ok = bool(expected_dot >= float(forward_alignment_threshold))
            failure_mode = _classify_failure_mode(
                actual_forward,
                expected_dot,
                threshold=float(forward_alignment_threshold),
            )

            if not isinstance(forward_alignment_ok, bool) and isinstance(expected_ok, bool):
                forward_alignment_ok = expected_ok

            check_item: Dict[str, Any] = {
                "sensor": sensor_name,
                "forward_alignment_ok": (
                    bool(forward_alignment_ok)
                    if isinstance(forward_alignment_ok, bool)
                    else None
                ),
                "forward_alignment_to_vehicle_x": (
                    float(forward_alignment_dot_x)
                    if isinstance(forward_alignment_dot_x, (int, float))
                    else None
                ),
            }
            if isinstance(expected_dot, float):
                check_item["forward_alignment_to_expected"] = float(expected_dot)
            check_item["expected_forward_vehicle"] = {
                "x": float(expected_forward_vec[0]),
                "y": float(expected_forward_vec[1]),
                "z": float(expected_forward_vec[2]),
            }
            check_item["expected_rule"] = str(expected_rule)
            check_item["failure_mode"] = str(failure_mode)
            if not isinstance(check_item.get("forward_alignment_ok"), bool):
                check_item["skip_reason"] = "insufficient_alignment_diagnostics"
            forward_alignment_checks.append(check_item)

            attachment_transform: Dict[str, Any]
            if isinstance(inferred_pose, dict):
                attachment_transform = {
                    "x": float(inferred_pose.get("x", 0.0)),
                    "y": float(inferred_pose.get("y", 0.0)),
                    "z": float(inferred_pose.get("z", 0.0)),
                    "roll": float(inferred_pose.get("roll", 0.0)),
                    "pitch": float(inferred_pose.get("pitch", 0.0)),
                    "yaw": float(inferred_pose.get("yaw", 0.0)),
                }
            else:
                attachment_transform = {
                    "x": float(carla_pose.get("x", 0.0)) if isinstance(carla_pose.get("x"), (int, float)) else 0.0,
                    "y": float(carla_pose.get("y", 0.0)) if isinstance(carla_pose.get("y"), (int, float)) else 0.0,
                    "z": float(carla_pose.get("z", 0.0)) if isinstance(carla_pose.get("z"), (int, float)) else 0.0,
                    "roll": float(carla_pose.get("roll", 0.0)) if isinstance(carla_pose.get("roll"), (int, float)) else 0.0,
                    "pitch": float(carla_pose.get("pitch", 0.0)) if isinstance(carla_pose.get("pitch"), (int, float)) else 0.0,
                    "yaw": float(carla_pose.get("yaw", 0.0)) if isinstance(carla_pose.get("yaw"), (int, float)) else 0.0,
                }

            actual_forward_dict: Optional[Dict[str, float]] = None
            if actual_forward is not None:
                actual_forward_dict = {
                    "x": float(actual_forward[0]),
                    "y": float(actual_forward[1]),
                    "z": float(actual_forward[2]),
                }
            forward_alignment_diagnostics.append(
                {
                    "sensor": sensor_name,
                    "expected_forward_vehicle": {
                        "x": float(expected_forward_vec[0]),
                        "y": float(expected_forward_vec[1]),
                        "z": float(expected_forward_vec[2]),
                        "rule": str(expected_rule),
                    },
                    "actual_forward_vehicle": actual_forward_dict,
                    "dot": float(expected_dot) if isinstance(expected_dot, float) else None,
                    "alignment_ok": (
                        bool(expected_ok) if isinstance(expected_ok, bool) else None
                    ),
                    "failure_mode": str(failure_mode),
                    "attachment_transform": attachment_transform,
                    "cTv_used": ctv_matrix,
                    "conversion_path": (
                        "camera_attachment_pose_from_cTv("
                        f"flip_vehicle_y={bool(runtime_flip_vehicle_y)}, "
                        f"opencv_camera_axes={bool(runtime_opencv_camera_axes)}, "
                        f"ctv_invert={bool(ctv_inv)})"
                    ),
                }
            )

            verification["sensors"][sensor_name] = {
                "type": "camera",
                "ctv_inverted": ctv_inv,
                "cTv_inverted": ctv_inv,
                "K_undistortion": k_undist,
                "image_size": {"width": width_px, "height": height_px},
                "derived_fov_deg": derived_fov,
                "forward_alignment_ok": (
                    bool(forward_alignment_ok)
                    if isinstance(forward_alignment_ok, bool)
                    else None
                ),
                "forward_alignment_to_vehicle_x": (
                    float(forward_alignment_dot_x)
                    if isinstance(forward_alignment_dot_x, (int, float))
                    else None
                ),
                "expected_forward_vehicle": {
                    "x": float(expected_forward_vec[0]),
                    "y": float(expected_forward_vec[1]),
                    "z": float(expected_forward_vec[2]),
                    "rule": str(expected_rule),
                },
                "forward_alignment_to_expected": (
                    float(expected_dot) if isinstance(expected_dot, float) else None
                ),
                "transform_convention": sensor_data.get("transform_convention", ""),
            }

        elif sensor_type == "lidar":
            lidars_count += 1
            vtl_inv = sensor_data.get("vtl_inverted", False) or sensor_data.get(
                "inversion_applied", False
            )
            if not vtl_inv:
                all_vtl_inverted = False

            verification["sensors"][sensor_name] = {
                "type": "lidar",
                "vtl_inverted": vtl_inv,
                "vTl_inverted": vtl_inv,
                "transform_convention": sensor_data.get("transform_convention", ""),
            }
    if lidars_count == 0:
        all_vtl_inverted = False

    _set_rig_compliance_flags(
        verification,
        use_K_undistortion_only=all_use_k_undistortion and cameras_count > 0,
        ignored_K_and_D=ignored_k_and_d,
        ctv_inverted=any_ctv_inverted,
        vtl_inverted=all_vtl_inverted,
    )

    # v2-compatible contract view for validators
    verification["sensor_contract"] = {
        "cameras": {
            "intrinsics_rule": "K_undistortion_only",
            "ignore_K_and_D": True,
        },
        "transforms": {
            "cTv_direction": "vehicle_to_camera",
            "vTl_direction": "lidar_to_vehicle",
            "cTv_inversion_forbidden": True,
            "vTl_inversion_required": True,
        },
    }
    verification["ok"] = bool(
        verification["thesis_compliance"].get(
            "ok", verification["thesis_compliance"].get("passed", True)
        )
    )
    verification["schema_version"] = "rig_verification_v2"
    verification["low_memory_profile_active"] = bool(low_memory_profile_active)
    if bool(low_memory_profile_active):
        verification["camera_resolution_cap"] = dict(LOW_MEMORY_CAMERA_CAP)

    if all_use_k_undistortion and cameras_count > 0:
        verification["compliance_notes"].append(
            "OK: All cameras use K_undistortion only"
        )
    if ignored_k_and_d:
        verification["compliance_notes"].append(
            "OK: K/D present in calib but ignored (thesis mode)"
        )
    if not any_ctv_inverted:
        verification["compliance_notes"].append(
            "OK: No camera cTv transforms were inverted"
        )
    if lidars_count > 0:
        if all_vtl_inverted:
            verification["compliance_notes"].append(
                "OK: All LiDAR vTl transforms were inverted for attachment"
            )
        else:
            verification["compliance_notes"].append(
                "WARN: One or more LiDAR vTl transforms were not inverted for attachment"
            )

    verification["sensors_summary"] = {
        "cameras_count": cameras_count,
        "lidars_count": lidars_count,
    }
    verification["spawned_cameras_count"] = int(len(spawned_camera_names))
    verification["spawned_camera_names"] = [str(x) for x in spawned_camera_names]
    if forward_alignment_checks:
        bool_checks = [
            bool(x.get("forward_alignment_ok"))
            for x in forward_alignment_checks
            if isinstance(x.get("forward_alignment_ok"), bool)
        ]
        passing_names = [
            str(x.get("sensor"))
            for x in forward_alignment_checks
            if x.get("forward_alignment_ok") is True
        ]
        failing_names = [
            str(x.get("sensor"))
            for x in forward_alignment_checks
            if x.get("forward_alignment_ok") is False
        ]
        skipped_checks = [
            {"sensor": str(x.get("sensor")), "reason": str(x.get("skip_reason"))}
            for x in forward_alignment_checks
            if isinstance(x.get("skip_reason"), str) and str(x.get("skip_reason"))
        ]
        verification["forward_alignment"] = {
            "spawned_cameras_count": int(len(spawned_camera_names)),
            "spawned_camera_names": [str(x) for x in spawned_camera_names],
            "checked_cameras": int(len(forward_alignment_checks)),
            "ok_all": bool(
                len(skipped_checks) == 0
                and len(bool_checks) == len(forward_alignment_checks)
                and all(bool_checks)
            ),
            "passing_camera_names": passing_names,
            "failing_camera_names": failing_names,
            "rule": "name-conditioned expected forward vectors (front:+X, back:-X, left:-Y, right:+Y)",
            "skipped_cameras": skipped_checks,
            "cameras": forward_alignment_checks,
        }

    if forward_alignment_diagnostics:
        mismatched = [
            str(item.get("sensor"))
            for item in forward_alignment_diagnostics
            if item.get("alignment_ok") is False
        ]
        verification["forward_alignment_diagnostics"] = {
            "schema_version": 1,
            "runtime_transform_config": {
                "rig_mode": str(rig_mode),
                "flip_vehicle_y": bool(runtime_flip_vehicle_y),
                "opencv_camera_axes": bool(runtime_opencv_camera_axes),
                "alignment_threshold": float(forward_alignment_threshold),
            },
            "ok_all": len(mismatched) == 0,
            "mismatched_sensors": mismatched,
            "cameras": forward_alignment_diagnostics,
        }

    return verification


def _extract_camera_runtime_metrics(
    rig_verification: Dict[str, Any],
) -> Dict[str, Any]:
    active_camera_count = 0
    camera_sizes: List[Tuple[int, int]] = []
    sensors = (
        rig_verification.get("sensors", {})
        if isinstance(rig_verification, dict)
        else {}
    )
    if isinstance(sensors, dict):
        for sensor_data in sensors.values():
            if not isinstance(sensor_data, dict):
                continue
            if str(sensor_data.get("type", "")).strip().lower() != "camera":
                continue
            active_camera_count += 1
            image_size = sensor_data.get("image_size", {})
            if isinstance(image_size, dict):
                try:
                    w = int(image_size.get("width"))
                    h = int(image_size.get("height"))
                    camera_sizes.append((w, h))
                except Exception:
                    pass
    summary = rig_verification.get("sensors_summary", {})
    if isinstance(summary, dict):
        try:
            active_camera_count = int(summary.get("cameras_count", active_camera_count))
        except Exception:
            pass
    resolution: Dict[str, Any] = {}
    if camera_sizes:
        unique_sizes = sorted({f"{w}x{h}" for (w, h) in camera_sizes})
        resolution = {
            "unique": unique_sizes,
            "max_width": int(max(w for (w, _h) in camera_sizes)),
            "max_height": int(max(h for (_w, h) in camera_sizes)),
        }
    return {
        "active_camera_count": int(max(0, active_camera_count)),
        "camera_resolution": resolution,
    }


def _save_stable_screenshots(
    recording_dir: Path, out_dir: Path
) -> Dict[str, Optional[str]]:
    """Save screenshots with stable thesis filenames.

    Returns dict mapping stable names to actual saved paths (or None if not found).
    """
    screenshots: Dict[str, Optional[str]] = {
        SCREENSHOT_EGO_SPAWN: None,
        SCREENSHOT_CAMERA_FRONT: None,
        SCREENSHOT_LIDAR_BEV: None,
    }

    shots_dir = out_dir / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)
    stable_dir = out_dir

    # Find RGB root for camera screenshots
    rgb_root = _find_rgb_root(recording_dir)
    if rgb_root is not None:
        cam_dir = _pick_front_cam_dir(rgb_root)
        if cam_dir is not None:
            imgs = sorted(cam_dir.glob("*.png"))
            if imgs:
                # First frame as camera_front (thesis requirement)
                try:
                    shutil.copy2(imgs[0], stable_dir / SCREENSHOT_CAMERA_FRONT)
                    shutil.copy2(imgs[0], shots_dir / SCREENSHOT_CAMERA_FRONT)
                    screenshots[SCREENSHOT_CAMERA_FRONT] = str(
                        stable_dir / SCREENSHOT_CAMERA_FRONT
                    )
                except Exception:
                    pass

    # Find LiDAR data for BEV
    lidar_files = list(recording_dir.rglob("*.ply")) + list(
        recording_dir.rglob("*.npz")
    )
    if lidar_files:
        try:
            if render_lidar_bev(lidar_files[0], stable_dir / SCREENSHOT_LIDAR_BEV):
                shutil.copy2(
                    stable_dir / SCREENSHOT_LIDAR_BEV, shots_dir / SCREENSHOT_LIDAR_BEV
                )
                screenshots[SCREENSHOT_LIDAR_BEV] = str(
                    stable_dir / SCREENSHOT_LIDAR_BEV
                )
        except Exception:
            pass

    return screenshots


def _ensure_lidar_overlay(out_dir: Path) -> Optional[Path]:
    """Create lidar_on_rgb_overlay.png if possible.

    Preferred path is a simple RGB/LiDAR-BEV alpha blend (Pillow when available).
    Fallback path is a deterministic copy of camera_front.png.
    """
    overlay = out_dir / SCREENSHOT_LIDAR_OVERLAY
    if overlay.is_file():
        return overlay

    camera_front = out_dir / SCREENSHOT_CAMERA_FRONT
    lidar_bev = out_dir / SCREENSHOT_LIDAR_BEV
    if not camera_front.is_file():
        return None

    try:
        from PIL import Image  # type: ignore

        base = Image.open(camera_front).convert("RGBA")
        if lidar_bev.is_file():
            ov = Image.open(lidar_bev).convert("RGBA").resize(base.size)
            ov = ov.point(lambda v: int(v * 0.55))
            merged = Image.alpha_composite(base, ov)
            merged.convert("RGB").save(overlay)
        else:
            base.convert("RGB").save(overlay)
        return overlay
    except Exception:
        pass

    try:
        shutil.copy2(camera_front, overlay)
        return overlay
    except Exception:
        return None


def _capture_ego_spawn_screenshot(
    host: str, port: int, out_dir: Path
) -> Optional[Path]:
    """Capture ego_spawn.png using carla_screenshot_once.py."""
    script = Path(__file__).resolve().parent / "carla_screenshot_once.py"
    if not script.exists():
        return None
    try:
        cmd = [
            sys.executable,
            str(script),
            "--host",
            str(host),
            "--port",
            str(int(port)),
            "--out",
            str(out_dir),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90.0,
        )
        (out_dir / "carla_screenshot_once_stdout.txt").write_text(
            proc.stdout or "", encoding="utf-8", errors="replace"
        )
        (out_dir / "carla_screenshot_once_stderr.txt").write_text(
            proc.stderr or "", encoding="utf-8", errors="replace"
        )
        shot = out_dir / "screenshot_once.png"
        if shot.exists():
            dst = out_dir / SCREENSHOT_EGO_SPAWN
            shutil.copy2(shot, dst)
            return dst
        
        # Fallback: use camera_front.png if available
        camera_front = out_dir / SCREENSHOT_CAMERA_FRONT
        if camera_front.exists():
            dst = out_dir / SCREENSHOT_EGO_SPAWN
            shutil.copy2(camera_front, dst)
            print(f"INFO: Using {SCREENSHOT_CAMERA_FRONT} as fallback for {SCREENSHOT_EGO_SPAWN}", flush=True)
            return dst
    except Exception:
        return None
    return None


def _spawn_sanity_objects_with_screenshot(
    host: str, port: int, out_dir: Path
) -> Optional[Path]:
    """Spawn deterministic sanity objects and capture a screenshot."""
    script = Path(__file__).resolve().parent / "spawn_sanity_objects.py"
    if not script.exists():
        return None
    report_path = out_dir / "objects_placed.json"
    screenshot_path = out_dir / "objects_placed.png"
    try:
        cmd = [
            sys.executable,
            str(script),
            "--host",
            str(host),
            "--port",
            str(int(port)),
            "--report",
            str(report_path),
            "--screenshot",
            str(screenshot_path),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120.0,
        )
        (out_dir / "spawn_sanity_objects_stdout.txt").write_text(
            proc.stdout or "", encoding="utf-8", errors="replace"
        )
        (out_dir / "spawn_sanity_objects_stderr.txt").write_text(
            proc.stderr or "", encoding="utf-8", errors="replace"
        )
        if screenshot_path.exists():
            return screenshot_path
    except Exception:
        return None
    return None


def _build_qa_spawn_report(out_dir: Path, spawn_requested: bool) -> Dict[str, Any]:
    source_path = out_dir / OBJECTS_PLACED_JSON
    report: Dict[str, Any] = {
        "qa_objects_attempted": 0,
        "qa_objects_spawned": 0,
        "qa_objects_spawn_success_rate": 0.0,
        "qa_objects_collision_free_rate": 0.0,
        "spawn_requested": bool(spawn_requested),
        "source_report_path": str(source_path) if source_path.is_file() else "",
        "source_report_found": bool(source_path.is_file()),
    }
    if not source_path.is_file():
        return report
    try:
        payload = json.loads(source_path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        report["parse_error"] = f"{e.__class__.__name__}:{e}"
        return report

    objects = payload.get("objects", [])
    if not isinstance(objects, list):
        report["parse_error"] = "objects_missing_or_not_list"
        return report

    attempted = int(len(objects))
    spawned = 0
    collision_failures = 0
    for item in objects:
        if not isinstance(item, dict):
            continue
        if bool(item.get("spawned", False)):
            spawned += 1
        if str(item.get("reason", "")).strip().lower() == "spawn_returned_none":
            collision_failures += 1

    collision_free = max(0, attempted - int(collision_failures))
    success_rate = float(spawned / attempted) if attempted > 0 else 0.0
    collision_free_rate = float(collision_free / attempted) if attempted > 0 else 0.0
    report.update(
        {
            "qa_objects_attempted": attempted,
            "qa_objects_spawned": int(spawned),
            "qa_objects_spawn_success_rate": success_rate,
            "qa_objects_collision_free_rate": collision_free_rate,
            "qa_objects_collision_failures": int(collision_failures),
        }
    )
    return report


def _default_calib_path() -> Path:
    repo_root = _repo_root_dir()
    preferred = repo_root / "ultimate_pipeline" / "sensors" / "calib_data.json"
    if preferred.exists():
        return preferred
    return repo_root / "calib_data.json"


def _resolve_calib_path(calib_arg: Optional[Path]) -> Tuple[Path, str]:
    repo_root = _repo_root_dir()
    if calib_arg is not None:
        p = Path(calib_arg).expanduser()
        if not p.is_absolute():
            p = (Path.cwd() / p)
        return p, "cli"
    settings_path = str(getattr(SETTINGS, "SENSOR_CALIB_JSON", "") or "").strip()
    if settings_path:
        p = Path(settings_path).expanduser()
        if not p.is_absolute():
            p = repo_root / p
        return p, "settings:SENSOR_CALIB_JSON"
    return _default_calib_path(), "default"


def _thesis_capture_gate_snapshot(rig: str) -> Dict[str, Any]:
    env_raw = os.environ.get("UP_ENABLE_THESIS_PERCEPTION_CAPTURE")
    env_present = env_raw is not None
    env_enabled = (
        _env_bool("UP_ENABLE_THESIS_PERCEPTION_CAPTURE", False)
        if env_present
        else None
    )
    settings_enabled = bool(getattr(SETTINGS, "ENABLE_THESIS_PERCEPTION_CAPTURE", False))
    gate_enabled = bool(env_enabled) if env_present else bool(settings_enabled)
    gate_required = str(rig).strip().lower() == "thesis"
    return {
        "gate_required": bool(gate_required),
        "enabled": bool(gate_enabled),
        "env_present": bool(env_present),
        "env_raw": str(env_raw) if env_raw is not None else "",
        "env_enabled": (
            bool(env_enabled) if isinstance(env_enabled, bool) else None
        ),
        "settings_enabled": bool(settings_enabled),
    }


def _build_prelaunch_rig_report(
    *,
    rig: str,
    calib_path: Path,
    calib_path_metadata: str,
    calib_source: str,
    gate: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": 2,
        "ok": False,
        "reason": "prelaunch",
        "rig": str(rig),
        "rig_attach_attempted": False,
        "calib_path_resolved": str(calib_path_metadata or ""),
        "calib_source": str(calib_source),
        "calib_exists": bool(calib_path.exists()),
        "gating_conditions": dict(gate),
        "spawned_sensors": [],
        "listener_callbacks_registered": 0,
        "sensors": [],
    }


def _build_scene_readiness_report(
    *,
    thesis_rig_requested: bool,
    thesis_gate_enabled: bool,
    calib_present: bool,
    enrichments_enabled: bool,
    enrich_spawn_report: Dict[str, Any],
    qa_bundle_written: bool,
    qa_capture_after_enrichment: bool,
    strict_scene_gate: bool,
) -> Dict[str, Any]:
    missing_required_types = list(
        enrich_spawn_report.get("missing_required_types", []) or []
    )
    enrichments_file_found = bool(
        enrich_spawn_report.get("error") != "enrichments_file_missing"
    )
    thesis_rig_attach_ready = bool(
        (not thesis_rig_requested) or (thesis_gate_enabled and calib_present)
    )
    readiness_blockers: List[str] = []
    if bool(enrichments_enabled) and not enrichments_file_found:
        readiness_blockers.append("enrichments_file_missing")
    if missing_required_types:
        readiness_blockers.append(
            f"missing_required_enrichments:{','.join(missing_required_types)}"
        )
    if thesis_rig_requested and not thesis_gate_enabled:
        readiness_blockers.append("rig_attach_gated")
    if thesis_rig_requested and not calib_present:
        readiness_blockers.append("calib_missing")
    if bool(qa_capture_after_enrichment) and not qa_bundle_written:
        readiness_blockers.append("qa_bundle_missing_after_enrichment")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "thesis_rig_requested": bool(thesis_rig_requested),
        "thesis_rig_attach_ready": bool(thesis_rig_attach_ready),
        # This artifact is written before record_route starts, so attach success
        # cannot be claimed here. Runtime truth lives in sensor_rig_report.json.
        "thesis_rig_attached": False,
        "thesis_rig_attached_reason": (
            "not_requested" if not thesis_rig_requested else "prelaunch_not_attempted"
        ),
        "enrichments_enabled": bool(enrichments_enabled),
        "enrichments_file_found": enrichments_file_found,
        "required_types": list(enrich_spawn_report.get("required_types", [])),
        "missing_required_types": missing_required_types,
        "spawned_count": enrich_spawn_report.get("spawned_count", 0),
        "qa_bundle_written": bool(qa_bundle_written),
        "strict_gate_requested": bool(strict_scene_gate),
        "safe_to_start_recording": not (
            bool(strict_scene_gate) and bool(readiness_blockers)
        ),
        "failure_reason": ";".join(readiness_blockers),
    }


def _finalize_scene_readiness_attachment(
    scene_readiness: Dict[str, Any],
    *,
    thesis_rig_requested: bool,
    rig_report_payload: Optional[Dict[str, Any]],
    spawned_sensors: List[str],
) -> Dict[str, Any]:
    report = dict(scene_readiness or {})
    if not bool(thesis_rig_requested):
        report["thesis_rig_attached"] = False
        report["thesis_rig_attached_reason"] = "not_requested"
        return report

    rig_payload = (
        dict(rig_report_payload) if isinstance(rig_report_payload, dict) else {}
    )
    spawn_success_count = _safe_int(
        rig_payload.get("spawn_success_count", 0),
        default=0,
    )
    spawned_from_report = rig_payload.get("spawned_sensors", [])
    if isinstance(spawned_from_report, list):
        spawned_evidence = [
            str(name)
            for name in spawned_from_report
            if str(name or "").strip()
        ]
    else:
        spawned_evidence = []
    if not spawned_evidence:
        spawned_evidence = [
            str(name) for name in spawned_sensors if str(name or "").strip()
        ]

    attached = bool(spawn_success_count > 0 or len(spawned_evidence) > 0)
    report["thesis_rig_attached"] = bool(attached)
    if spawn_success_count > 0:
        report["thesis_rig_attached_reason"] = "spawn_success_count"
    elif spawned_evidence:
        report["thesis_rig_attached_reason"] = "spawned_sensors"
    elif bool(rig_payload.get("rig_attach_attempted", False)):
        report["thesis_rig_attached_reason"] = "attach_attempt_without_spawn_success"
    else:
        report["thesis_rig_attached_reason"] = "prelaunch_not_attempted"
    return report


def _parse_bounded_spawned_sensors_payload(payload: str) -> List[str]:
    text = str(payload or "").strip()
    if not text:
        return []
    if len(text) > MAX_SPAWNED_SENSORS_PAYLOAD_CHARS:
        return []
    if not (text.startswith("[") and text.endswith("]")):
        return []

    try:
        parsed: Any = json.loads(text)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []

    out: List[str] = []
    for item in parsed[:MAX_SPAWNED_SENSOR_NAMES]:
        name = str(item).strip()
        if not name or len(name) > 256:
            continue
        out.append(name)
    return out


def _extract_rig_attach_diagnostics_from_stdout(
    stdout_text: str,
) -> Tuple[bool, List[str], int]:
    attempted = False
    spawned: List[str] = []
    listeners = 0
    text = str(stdout_text or "")
    for raw_line in text.splitlines():
        line = str(raw_line).strip()
        if line.lower().startswith("rig attach attempted:"):
            attempted = "yes" in line.lower()
        elif line.lower().startswith("spawned sensors:"):
            payload = line.split(":", 1)[-1].strip()
            spawned = _parse_bounded_spawned_sensors_payload(payload)
        elif line.lower().startswith("listener callbacks registered:"):
            try:
                listeners = int(line.split(":", 1)[-1].strip())
            except Exception:
                listeners = 0
    return bool(attempted), spawned, int(listeners)


def _tcp_port_open(host: str, port: int, timeout_s: float = 0.5) -> bool:
    import socket

    try:
        with socket.create_connection((host, int(port)), timeout=float(timeout_s)):
            return True
    except OSError:
        return False


def _find_rgb_root(recording_dir: Path) -> Optional[Path]:
    rgb = recording_dir / "rgb"
    if rgb.is_dir():
        return rgb
    for p in recording_dir.rglob("rgb"):
        if p.is_dir():
            return p
    return None


def _count_files(root: Path, patterns: Tuple[str, ...]) -> int:
    c = 0
    for pat in patterns:
        c += sum(1 for _ in root.rglob(pat))
    return c


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _read_json_if_dict(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_manifest_fallback_payload(
    recording_dir: Path, *, fallback_timestamp: str
) -> Dict[str, Any]:
    rgb_root = _find_rgb_root(recording_dir)
    rgb_files = _count_files(rgb_root, ("*.png",)) if rgb_root is not None else 0
    semseg_root = recording_dir / "semseg_raw"
    semseg_files = _count_files(semseg_root, ("*.png",)) if semseg_root.is_dir() else 0
    lidar_files = _count_files(recording_dir, ("*.ply", "*.npz"))

    sensors: List[Dict[str, Any]] = []
    per_sensor_counts: Dict[str, Dict[str, Any]] = {}

    if rgb_root is not None:
        for cam_dir in sorted([p for p in rgb_root.iterdir() if p.is_dir()], key=lambda p: p.name):
            frames = _count_files(cam_dir, ("*.png",))
            sensors.append(
                {
                    "name": cam_dir.name,
                    "kind": "rgb",
                    "type_id": "",
                    "frame_count": int(frames),
                    "output_dir": str(cam_dir),
                }
            )
            per_sensor_counts[cam_dir.name] = {
                "kind": "rgb",
                "frames": int(frames),
                "rgb_frames": int(frames),
                "lidar_frames": 0,
            }

    lidar_root = recording_dir / "lidar"
    if lidar_root.is_dir():
        for lidar_dir in sorted([p for p in lidar_root.iterdir() if p.is_dir()], key=lambda p: p.name):
            frames = _count_files(lidar_dir, ("*.ply", "*.npz"))
            sensors.append(
                {
                    "name": lidar_dir.name,
                    "kind": "lidar",
                    "type_id": "",
                    "frame_count": int(frames),
                    "output_dir": str(lidar_dir),
                }
            )
            per_sensor_counts[lidar_dir.name] = {
                "kind": "lidar",
                "frames": int(frames),
                "rgb_frames": 0,
                "lidar_frames": int(frames),
            }

    return {
        "schema_version": 1,
        "start_time": str(fallback_timestamp),
        "end_time": str(fallback_timestamp),
        "started_utc": str(fallback_timestamp),
        "closed_utc": str(fallback_timestamp),
        "output_dir": str(recording_dir),
        "output_roots": {
            "rgb": str(recording_dir / "rgb"),
            "semseg": str(recording_dir / "semseg_raw"),
            "lidar": str(recording_dir / "lidar"),
            "meta": str(recording_dir / "meta"),
        },
        "sensors": sensors,
        "per_sensor_counts": per_sensor_counts,
        "sensor_frame_counts": {
            k: int(v.get("frames", 0)) for k, v in per_sensor_counts.items()
        },
        "counts": {
            "rgb_files": int(rgb_files),
            "semseg_files": int(semseg_files),
            "lidar_files": int(lidar_files),
            "total_files": int(rgb_files + semseg_files + lidar_files),
        },
        "save_errors_tail": [],
        "last_tick_snapshot": None,
        "manifest_source": "run_perception_safe_fallback",
    }


def _sync_recorder_manifest(
    recording_dir: Path,
    out_dir: Path,
    *,
    fallback_timestamp: str,
    map_name: str = "UNKNOWN",
    world_settings_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    src = recording_dir / "recorder_manifest.json"
    dst = out_dir / "recorder_manifest.json"
    manifest = _read_json_if_dict(src)
    synthesized = False
    if not manifest:
        manifest = _build_manifest_fallback_payload(
            recording_dir, fallback_timestamp=fallback_timestamp
        )
        synthesized = True
    if not isinstance(manifest, dict):
        manifest = {}
    manifest["manifest_source"] = (
        "run_perception_safe_fallback" if synthesized else "recorder"
    )
    map_name_text = str(map_name or "UNKNOWN")
    manifest["carla_map_name"] = map_name_text
    manifest["carla_map_basename"] = map_name_text.split("/")[-1]
    manifest["carla_world_settings"] = (
        dict(world_settings_payload)
        if isinstance(world_settings_payload, dict)
        else {}
    )

    rec_written = False
    root_written = False
    errors: List[str] = []
    try:
        _write_json(src, manifest)
        rec_written = True
    except Exception as exc:
        errors.append(f"recording_manifest_write_failed:{exc}")
    try:
        _write_json(dst, manifest)
        root_written = True
    except Exception as exc:
        errors.append(f"root_manifest_write_failed:{exc}")

    if rec_written and root_written:
        return {
            "path": str(src),
            "recording_path": str(src),
            "root_copy_path": str(dst),
            "written": True,
            "recording_written": True,
            "root_copy_written": True,
            "synthesized": bool(synthesized),
            "error": "",
            "data": manifest,
        }

    return {
        "path": str(src),
        "recording_path": str(src),
        "root_copy_path": str(dst),
        "written": False,
        "recording_written": bool(rec_written),
        "root_copy_written": bool(root_written),
        "synthesized": bool(synthesized),
        "error": ";".join(errors),
        "data": manifest if isinstance(manifest, dict) else {},
    }


def _assert_recorder_manifest_integrity(
    recording_dir: Path, out_dir: Path, manifest_sync: Optional[Dict[str, Any]] = None
) -> None:
    src = recording_dir / "recorder_manifest.json"
    dst = out_dir / "recorder_manifest.json"
    src_exists = src.is_file()
    dst_exists = dst.is_file()
    if not src_exists and not dst_exists:
        raise RuntimeError("MISSING_RECORDER_MANIFEST")

    payload: Dict[str, Any] = {}
    if isinstance(manifest_sync, dict):
        data = manifest_sync.get("data")
        if isinstance(data, dict):
            payload = data
    if not payload and src_exists:
        payload = _read_json_if_dict(src)
    if not payload and dst_exists:
        payload = _read_json_if_dict(dst)

    counts = payload.get("counts", {}) if isinstance(payload, dict) else {}
    total_files = _safe_int(
        counts.get("total_files", 0) if isinstance(counts, dict) else 0, default=0
    )
    sensors = payload.get("sensors", []) if isinstance(payload, dict) else []
    sensors_count = len(sensors) if isinstance(sensors, list) else 0
    if int(total_files) <= 0 or int(sensors_count) <= 0:
        raise RuntimeError("EMPTY_RECORDER_MANIFEST")
    required_provenance = (
        "carla_map_name",
        "carla_map_basename",
        "carla_world_settings",
    )
    if any(key not in payload for key in required_provenance):
        raise RuntimeError("MISSING_MAP_PROVENANCE")


def _evaluate_sensors_attached(
    sensors_data: Dict[str, Dict[str, Any]],
    manifest_payload: Dict[str, Any],
    recording_dir: Path,
    *,
    require_stream_health: bool = False,
) -> Dict[str, Any]:
    rule = "all_reported_sensors_spawned_and_required_modalities_have_frames"
    if not isinstance(sensors_data, dict) or not sensors_data:
        return {
            "sensors_attached": "unknown",
            "sensors_attached_status": "unknown",
            "sensors_attached_reason": "no_sensor_report_entries",
            "sensors_attached_rule": rule,
            "required_modalities": {"rgb": 0, "lidar": 0},
            "recorded_modalities": {"rgb_frames": 0, "lidar_frames": 0},
        }

    required_rgb = 0
    required_lidar = 0
    spawn_errors: List[str] = []
    for sensor_name, sensor_data in sensors_data.items():
        if not isinstance(sensor_data, dict):
            continue
        sensor_type = str(sensor_data.get("type", "")).lower()
        if sensor_type == "camera":
            required_rgb += 1
        elif sensor_type == "lidar":
            required_lidar += 1

        healthcheck = sensor_data.get("healthcheck")
        listen_error = (
            healthcheck.get("listen_error")
            if isinstance(healthcheck, dict)
            else None
        )
        sensor_error = sensor_data.get("spawn_error") or sensor_data.get("error")
        if sensor_error:
            spawn_errors.append(f"{sensor_name}:{sensor_error}")
        elif require_stream_health and listen_error:
            spawn_errors.append(f"{sensor_name}:{listen_error}")

    counts = manifest_payload.get("counts", {}) if isinstance(manifest_payload, dict) else {}
    rgb_frames = _safe_int(counts.get("rgb_files"), default=-1)
    lidar_frames = _safe_int(counts.get("lidar_files"), default=-1)
    rgb_root = _find_rgb_root(recording_dir)
    rgb_frames_disk = _count_files(rgb_root, ("*.png",)) if rgb_root is not None else 0
    lidar_frames_disk = _count_files(recording_dir, ("*.ply", "*.npz"))
    if rgb_frames < 0:
        rgb_frames = int(rgb_frames_disk)
    else:
        rgb_frames = int(max(rgb_frames, rgb_frames_disk))
    if lidar_frames < 0:
        lidar_frames = int(lidar_frames_disk)
    else:
        lidar_frames = int(max(lidar_frames, lidar_frames_disk))

    if spawn_errors:
        return {
            "sensors_attached": False,
            "sensors_attached_status": "false",
            "sensors_attached_reason": "sensor_spawn_or_listen_error",
            "sensors_attached_errors": spawn_errors,
            "sensors_attached_rule": rule,
            "required_modalities": {"rgb": int(required_rgb), "lidar": int(required_lidar)},
            "recorded_modalities": {
                "rgb_frames": int(rgb_frames),
                "lidar_frames": int(lidar_frames),
            },
        }

    if (required_rgb + required_lidar) > 0 and rgb_frames < 1 and lidar_frames < 1:
        return {
            "sensors_attached": "unknown",
            "sensors_attached_status": "unknown",
            "sensors_attached_reason": "no_recorded_frames_attachment_unknown",
            "sensors_attached_rule": rule,
            "required_modalities": {"rgb": int(required_rgb), "lidar": int(required_lidar)},
            "recorded_modalities": {
                "rgb_frames": int(rgb_frames),
                "lidar_frames": int(lidar_frames),
            },
        }

    missing_modalities: List[str] = []
    if required_rgb > 0 and rgb_frames < 1:
        missing_modalities.append("rgb")
    if required_lidar > 0 and lidar_frames < 1:
        missing_modalities.append("lidar")

    if missing_modalities:
        return {
            "sensors_attached": False,
            "sensors_attached_status": "false",
            "sensors_attached_reason": "missing_modality_frames",
            "sensors_attached_missing_modalities": missing_modalities,
            "sensors_attached_rule": rule,
            "required_modalities": {"rgb": int(required_rgb), "lidar": int(required_lidar)},
            "recorded_modalities": {
                "rgb_frames": int(rgb_frames),
                "lidar_frames": int(lidar_frames),
            },
        }

    return {
        "sensors_attached": True,
        "sensors_attached_status": "true",
        "sensors_attached_reason": "spawn_ok_and_required_modalities_recorded",
        "sensors_attached_rule": rule,
        "required_modalities": {"rgb": int(required_rgb), "lidar": int(required_lidar)},
        "recorded_modalities": {
            "rgb_frames": int(rgb_frames),
            "lidar_frames": int(lidar_frames),
        },
    }


def _recording_satisfies_min_frames(recording_dir: Path, min_frames: int) -> bool:
    rgb_root = _find_rgb_root(recording_dir)
    if rgb_root is None:
        return False
    png_count = _count_files(rgb_root, ("*.png",))
    return int(png_count) >= int(max(0, min_frames))


def _pick_primary_cam_dir(rgb_root: Path) -> Optional[Path]:
    cams = [p for p in rgb_root.iterdir() if p.is_dir()]
    cams.sort(key=lambda p: p.name)
    return cams[0] if cams else None


def _pick_front_cam_dir(rgb_root: Path) -> Optional[Path]:
    cams = [p for p in rgb_root.iterdir() if p.is_dir()]
    cams.sort(key=lambda p: p.name)
    if not cams:
        return None
    front = [p for p in cams if "front" in p.name.lower()]
    return front[0] if front else cams[0]


def _ensure_front_rgb_frame(rgb_root: Optional[Path]) -> Dict[str, str]:
    evidence = {"camera_dir": "", "first_frame_path": "", "front_alias_path": ""}
    if rgb_root is None:
        return evidence

    cam_dir = _pick_front_cam_dir(rgb_root)
    if cam_dir is None:
        return evidence
    evidence["camera_dir"] = str(cam_dir)

    imgs = sorted(cam_dir.glob("*.png"))
    if not imgs:
        return evidence

    first = imgs[0]
    evidence["first_frame_path"] = str(first)
    if "front" in cam_dir.name.lower():
        evidence["front_alias_path"] = str(first)
        return evidence

    front_dir = rgb_root / "front"
    front_dir.mkdir(parents=True, exist_ok=True)
    front_alias = front_dir / first.name
    try:
        if not front_alias.exists():
            shutil.copy2(first, front_alias)
        evidence["front_alias_path"] = str(front_alias)
    except Exception:
        evidence["front_alias_path"] = str(first)
    return evidence


def _compute_simple_image_stats(image_paths: List[Path]) -> Dict[str, float]:
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return {
            "brightness_mean": 0.0,
            "brightness_std": 0.0,
            "laplacian_variance": 0.0,
        }

    if not image_paths:
        return {
            "brightness_mean": 0.0,
            "brightness_std": 0.0,
            "laplacian_variance": 0.0,
        }

    sample = image_paths
    if len(sample) > 25:
        idxs = [int(i * (len(sample) - 1) / 24) for i in range(25)]
        sample = [sample[i] for i in idxs]

    means, stds, laps = [], [], []
    for p in sample:
        try:
            img = Image.open(p).convert("L")
            arr = np.array(img, dtype=np.float32) / 255.0
            means.append(float(arr.mean()))
            stds.append(float(arr.std()))
            lap = (
                -4.0 * arr
                + np.roll(arr, 1, axis=0)
                + np.roll(arr, -1, axis=0)
                + np.roll(arr, 1, axis=1)
                + np.roll(arr, -1, axis=1)
            )
            laps.append(float(lap.var()))
        except Exception:
            continue

    if not means:
        return {
            "brightness_mean": 0.0,
            "brightness_std": 0.0,
            "laplacian_variance": 0.0,
        }
    import numpy as np

    return {
        "brightness_mean": float(np.mean(means)),
        "brightness_std": float(np.mean(stds)),
        "laplacian_variance": float(np.mean(laps) if laps else 0.0),
    }


def _scan_outputs(out_dir: Path) -> Dict[str, Any]:
    png_count = _count_files(out_dir, ("*.png",))
    ply_count = _count_files(out_dir, ("*.ply",))
    npz_count = _count_files(out_dir, ("*.npz",))
    ply_example = ""
    if int(ply_count) > 0:
        try:
            first = sorted(out_dir.rglob("*.ply"))[0]
            ply_example = str(first)
        except Exception:
            ply_example = ""
    return {
        "png": int(png_count),
        "ply": int(ply_count),
        "npz": int(npz_count),
        "ply_example_path": str(ply_example),
    }


def _semseg_file_count(recording_dir: Path, manifest_payload: Dict[str, Any]) -> int:
    semseg_disk = 0
    semseg_root = recording_dir / "semseg_raw"
    if semseg_root.is_dir():
        semseg_disk = _count_files(semseg_root, ("*.png",))
    semseg_manifest = 0
    counts = manifest_payload.get("counts", {}) if isinstance(manifest_payload, dict) else {}
    if isinstance(counts, dict):
        semseg_manifest = _safe_int(counts.get("semseg_files", 0), default=0)
    return int(max(int(semseg_disk), int(semseg_manifest)))


def _png_readable(path: Path) -> bool:
    try:
        from PIL import Image

        with Image.open(path) as img:
            img.verify()
        return True
    except Exception:
        try:
            header = path.read_bytes()[:8]
            return header == b"\x89PNG\r\n\x1a\n"
        except Exception:
            return False


def _read_queue_depth_at_shutdown(manifest_payload: Dict[str, Any]) -> int:
    if not isinstance(manifest_payload, dict):
        return 0
    last_tick = manifest_payload.get("last_tick_snapshot", {})
    if isinstance(last_tick, dict):
        for key in (
            "queue_depth_at_shutdown",
            "queue_depth",
            "pending_writes",
            "pending_writes_count",
        ):
            if key in last_tick:
                return _safe_int(last_tick.get(key, 0), default=0)
    for key in ("queue_depth_at_shutdown", "queue_depth"):
        if key in manifest_payload:
            return _safe_int(manifest_payload.get(key, 0), default=0)
    return 0


def _build_write_integrity_status(
    *,
    recording_dir: Path,
    manifest_payload: Dict[str, Any],
    max_png_checks: int = 400,
) -> Dict[str, Any]:
    roots = [recording_dir / "rgb", recording_dir / "semseg_raw"]
    png_paths: List[Path] = []
    for root in roots:
        if root.is_dir():
            png_paths.extend(sorted(root.rglob("*.png")))
    if len(png_paths) > int(max_png_checks):
        stride = max(1, len(png_paths) // int(max_png_checks))
        sampled = png_paths[::stride]
        png_paths = sampled[: int(max_png_checks)]

    invalid_examples: List[str] = []
    invalid_count = 0
    for path in png_paths:
        if _png_readable(path):
            continue
        invalid_count += 1
        if len(invalid_examples) < 20:
            invalid_examples.append(str(path))

    return {
        "schema_version": 1,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "png_files_checked": int(len(png_paths)),
        "corrupted_png_read": int(1 if invalid_count > 0 else 0),
        "invalid_png_count": int(invalid_count),
        "invalid_png_examples": invalid_examples,
        "queue_depth_at_shutdown": int(
            _read_queue_depth_at_shutdown(manifest_payload)
        ),
    }


def _detect_destroyed_actor(out_dir: Path) -> bool:
    haystacks = []
    for name in ("record_route_stderr.txt", "record_route_stdout.txt"):
        p = out_dir / name
        if p.exists():
            try:
                haystacks.append(p.read_text(encoding="utf-8", errors="ignore").lower())
            except Exception:
                pass
    text = "\n".join(haystacks)
    if not text:
        return False
    return ("destroyed actor" in text) or ("actor" in text and "destroyed" in text)


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Safe perception capture with bounded waits."
    )
    ap.add_argument("--manual-town", required=True)

    map_group = ap.add_mutually_exclusive_group(required=True)
    map_group.add_argument("--xodr-in", type=Path)
    map_group.add_argument("--town")

    ap.add_argument("--use-current-world", action="store_true")
    ap.add_argument("--rig", choices=["dominik", "thesis"], default="thesis")
    ap.add_argument(
        "--manual-via-xodr",
        action="store_true",
        help="Force manual baseline to load via XODR instead of cooked town",
    )

    # Runtime Enrichment & QA Arguments
    ap.add_argument(
        "--spawn-enrichments",
        action="store_true",
        help="Spawn visible proxy actors before recording."
    )
    ap.add_argument(
        "--enrichments-json",
        type=Path,
        default=None,
        help="Path to enrichments.json; defaults to <out>/enrichments/enrichments_runtime.json"
    )
    ap.add_argument(
        "--spawn-enrichments-filter",
        default="building,pole,barrier,fence_proxy,vegetation_proxy,bench,bin",
        help="Comma-separated types to spawn."
    )
    ap.add_argument(
        "--spawn-enrichments-limit",
        type=int,
        default=1500,
        help="Max enrichment actors."
    )
    ap.add_argument(
        "--spawn-enrichments-seed",
        type=int,
        default=42,
        help="Deterministic spawn seed."
    )
    ap.add_argument(
        "--spawn-enrichments-required-types",
        default="building,pole,barrier",
        help="Comma-separated types that MUST be present."
    )
    ap.add_argument(
        "--fail-on-missing-required-enrichments",
        action="store_true",
        help="Fail closed if required classes are absent."
    )
    ap.add_argument(
        "--qa-capture-after-enrichment",
        action="store_true",
        help="Capture single-frame QA bundle after spawning actors."
    )
    ap.add_argument(
        "--keep-enrichments-alive",
        action="store_true",
        help="Do not destroy enrichment actors after run."
    )

    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--frames", type=int, default=200)
    ap.add_argument("--fps", type=float, default=10.0)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2000)
    ap.add_argument("--streaming-port", type=int, default=None)
    ap.add_argument(
        "--skip-stream-check",
        action="store_true",
        help=(
            "Bypass outer streaming port probe; useful when CARLA streaming is "
            "available but takes time to bind. Inner check in record_route still applies."
        ),
    )
    ap.add_argument(
        "--stream-wait-s",
        type=float,
        default=None,
        help=(
            "Wait up to this many seconds for the CARLA streaming port to become "
            "reachable before capture starts. Defaults to UP_STREAM_WAIT_S or 1.0s."
        ),
    )

    ap.add_argument("--lowres", action="store_true")
    ap.add_argument(
        "--no-seg",
        action="store_true",
        help="Disable semantic segmentation sensors for record_route_fixed capture.",
    )
    ap.add_argument(
        "--front-only-strict",
        action="store_true",
        help=(
            "Use reduced strict capture profile (front camera(s) + primary LiDAR) "
            "for record_route_fixed."
        ),
    )
    ap.add_argument(
        "--force-fresh-capture",
        action="store_true",
        help=(
            "Bypass offline recording reuse shortcut and force a fresh "
            "record_route_fixed capture."
        ),
    )
    ap.add_argument("--calib", type=Path, default=None)
    ap.add_argument(
        "--calib-override",
        type=str,
        default=None,
        help="Optional JSON file with per-camera cTv overrides",
    )
    ap.add_argument("--spawn-qa-objects", action="store_true")
    ap.add_argument("--lidar-overlay", action="store_true")
    ap.add_argument("--elevation-gate", action="store_true")
    ap.add_argument(
        "--fail-nonzero",
        action="store_true",
        help="Return nonzero on failed gating/integrity checks (auto-enabled in thesis-strict mode).",
    )
    ap.add_argument(
        "--strict-artifacts",
        action="store_true",
        help=(
            "Require full capture (min_frames=frames) and fail nonzero "
            "(auto-enabled in thesis-strict mode)."
        ),
    )
    ap.add_argument(
        "--expected-map-name",
        type=str,
        default=None,
        help="Fail if CARLA world map name does not contain this substring.",
    )
    ap.add_argument(
        "--map-probe",
        action="store_true",
        help=(
            "Run a fast map-only preflight probe before record_route_fixed. "
            "Automatically enabled when --expected-map-name is provided."
        ),
    )
    ap.add_argument(
        "--map-probe-timeout-s",
        type=float,
        default=None,
        help="Optional timeout override for the map-only probe subprocess.",
    )
    ap.add_argument(
        "--require-evidence-pack",
        action="store_true",
        help="Fail-closed if required evidence artifacts are missing.",
    )
    ap.add_argument(
        "--visual-qa-gate-report",
        type=Path,
        default=None,
        help=(
            "Path to carla_visual_smoke_gate.json. When required, generated-map "
            "perception capture is blocked unless this report passes."
        ),
    )
    ap.add_argument(
        "--require-visual-qa-gate",
        action="store_true",
        help=(
            "Fail closed for --xodr-in captures unless the CARLA visual smoke "
            "gate report has ok=true."
        ),
    )
    ap.add_argument(
        "--record-route-timeout-s",
        type=float,
        default=None,
        help="Optional timeout override for record_route_fixed subprocess.",
    )
    ap.add_argument(
        "--min-frames",
        type=int,
        default=_env_int("UP_MIN_FRAMES", 8),
        help="Minimum RGB frames required for integrity gate (default: UP_MIN_FRAMES or 8).",
    )
    ap.add_argument(
        "--sensor-spawn-delay",
        type=float,
        default=float(os.environ.get("UP_SENSOR_SPAWN_DELAY_S", "0.5")),
        help="Seconds to wait between individual sensor spawns (default 0.5s). Increase for unstable maps.",
    )
    return ap.parse_args()


def main() -> int:
    args = _parse_args()
    requested_town_for_defaults = str(args.town or "").strip()
    if not requested_town_for_defaults:
        requested_town_for_defaults = str(args.manual_town or "").strip()
    unstable_map_defaults_applied = _apply_unstable_map_env_defaults(
        requested_town_for_defaults
    )
    # Propagate UP_SKIP_STREAM_CHECK env var (set by _apply_unstable_map_env_defaults
    # for Grid maps) into args so all downstream code sees the same value.
    if not args.skip_stream_check:
        args.skip_stream_check = os.environ.get("UP_SKIP_STREAM_CHECK", "").strip() == "1"
    thesis_strict_mode = bool(_env_bool("UP_THESIS_STRICT", False))
    if thesis_strict_mode:
        args.strict_artifacts = True
        args.fail_nonzero = True
        try:
            args.min_frames = max(8, int(args.min_frames))
        except Exception:
            args.min_frames = 8
    # Backwards-compatible strict mode (thesis): require full capture
    if getattr(args, "strict_artifacts", False):
        try:
            args.min_frames = int(args.frames)
        except Exception:
            pass
        args.fail_nonzero = True
        args.lidar_overlay = True
        args.spawn_qa_objects = True
        args.require_evidence_pack = True
    low_memory_profile_active = bool(
        _env_bool("UP_LOW_MEMORY_PROFILE", False)
        or bool(getattr(SETTINGS, "LOW_MEMORY_PROFILE_ACTIVE", False))
        or bool(getattr(args, "lowres", False))
    )
    low_memory_override_used = False
    if bool(low_memory_profile_active) and (not bool(args.lowres)):
        args.lowres = True
        low_memory_override_used = True
    configured_npc_cap = int(getattr(SETTINGS, "MAX_NPCS_LOCAL", LOCAL_PERCEPTION_MAX_NPCS))
    effective_npc_cap = int(
        min(configured_npc_cap, int(LOCAL_PERCEPTION_MAX_NPCS))
        if bool(low_memory_profile_active)
        else configured_npc_cap
    )
    exit_code = 0
    require_overlay = bool(getattr(args, "lidar_overlay", False))
    require_objects = bool(getattr(args, "spawn_qa_objects", False))
    require_evidence_pack = bool(getattr(args, "require_evidence_pack", False))
    require_manifest_gate = bool(
        require_evidence_pack or bool(getattr(args, "strict_artifacts", False))
    )
    out_dir, repo_root = _resolve_output_dir(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    last_run_pointer = _write_last_run_pointer(repo_root, out_dir)
    stream_port = _resolve_stream_port(int(args.port), args.streaming_port)
    calib_path, calib_source = _resolve_calib_path(args.calib)
    calib_path_metadata = _portable_path_for_metadata(calib_path, repo_root=repo_root)
    xodr_in_metadata = (
        _portable_path_for_metadata(args.xodr_in, repo_root=repo_root)
        if args.xodr_in
        else ""
    )
    visual_qa_gate_required = bool(
        bool(getattr(args, "require_visual_qa_gate", False))
        or _env_bool("UP_REQUIRE_VISUAL_QA_GATE_FOR_PERCEPTION", False)
    )
    visual_qa_gate_path = _resolve_visual_qa_gate_path(
        explicit_path=getattr(args, "visual_qa_gate_report", None),
        xodr_in=args.xodr_in,
        out_dir=out_dir,
        repo_root=repo_root,
    )
    upstream_visual_qa_gate = _load_visual_qa_gate_status(
        gate_path=visual_qa_gate_path,
        required=bool(visual_qa_gate_required),
        repo_root=repo_root,
    )
    sensor_rig_report_path_metadata = _portable_path_for_metadata(
        out_dir / "sensor_rig_report.json", repo_root=repo_root
    )
    thesis_gate = _thesis_capture_gate_snapshot(str(args.rig))
    sensor_rig_report_path = out_dir / "sensor_rig_report.json"
    sensor_rig_report_payload = _build_prelaunch_rig_report(
        rig=str(args.rig),
        calib_path=calib_path,
        calib_path_metadata=calib_path_metadata,
        calib_source=calib_source,
        gate=thesis_gate,
    )
    _write_json(sensor_rig_report_path, sensor_rig_report_payload)
    stream_timeout_s = _bounded_probe_timeout_s("UP_STREAM_TIMEOUT_S", 1.0)
    stream_wait_s = max(float(stream_timeout_s), float(_env_float("UP_STREAM_WAIT_S", 1.0)))
    if args.stream_wait_s is not None:
        try:
            stream_wait_s = max(float(stream_timeout_s), float(args.stream_wait_s))
        except Exception:
            pass
    stream_wait_s = max(float(stream_timeout_s), min(300.0, float(stream_wait_s)))
    prelaunch_stream_required_successes = max(
        1, _env_int("UP_STREAM_READY_SUCCESS_STREAK", 1)
    )
    current_world_stream_wait_s = max(
        float(stream_wait_s),
        float(_env_float("UP_THESIS_STREAMING_RECOVERY_WAIT_S", 30.0)),
    )
    rpc_timeout_s = _bounded_probe_timeout_s("UP_RPC_TIMEOUT_S", 1.0)
    stream_optional = bool(args.skip_stream_check or unstable_map_defaults_applied)
    map_probe_requested = bool(getattr(args, "map_probe", False))
    if (
        (not map_probe_requested)
        and (not bool(getattr(args, "use_current_world", False)))
        and str(args.expected_map_name or "").strip()
    ):
        map_probe_requested = True
    map_probe_timeout_s = max(5.0, _env_float("UP_MAP_PROBE_TIMEOUT_S", 90.0))
    if args.map_probe_timeout_s is not None:
        try:
            map_probe_timeout_s = max(5.0, float(args.map_probe_timeout_s))
        except Exception:
            pass
    rpc_reachable = False
    stream_reachable = False
    estimated_duration_s = float(args.frames) / float(max(float(args.fps), 1.0))
    env_record_route_timeout_s = _env_float("UP_RECORD_ROUTE_TIMEOUT_S", -1.0)
    record_route_timeout_s = _compute_record_route_timeout_s(
        frames=int(args.frames),
        fps=float(args.fps),
        duration_s=float(estimated_duration_s),
        override_timeout_s=(
            float(args.record_route_timeout_s)
            if args.record_route_timeout_s is not None
            else None
        ),
        env_timeout_s=(
            float(env_record_route_timeout_s)
            if float(env_record_route_timeout_s) > 0.0
            else None
        ),
    )
    map_load_timeout_s = max(
        60.0, float(os.environ.get("UP_CARLA_MAP_LOAD_TIMEOUT_S", "180.0"))
    )
    run_info_payload: Dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(repo_root),
        "output_dir_abs": str(out_dir),
        "last_run_pointer": str(last_run_pointer),
        "cwd": str(Path.cwd()),
        "argv": list(sys.argv),
        "manual_town": str(args.manual_town),
        "town": str(args.town or ""),
        "xodr_in": str(xodr_in_metadata),
        "expected_map_name": str(args.expected_map_name or ""),
        "map_probe_requested": bool(map_probe_requested),
        "visual_qa_gate_required": bool(visual_qa_gate_required),
        "visual_qa_gate": dict(upstream_visual_qa_gate),
        "rig": str(args.rig),
        "calib_path_resolved": str(calib_path_metadata),
        "calib_source": str(calib_source),
        "calib_exists": bool(calib_path.exists()),
        "thesis_capture_gate": dict(thesis_gate),
        "host": str(args.host),
        "port": int(args.port),
        "streaming_port": int(stream_port),
        "skip_stream_check": bool(args.skip_stream_check),
        "rpc_reachable": bool(rpc_reachable),
        "stream_reachable": bool(stream_reachable),
        "stream_optional": bool(stream_optional),
        "stream_timeout_s": float(stream_timeout_s),
        "stream_wait_s": float(stream_wait_s),
        "stream_required_successes": int(prelaunch_stream_required_successes),
        "front_only_strict": bool(args.front_only_strict),
        "force_fresh_capture": bool(args.force_fresh_capture),
        "low_memory_profile_active": bool(low_memory_profile_active),
        "low_memory_override_used": bool(low_memory_override_used),
        "low_memory_npc_cap": int(effective_npc_cap),
        "low_memory_camera_resolution_cap": dict(LOW_MEMORY_CAMERA_CAP),
        "timeouts": {
            "map_load_timeout_s": float(map_load_timeout_s),
            "map_probe_timeout_s": float(map_probe_timeout_s),
            "record_route_timeout_s": float(record_route_timeout_s),
            "rpc_probe_timeout_s": float(rpc_timeout_s),
            "stream_timeout_s": float(stream_timeout_s),
            "stream_wait_s": float(stream_wait_s),
        },
    }
    _write_json(out_dir / "run_info.json", run_info_payload)
    recording_dir = out_dir / "recording"
    lock_path: Optional[Path] = None
    lock_acquired = False
    timestamp = datetime.now(timezone.utc).isoformat()
    map_name = "UNKNOWN"
    world_settings_payload: Dict[str, Any] = {}

    status: Dict[str, Any] = {
        "ok": False,
        "carla_enabled": True,
        "carla_failed": False,
        "expected_map_name": str(args.expected_map_name or ""),
        "actual_map_name": "",
        "map_mismatch_detected": False,
        "failure_reason": None,
        "failure_detail": "",
        "timestamp": timestamp,
    }
    perception_status: Dict[str, Any] = {
        "ok": False,
        "failure_reason": None,
        "failure_detail": "",
        "warnings": [],
        "output_dir": str(out_dir),
        "png_files": 0,
        "semseg_files": 0,
        "ply_files": 0,
        "npz_files": 0,
        "corrupted_png_read": 0,
        "invalid_png_count": 0,
        "queue_depth_at_shutdown": 0,
        "write_integrity_status_path": "",
        "frames_recorded": 0,
        "frames_requested": int(args.frames),
        "record_route_returncode": None,
        "first_measurement_ok": False,
        "timestamp": timestamp,
        "missing_artifacts": [],
        "evidence_pack_ok": False,
        "front_camera_rgb_path": "",
        "front_camera_source_dir": "",
        "forward_alignment": {},
        "passing_camera_names": [],
        "failing_camera_names": [],
        "camera_exclusion_policy": "exclude_failing",
        "excluded_camera_names": [],
        "camera_claim_scope": "all_cameras",
        "recorder_manifest_path": "",
        "recorder_manifest_recording_path": "",
        "recorder_manifest_root_copy_path": "",
        "recorder_manifest_written": False,
        "recorder_manifest_synthesized": False,
        "recorder_manifest_source": "",
        "calib_override_path": str(args.calib_override or ""),
        "calib_override_applied": False,
        "calib_override_applied_to": [],
        "calib_path_resolved": str(calib_path_metadata),
        "calib_source": str(calib_source),
        "calib_exists": bool(calib_path.exists()),
        "thesis_capture_gate": dict(thesis_gate),
        "sensor_rig_report_path": str(sensor_rig_report_path_metadata),
        "rig_attach_attempted": False,
        "spawned_sensors": [],
        "listener_callbacks_registered": 0,
        "sensors_attached": "unknown",
        "sensors_attached_status": "unknown",
        "sensors_attached_reason": "not_evaluated",
        "sensors_attached_rule": (
            "all_reported_sensors_spawned_and_required_modalities_have_frames"
        ),
        "strict_artifacts_mode": bool(getattr(args, "strict_artifacts", False)),
        "required_artifacts": {
            "require_overlay": bool(require_overlay),
            "require_objects": bool(require_objects),
            "require_evidence_pack": bool(require_evidence_pack),
            "require_manifest_nonempty": bool(require_manifest_gate),
        },
        "rpc_reachable": bool(rpc_reachable),
        "stream_reachable": bool(stream_reachable),
        "stream_optional": bool(stream_optional),
        "stream_timeout_s": float(stream_timeout_s),
        "stream_wait_s": float(stream_wait_s),
        "stream_required_successes": int(prelaunch_stream_required_successes),
        "front_only_strict": bool(args.front_only_strict),
        "force_fresh_capture": bool(args.force_fresh_capture),
        "low_memory_profile_active": bool(low_memory_profile_active),
        "low_memory_override_used": bool(low_memory_override_used),
        "active_camera_limit": int(MAX_ACTIVE_CAMERAS),
        "active_camera_count": 0,
        "active_npc_count": int(effective_npc_cap),
        "active_npc_count_source": "configured_cap",
        "camera_resolution": (
            {"cap": dict(LOW_MEMORY_CAMERA_CAP)}
            if bool(low_memory_profile_active)
            else {}
        ),
        "map_probe_requested": bool(map_probe_requested),
        "map_probe_ok": None,
        "map_probe_result_path": "",
        "map_probe_stdout_path": "",
        "map_probe_stderr_path": "",
        "upstream_visual_qa_gate": dict(upstream_visual_qa_gate),
        "capture_world_settings": {},
        "synchronous_mode": False,
        "fixed_delta_seconds": 0.0,
        "settings_applied_before_tick": False,
        "world_settings_restored": False,
        "tick_watchdog_path": "",
        "ticks_observed": 0,
        "tick_advanced": False,
        "produced_artifacts": {},
        "building_proxy_spawn": {},
        "environment": {},
    }
    _apply_camera_claim_scope_status(perception_status, None)
    _apply_calib_override_status(
        perception_status,
        requested_path=str(args.calib_override or ""),
        override_info=None,
        base_calib_path=str(calib_path_metadata),
        base_calib_applied=bool(calib_path.exists()),
    )
    if getattr(args, "calib_override", None):
        calib_override_error = _validate_calib_override_file(str(args.calib_override))
        if calib_override_error:
            warning = f"calib_override_invalid:{calib_override_error}"
            if warning not in perception_status["warnings"]:
                perception_status["warnings"].append(warning)
    manifest_sync: Dict[str, Any] = {
        "path": "",
        "written": False,
        "synthesized": False,
        "error": "",
        "data": {},
    }
    pair_manifest: Dict[str, Any] = {
        "schema_version": 3,
        "generated_at": timestamp,
        "inputs": {
            "manual_town": args.manual_town,
            "town": args.town or "",
            "xodr_in": str(xodr_in_metadata),
            "rig_mode": args.rig,
            "expected_map_name": str(args.expected_map_name or ""),
            "map_probe_requested": bool(map_probe_requested),
            "calib_path_resolved": str(calib_path_metadata),
            "calib_source": str(calib_source),
            "calib_override": str(args.calib_override or ""),
            "use_current_world": bool(args.use_current_world),
            "front_only_strict": bool(args.front_only_strict),
            "force_fresh_capture": bool(args.force_fresh_capture),
            "frames": int(args.frames),
            "fps": float(args.fps),
            "visual_qa_gate_required": bool(visual_qa_gate_required),
            "visual_qa_gate_report": str(
                upstream_visual_qa_gate.get("path", "") or ""
            ),
        },
        "status": status,
    }
    route_use_current_world = bool(args.use_current_world)
    expected_map_substr = str(args.expected_map_name or "").strip()
    actor_ids_to_destroy: List[int] = []

    if args.xodr_in and visual_qa_gate_required and not bool(
        upstream_visual_qa_gate.get("ok", False)
    ):
        failure_reason = "visual_qa_gate_failed_or_missing"
        detail = str(upstream_visual_qa_gate.get("reason") or "")
        status["ok"] = False
        status["carla_failed"] = False
        status["failure_reason"] = failure_reason
        status["failure_detail"] = detail
        status["visual_qa_gate_status"] = "blocked"
        perception_status["ok"] = False
        perception_status["failure_reason"] = failure_reason
        perception_status["failure_detail"] = detail
        perception_status["result_class"] = "capture_failed"
        perception_status["result_class_reason"] = (
            "generated-map perception capture is blocked until CARLA visual QA passes"
        )
        perception_status["warnings"].append("perception_blocked_until_visual_qa_passes")
        _write_status_bundle(out_dir, status, pair_manifest, perception_status)
        _write_json(
            out_dir / "recording_summary.json",
            {
                "status": "FAIL",
                "failure_reason": failure_reason,
                "failure_detail": detail,
                "frames_recorded": 0,
                "frames_requested": int(args.frames),
                "fps": float(args.fps),
                "host": args.host,
                "port": int(args.port),
                "camera": "",
                "image_size": {"width": 0, "height": 0},
                "brightness_mean": 0.0,
                "brightness_std": 0.0,
                "laplacian_variance": 0.0,
                "screenshot_paths": [],
            },
        )
        return 2 if args.fail_nonzero else 0

    try:
        lock_acquired, lock_path = _acquire_run_lock(out_dir)
        if not lock_acquired:
            status["ok"] = False
            status["carla_failed"] = True
            status["failure_reason"] = "duplicate_invocation_locked"
            perception_status["ok"] = False
            perception_status["failure_reason"] = "duplicate_invocation_locked"
            _write_status_bundle(out_dir, status, pair_manifest, perception_status)
            _write_json(
                out_dir / "recording_summary.json",
                {
                    "status": "FAIL",
                    "failure_reason": "duplicate_invocation_locked",
                    "frames_recorded": 0,
                    "frames_requested": int(args.frames),
                    "fps": float(args.fps),
                    "host": args.host,
                    "port": int(args.port),
                    "camera": "",
                    "image_size": {"width": 0, "height": 0},
                    "brightness_mean": 0.0,
                    "brightness_std": 0.0,
                    "laplacian_variance": 0.0,
                    "screenshot_paths": [],
                },
            )
            raise _EarlyExit(2 if args.fail_nonzero else 0)

        if int(args.port) != 2000:
            failure_reason = f"rpc_port_contract_violation:expected_2000:got_{int(args.port)}"
            status["ok"] = False
            status["carla_failed"] = True
            status["failure_reason"] = failure_reason
            perception_status["ok"] = False
            perception_status["failure_reason"] = failure_reason
            pair_manifest["status"]["port_contract"] = {
                "ok": False,
                "rpc_port": int(args.port),
                "stream_port": int(stream_port),
                "expected_rpc_port": 2000,
                "expected_stream_port": 2001,
            }
            _write_json(out_dir / "run_info.json", run_info_payload)
            _write_status_bundle(out_dir, status, pair_manifest, perception_status)
            raise _EarlyExit(2 if args.fail_nonzero else 0)

        if int(stream_port) != 2001:
            failure_reason = f"stream_port_contract_violation:expected_2001:got_{int(stream_port)}"
            status["ok"] = False
            status["carla_failed"] = True
            status["failure_reason"] = failure_reason
            perception_status["ok"] = False
            perception_status["failure_reason"] = failure_reason
            pair_manifest["status"]["port_contract"] = {
                "ok": False,
                "rpc_port": int(args.port),
                "stream_port": int(stream_port),
                "expected_rpc_port": 2000,
                "expected_stream_port": 2001,
            }
            _write_json(out_dir / "run_info.json", run_info_payload)
            _write_status_bundle(out_dir, status, pair_manifest, perception_status)
            raise _EarlyExit(2 if args.fail_nonzero else 0)

        # Known-unstable map defensive handling (per GRID_PERCEPTION_RCA.md)
        # These maps must use --use-current-world after manual pre-load.
        requested_town_for_check = str(args.town or "").strip()
        if not requested_town_for_check and not args.xodr_in:
            requested_town_for_check = str(args.manual_town or "").strip()
        if (
            requested_town_for_check
            and _is_known_unstable_map(requested_town_for_check)
            and not args.use_current_world
            and not bool(args.xodr_in)
        ):
            failure_reason = "MAP_TRAVEL_RISK"
            failure_detail = (
                f"'{requested_town_for_check}' is known to crash CARLA during load_world(). "
                f"To capture on this map, pre-load it manually and use --use-current-world."
            )
            guidance = (
                "Operator action required:\n"
                "  1. Start CARLA manually\n"
                "  2. Load the map via CARLA GUI or external script\n"
                f"  3. Run: run_perception_safe.py --manual-town {requested_town_for_check} "
                f"--town {requested_town_for_check} --use-current-world --out <dir>"
            )
            print(f"[perception_safe] {failure_reason}: {failure_detail}")
            print(f"[perception_safe] {guidance}")
            status["ok"] = False
            status["carla_failed"] = True
            status["failure_reason"] = failure_reason
            status["failure_detail"] = failure_detail
            perception_status["ok"] = False
            perception_status["failure_reason"] = failure_reason
            perception_status["failure_detail"] = failure_detail
            perception_status["map_travel_risk_guidance"] = guidance
            _write_status_bundle(out_dir, status, pair_manifest, perception_status)
            _write_json(
                out_dir / "recording_summary.json",
                {
                    "status": "FAIL",
                    "failure_reason": failure_reason,
                    "failure_detail": failure_detail,
                    "frames_recorded": 0,
                    "frames_requested": int(args.frames),
                    "fps": float(args.fps),
                    "host": args.host,
                    "port": int(args.port),
                    "camera": "",
                    "image_size": {"width": 0, "height": 0},
                    "brightness_mean": 0.0,
                    "brightness_std": 0.0,
                    "laplacian_variance": 0.0,
                    "screenshot_paths": [],
                },
            )
            # Write minimal diagnostics
            _write_perception_diagnostics(
                out_dir,
                failure_reason=failure_reason,
                failure_detail=failure_detail,
                sensor_spawn_status={},
                listen_errors=[],
                per_sensor_frame_counts={},
                tick_progression={"ticks_attempted": 0, "frame_ids": [], "elapsed_seconds": []},
                map_state={"map_name_raw": "", "map_name_normalized": "", "map_match": False},
                sync_settings={"synchronous_mode": False, "fixed_delta_seconds": 0.0, "no_rendering_mode": False},
                ego_spawn={"x": 0.0, "y": 0.0, "z": 0.0},
                streaming_port_reachable=False,
                carla_log_path="",
            )
            raise _EarlyExit(EXIT_CODE_MAP_TRAVEL_RISK)

        if _env_bool("UP_DISABLE_CARLA", False):
            status["carla_enabled"] = False
            status["carla_failed"] = True
            status["failure_reason"] = "disabled_by_env"
            perception_status["failure_reason"] = "disabled_by_env"
            _write_status_bundle(out_dir, status, pair_manifest, perception_status)
            _write_json(
                out_dir / "recording_summary.json",
                {
                    "status": "SKIP",
                    "failure_reason": "disabled_by_env",
                    "frames_recorded": 0,
                    "frames_requested": int(args.frames),
                    "fps": float(args.fps),
                    "host": args.host,
                    "port": int(args.port),
                    "camera": "",
                    "image_size": {"width": 0, "height": 0},
                    "brightness_mean": 0.0,
                    "brightness_std": 0.0,
                    "laplacian_variance": 0.0,
                    "screenshot_paths": [],
                },
            )
            strict_rig_contract = _rig_verification_strict_mode(args)
            rig_verification_note = "SKIP: CARLA disabled via UP_DISABLE_CARLA=1"
            rig_verification_payload = _rig_verification_stub(
                "carla_disabled_by_env",
                rig_verification_note,
            )
            rig_contract_errors: List[str] = []
            try:
                rig_verification_payload, rig_contract_errors = (
                    _write_canonical_rig_verification(
                        out_dir=out_dir,
                        calib_path=calib_path,
                        rig_report_payload={
                            "rig": str(args.rig),
                            "sensors": [],
                            "reason": "carla_disabled_by_env",
                        },
                        existing_verification=rig_verification_payload,
                        note=rig_verification_note,
                    )
                )
            except Exception as exc:
                rig_write_error = f"rig_verification_write_failed:{exc}"
                if strict_rig_contract:
                    status["failure_reason"] = "rig_verification_write_failed"
                    perception_status["failure_reason"] = "rig_verification_write_failed"
                    perception_status["failure_detail"] = str(exc)
                    _write_status_bundle(out_dir, status, pair_manifest, perception_status)
                    raise _EarlyExit(EXIT_CODE_INFRA_FAILURE)
                rig_verification_payload = _rig_verification_stub(
                    "rig_verification_write_failed",
                    f"ERROR: {rig_write_error}",
                )
                _write_json(out_dir / "rig_verification.json", rig_verification_payload)
            if strict_rig_contract and rig_contract_errors:
                status["failure_reason"] = "rig_verification_non_compliant"
                perception_status["failure_reason"] = "rig_verification_non_compliant"
                perception_status["failure_detail"] = ";".join(rig_contract_errors)
                _write_status_bundle(out_dir, status, pair_manifest, perception_status)
                raise _EarlyExit(EXIT_CODE_INFRA_FAILURE)
            raise _EarlyExit(2 if args.fail_nonzero else 0)

        # Offline success path: if frames already exist, skip CARLA probes/capture and mark PASS.
        if (
            (not bool(args.force_fresh_capture))
            and _recording_satisfies_min_frames(recording_dir, int(args.min_frames))
        ):
            frames_recorded = (
                _count_files(_find_rgb_root(recording_dir), ("*.png",))
                if _find_rgb_root(recording_dir)
                else 0
            )
            manifest_sync = _sync_recorder_manifest(
                recording_dir,
                out_dir,
                fallback_timestamp=timestamp,
                map_name=map_name,
                world_settings_payload=world_settings_payload,
            )
            perception_status["recorder_manifest_path"] = str(manifest_sync.get("path", ""))
            perception_status["recorder_manifest_recording_path"] = str(
                manifest_sync.get("recording_path", "")
            )
            perception_status["recorder_manifest_root_copy_path"] = str(
                manifest_sync.get("root_copy_path", "")
            )
            perception_status["recorder_manifest_written"] = bool(
                manifest_sync.get("written", False)
            )
            perception_status["recorder_manifest_synthesized"] = bool(
                manifest_sync.get("synthesized", False)
            )
            perception_status["recorder_manifest_source"] = str(
                manifest_sync.get("data", {}).get("manifest_source", "")
                if isinstance(manifest_sync.get("data"), dict)
                else ""
            )
            if manifest_sync.get("error"):
                perception_status["warnings"].append(
                    f"recorder_manifest_write_failed:{manifest_sync.get('error')}"
                )
            if require_manifest_gate:
                capture_status_payload = _read_capture_status_payload(recording_dir)
                known_capture_failure = _enforce_manifest_gate_for_capture(
                    require_manifest_gate=bool(require_manifest_gate),
                    recording_dir=recording_dir,
                    out_dir=out_dir,
                    manifest_sync=manifest_sync,
                    capture_status_payload=capture_status_payload,
                )
                if known_capture_failure:
                    status["ok"] = False
                    status["carla_failed"] = True
                    status["failure_reason"] = str(known_capture_failure)
                    perception_status["ok"] = False
                    perception_status["failure_reason"] = str(known_capture_failure)
                    if str(known_capture_failure) not in perception_status["warnings"]:
                        perception_status["warnings"].append(str(known_capture_failure))
                    copied_log = copy_latest_carla_log(out_dir)
                    if copied_log:
                        perception_status["carla_latest_log_path"] = str(copied_log)
                else:
                    _assert_recorder_manifest_integrity(
                        recording_dir, out_dir, manifest_sync
                    )
            manifest_payload = (
                manifest_sync.get("data", {})
                if isinstance(manifest_sync.get("data"), dict)
                else {}
            )
            semseg_files = _semseg_file_count(recording_dir, manifest_payload)
            write_integrity = _build_write_integrity_status(
                recording_dir=recording_dir, manifest_payload=manifest_payload
            )
            _write_json(out_dir / WRITE_INTEGRITY_STATUS_JSON, write_integrity)
            perception_status["write_integrity_status_path"] = str(
                out_dir / WRITE_INTEGRITY_STATUS_JSON
            )
            perception_status["semseg_files"] = int(semseg_files)
            perception_status["corrupted_png_read"] = int(
                write_integrity.get("corrupted_png_read", 0) or 0
            )
            perception_status["invalid_png_count"] = int(
                write_integrity.get("invalid_png_count", 0) or 0
            )
            perception_status["queue_depth_at_shutdown"] = int(
                write_integrity.get("queue_depth_at_shutdown", 0) or 0
            )
            corrupted_png = int(write_integrity.get("corrupted_png_read", 0) or 0)
            # Offline short-circuit: existing RGB frames can satisfy default success
            # without semseg requirements. Strict/evidence modes keep hard gates.
            offline_reuse_block_reason = ""
            if require_manifest_gate:
                if int(semseg_files) <= 0:
                    offline_reuse_block_reason = "semseg_missing"
                elif corrupted_png != 0:
                    offline_reuse_block_reason = "corrupted_png_read"
            if offline_reuse_block_reason:
                reuse_warning = f"offline_reuse_blocked:{offline_reuse_block_reason}"
                if reuse_warning not in perception_status["warnings"]:
                    perception_status["warnings"].append(reuse_warning)
            else:
                if require_manifest_gate:
                    integrity_ok = bool(int(semseg_files) > 0 and corrupted_png == 0)
                    integrity_reason = ""
                else:
                    integrity_ok = bool(int(frames_recorded) >= int(args.min_frames))
                    integrity_reason = ""
                    if not integrity_ok:
                        integrity_reason = "insufficient_frames"
                    elif int(semseg_files) <= 0:
                        perception_status["warnings"].append("semseg_missing_optional")
                    if corrupted_png != 0:
                        perception_status["warnings"].append("corrupted_png_read_optional")
                status["ok"] = bool(integrity_ok)
                status["carla_failed"] = not bool(integrity_ok)
                status["failure_reason"] = None if integrity_ok else integrity_reason
                perception_status["ok"] = bool(integrity_ok)
                perception_status["failure_reason"] = None if integrity_ok else integrity_reason
                if not integrity_ok and integrity_reason not in perception_status["warnings"]:
                    perception_status["warnings"].append(integrity_reason)
                perception_status["frames_recorded"] = int(frames_recorded)
                _write_json(
                    out_dir / "recording_summary.json",
                    {
                        "status": "OK" if integrity_ok else "FAIL",
                        "failure_reason": "" if integrity_ok else integrity_reason,
                        "frames_recorded": int(frames_recorded),
                        "frames_requested": int(args.frames),
                        "fps": float(args.fps),
                        "host": args.host,
                        "port": int(args.port),
                        "camera": "",
                        "image_size": {"width": 0, "height": 0},
                        "brightness_mean": 0.0,
                        "brightness_std": 0.0,
                        "laplacian_variance": 0.0,
                        "screenshot_paths": [],
                        "note": "offline_postprocess",
                        "semseg_files": int(semseg_files),
                        "corrupted_png_read": int(
                            write_integrity.get("corrupted_png_read", 0) or 0
                        ),
                    },
                )
                _write_status_bundle(out_dir, status, pair_manifest, perception_status)
                raise _EarlyExit(2 if (args.fail_nonzero and not integrity_ok) else 0)

        _maybe_restart_carla_before_run(
            args=args,
            out_dir=out_dir,
            perception_status=perception_status,
            pair_manifest=pair_manifest,
            route_use_current_world=bool(route_use_current_world),
            stream_port=int(stream_port),
        )
        _assert_supported_carla_version()
        try:
            requested_town = str(args.town or "").strip()
            autostart_env_override_map = ""
            if (
                requested_town
                and (not bool(route_use_current_world))
                and not str(os.environ.get("UP_CARLA_DEFAULT_MAP", "") or "").strip()
            ):
                os.environ["UP_CARLA_DEFAULT_MAP"] = requested_town
                autostart_env_override_map = requested_town
            if bool(route_use_current_world):
                import carla  # type: ignore

                client = carla.Client(str(args.host), int(args.port))
                client.set_timeout(float(getattr(SETTINGS, "CARLA_TIMEOUT", 20.0)))
                try:
                    current_world = client.get_world()
                    current_world.get_map()
                except Exception as current_world_exc:
                    raise RuntimeError(
                        "CARLA not ready while --use-current-world is active. "
                        "Launch/load the target world manually and retry; "
                        "autostart/restart is intentionally bypassed in current-world mode. "
                        f"details={current_world_exc}"
                    ) from current_world_exc
                stream_wait_s = max(
                    float(stream_wait_s),
                    float(current_world_stream_wait_s),
                )
                _maybe_wait_for_current_world_streaming(
                    host=str(args.host),
                    stream_port=int(stream_port),
                    route_use_current_world=bool(route_use_current_world),
                    skip_stream_check=bool(args.skip_stream_check),
                    perception_status=perception_status,
                    wait_s=float(current_world_stream_wait_s),
                )
                pair_manifest["status"]["carla_ready"] = {
                    "ok": True,
                    "source": "direct_current_world_connection",
                    "host": str(args.host),
                    "port": int(args.port),
                }
            else:
                client = autostart_carla_if_needed(str(args.host), int(args.port))
                pair_manifest["status"]["carla_ready"] = {
                    "ok": True,
                    "source": "core.autostart_carla_if_needed",
                    "host": str(args.host),
                    "port": int(args.port),
                }
            pair_manifest["status"]["carla_client_ok"] = True
            requested_town = str(args.town or "").strip()
            if map_probe_requested and not requested_town:
                if "map_probe_skipped_no_town" not in perception_status["warnings"]:
                    perception_status["warnings"].append("map_probe_skipped_no_town")
            if (
                requested_town
                and _is_known_unstable_map(requested_town)
                and not bool(route_use_current_world)
            ):
                raise RuntimeError(
                    f"MAP_LOAD_FAILED: MAP_TRAVEL_RISK_{requested_town.upper()}: map travel to {requested_town} is blocked. "
                    f"Load {requested_town} manually and rerun with --use-current-world."
                )
            if map_probe_requested and requested_town:
                map_probe = _run_map_only_probe_subprocess(
                    out_dir=out_dir,
                    host=str(args.host),
                    port=int(args.port),
                    town=requested_town,
                    expected_map_name=expected_map_substr,
                    use_current_world=bool(route_use_current_world),
                    timeout_s=float(map_probe_timeout_s),
                )
                run_info_payload["map_probe"] = dict(map_probe)
                _write_json(out_dir / "run_info.json", run_info_payload)
                perception_status["map_probe_ok"] = bool(map_probe.get("ok", False))
                perception_status["map_probe_result_path"] = str(
                    map_probe.get("probe_result_path", "") or ""
                )
                perception_status["map_probe_stdout_path"] = str(
                    map_probe.get("stdout_path", "") or ""
                )
                perception_status["map_probe_stderr_path"] = str(
                    map_probe.get("stderr_path", "") or ""
                )
                pair_manifest["status"]["map_probe"] = dict(map_probe)
                status["expected_map_name"] = str(
                    map_probe.get("expected_map_name", expected_map_substr) or ""
                )
                status["actual_map_name"] = str(
                    map_probe.get("actual_map_name", "") or ""
                )
                status["map_mismatch_detected"] = bool(
                    map_probe.get("map_mismatch_detected", False)
                )
                if not bool(map_probe.get("ok", False)):
                    probe_failure_reason = str(
                        map_probe.get("failure_reason", "") or "ENGINE_FATAL"
                    )
                    probe_failure_detail = str(
                        map_probe.get("failure_detail", "") or ""
                    )
                    if probe_failure_reason == "WRONG_MAP_LOADED":
                        raise RuntimeError(f"WRONG_MAP_LOADED: {probe_failure_detail}")
                    probe_warning = (
                        f"map_probe_failed:{probe_failure_reason.lower()}"
                        if probe_failure_reason
                        else "map_probe_failed"
                    )
                    if probe_warning not in perception_status["warnings"]:
                        perception_status["warnings"].append(probe_warning)
                    pair_manifest["status"]["map_probe_warning"] = {
                        "reason": probe_failure_reason,
                        "detail": probe_failure_detail,
                    }
                else:
                    # Probe loads or validates the target map; avoid a second load_world call.
                    route_use_current_world = True
            world = client.get_world()
            (
                world,
                map_name,
                world_settings_payload,
                route_use_current_world,
            ) = _provision_requested_town_map(
                client=client,
                world=world,
                requested_town=requested_town,
                route_use_current_world=route_use_current_world,
                pair_status=pair_manifest["status"],
                xodr_path=(Path(args.xodr_in).resolve() if args.xodr_in else None),
                host=str(args.host),
                port=int(args.port),
            )
            status["actual_map_name"] = str(map_name or "")
            if expected_map_substr and (
                not _map_matches_requested(str(map_name), str(expected_map_substr))
            ):
                status["map_mismatch_detected"] = True
                raise RuntimeError(
                    f"WRONG_MAP_LOADED: expected '{expected_map_substr}', got '{map_name}'"
                )
        except Exception as e:
            err_text = str(e)
            if err_text.startswith("WRONG_MAP_LOADED:"):
                actual_map_name = str(
                    pair_manifest["status"].get("actual_map_name_raw", "")
                    or pair_manifest["status"].get("carla_map_name", "")
                    or status.get("actual_map_name", "")
                )
                if not actual_map_name:
                    got_match = re.search(r"got '([^']+)'", err_text)
                    if got_match:
                        actual_map_name = str(got_match.group(1) or "")
                status["expected_map_name"] = str(expected_map_substr or "")
                status["actual_map_name"] = actual_map_name
                status["map_mismatch_detected"] = True
                status["failure_reason"] = "WRONG_MAP_LOADED"
                status["carla_failed"] = True
                perception_status["ok"] = False
                perception_status["failure_reason"] = "WRONG_MAP_LOADED"
                if "WRONG_MAP_LOADED" not in perception_status.get("warnings", []):
                    perception_status["warnings"].append("WRONG_MAP_LOADED")
                pair_manifest["status"]["carla_ready"] = {
                    "ok": True,
                    "source": "core.autostart_carla_if_needed",
                    "host": str(args.host),
                    "port": int(args.port),
                }
                pair_manifest["status"]["carla_client_ok"] = True
                pair_manifest["status"]["map_mismatch_error"] = err_text
                print(err_text)
                _write_status_bundle(out_dir, status, pair_manifest, perception_status)
                raise _EarlyExit(2)
            if err_text.startswith("MAP_LOAD_FAILED:"):
                map_travel_risk_reason = _extract_map_travel_risk_reason(err_text)
                if map_travel_risk_reason:
                    requested_town_hint = str(
                        args.town or args.manual_town or map_travel_risk_reason.removeprefix("MAP_TRAVEL_RISK_")
                    ).strip()
                    status["failure_reason"] = map_travel_risk_reason
                    status["failure_detail"] = err_text
                    status["carla_failed"] = False
                    perception_status["ok"] = False
                    perception_status["failure_reason"] = map_travel_risk_reason
                    perception_status["failure_detail"] = err_text
                    perception_status["operator_instruction"] = (
                        f"Load {requested_town_hint} manually in CARLA, then rerun with --use-current-world."
                    )
                    if map_travel_risk_reason not in perception_status.get("warnings", []):
                        perception_status["warnings"].append(map_travel_risk_reason)
                    pair_manifest["status"]["map_load_error"] = err_text
                    _write_json(
                        out_dir / "recording_summary.json",
                        {
                            "status": "SKIP",
                            "failure_reason": map_travel_risk_reason,
                            "failure_detail": err_text,
                            "frames_recorded": 0,
                            "frames_requested": int(args.frames),
                            "fps": float(args.fps),
                            "host": args.host,
                            "port": int(args.port),
                            "camera": "",
                            "image_size": {"width": 0, "height": 0},
                            "brightness_mean": 0.0,
                            "brightness_std": 0.0,
                            "laplacian_variance": 0.0,
                            "screenshot_paths": [],
                        },
                    )
                    print(err_text)
                    _write_status_bundle(out_dir, status, pair_manifest, perception_status)
                    raise _EarlyExit(EXIT_CODE_MAP_TRAVEL_RISK)
                status["failure_reason"] = "MAP_LOAD_FAILED"
                status["failure_detail"] = err_text
                status["carla_failed"] = True
                perception_status["ok"] = False
                perception_status["failure_reason"] = "MAP_LOAD_FAILED"
                perception_status["failure_detail"] = err_text
                if "MAP_LOAD_FAILED" not in perception_status.get("warnings", []):
                    perception_status["warnings"].append("MAP_LOAD_FAILED")
                pair_manifest["status"]["carla_ready"] = {
                    "ok": True,
                    "source": "core.autostart_carla_if_needed",
                    "host": str(args.host),
                    "port": int(args.port),
                }
                pair_manifest["status"]["carla_client_ok"] = True
                pair_manifest["status"]["map_load_error"] = err_text
                print(err_text)
                _write_status_bundle(out_dir, status, pair_manifest, perception_status)
                raise _EarlyExit(2)
            if err_text.startswith("ENGINE_FATAL:"):
                status["failure_reason"] = "ENGINE_FATAL"
                status["failure_detail"] = err_text
                status["carla_failed"] = True
                perception_status["ok"] = False
                perception_status["failure_reason"] = "ENGINE_FATAL"
                perception_status["failure_detail"] = err_text
                if "ENGINE_FATAL" not in perception_status.get("warnings", []):
                    perception_status["warnings"].append("ENGINE_FATAL")
                pair_manifest["status"]["engine_fatal_error"] = err_text
                print(err_text)
                _write_status_bundle(out_dir, status, pair_manifest, perception_status)
                raise _EarlyExit(2)
            pair_manifest["status"]["carla_ready"] = {
                "ok": False,
                "source": "core.autostart_carla_if_needed",
                "host": str(args.host),
                "port": int(args.port),
                "error": str(e),
            }
            status["failure_reason"] = "carla_not_reachable"
            status["host"] = str(args.host)
            status["port"] = int(args.port)
            status["carla_failed"] = True
            perception_status["failure_reason"] = "CARLA server not reachable"
            perception_status["sensors_attached"] = False
            perception_status["sensors_attached_status"] = "false"
            perception_status["sensors_attached_reason"] = "carla_not_reachable"
            print(f"ERROR: CARLA not reachable at {args.host}:{int(args.port)}")
            _write_status_bundle(out_dir, status, pair_manifest, perception_status)
            raise _EarlyExit(2 if args.fail_nonzero else 0)

        # If CARLA client/world access already succeeded, RPC is effectively reachable.
        rpc_reachable = bool(pair_manifest["status"].get("carla_client_ok", False)) or _tcp_port_open(
            str(args.host), int(args.port), timeout_s=float(rpc_timeout_s)
        )
        # The outer wrapper only needs one confirmed stream connection; deeper
        # sensor spawn still performs its own readiness checks inside record_route.
        stream_required_successes = int(prelaunch_stream_required_successes)
        stream_reachable = _wait_for_port_open(
            str(args.host),
            int(stream_port),
            wait_s=float(stream_wait_s),
            probe_timeout_s=float(stream_timeout_s),
            required_successes=int(stream_required_successes),
        )
        run_info_payload["rpc_reachable"] = bool(rpc_reachable)
        run_info_payload["stream_reachable"] = bool(stream_reachable)
        run_info_payload["stream_optional"] = bool(stream_optional)
        run_info_payload["stream_timeout_s"] = float(stream_timeout_s)
        run_info_payload["stream_wait_s"] = float(stream_wait_s)
        run_info_payload["stream_required_successes"] = int(stream_required_successes)
        _write_json(out_dir / "run_info.json", run_info_payload)
        perception_status["rpc_reachable"] = bool(rpc_reachable)
        perception_status["stream_reachable"] = bool(stream_reachable)
        perception_status["stream_optional"] = bool(stream_optional)
        perception_status["stream_timeout_s"] = float(stream_timeout_s)
        perception_status["stream_wait_s"] = float(stream_wait_s)
        perception_status["stream_required_successes"] = int(stream_required_successes)
        pair_manifest["status"]["port_contract"] = {
            "ok": bool(rpc_reachable and (stream_reachable or stream_optional)),
            "rpc_port": int(args.port),
            "stream_port": int(stream_port),
            "expected_rpc_port": 2000,
            "expected_stream_port": 2001,
            "rpc_reachable": bool(rpc_reachable),
            "stream_reachable": bool(stream_reachable),
            "stream_optional": bool(stream_optional),
            "stream_timeout_s": float(stream_timeout_s),
            "stream_wait_s": float(stream_wait_s),
            "stream_required_successes": int(stream_required_successes),
        }

        if not rpc_reachable:
            failure_reason = f"carla_rpc_unreachable:{args.host}:{int(args.port)}"
            status["carla_failed"] = True
            status["failure_reason"] = failure_reason
            perception_status["ok"] = False
            perception_status["failure_reason"] = failure_reason
            _write_status_bundle(out_dir, status, pair_manifest, perception_status)
            _write_json(
                out_dir / "recording_summary.json",
                {
                    "status": "FAIL",
                    "failure_reason": failure_reason,
                    "frames_recorded": 0,
                    "frames_requested": int(args.frames),
                    "fps": float(args.fps),
                    "host": args.host,
                    "port": int(args.port),
                    "camera": "",
                    "image_size": {"width": 0, "height": 0},
                    "brightness_mean": 0.0,
                    "brightness_std": 0.0,
                    "laplacian_variance": 0.0,
                    "screenshot_paths": [],
                },
            )
            raise _EarlyExit(2 if args.fail_nonzero else 0)

        failure_reason = _handle_outer_stream_gate(
            args=args,
            out_dir=out_dir,
            status=status,
            pair_manifest=pair_manifest,
            perception_status=perception_status,
            stream_reachable=bool(stream_reachable),
            stream_optional=bool(stream_optional),
            stream_port=int(stream_port),
        )
        if failure_reason:
            raise _EarlyExit(2 if args.fail_nonzero else 0)
        elif (not stream_reachable) and (
            "streaming_unreachable_optional" not in perception_status.get("warnings", [])
        ):
            perception_status["warnings"].append("streaming_unreachable_optional")

        # ---------------------------------------------------------------------
        # Runtime Enrichment Spawning
        # ---------------------------------------------------------------------
        enrich_spawn_report = _spawn_runtime_enrichments(
            host=args.host,
            port=int(args.port),
            out_dir=out_dir,
            enrichments_json=args.enrichments_json,
            limit=int(args.spawn_enrichments_limit),
            seed=int(args.spawn_enrichments_seed),
            type_filter_str=args.spawn_enrichments_filter,
            required_types_str=args.spawn_enrichments_required_types,
            enabled=bool(args.spawn_enrichments),
        )
        perception_status["enrichment_spawn"] = enrich_spawn_report
        if enrich_spawn_report.get("spawned_ids"):
            actor_ids_to_destroy.extend(enrich_spawn_report["spawned_ids"])
        
        # ---------------------------------------------------------------------
        # Post-Enrichment QA Capture
        # ---------------------------------------------------------------------
        qa_report = {"enabled": False, "qa_bundle_written": False}
        if bool(args.qa_capture_after_enrichment):
            print("[run_perception_safe] Capturing post-enrichment QA bundle...")
            qa_report = capture_qa_bundle(
                host=args.host,
                port=int(args.port),
                calib_path=str(calib_path),
                out_dir=out_dir,
                rig_type=args.rig,
            )
            perception_status["enrichment_visibility_qa"] = qa_report
            _write_json(out_dir / "enrichments_visibility_qa.json", qa_report)

        # ---------------------------------------------------------------------
        # Scene Readiness Reporting
        # ---------------------------------------------------------------------
        strict_scene_gate = bool(
            bool(args.fail_on_missing_required_enrichments)
            or bool(getattr(args, "require_evidence_pack", False))
        )
        thesis_rig_requested = bool(args.rig == "thesis")
        thesis_gate_enabled = bool(thesis_gate.get("enabled", False))
        calib_present = bool(calib_path.exists())
        qa_bundle_written = bool(qa_report.get("qa_bundle_written", False))
        scene_readiness = _build_scene_readiness_report(
            thesis_rig_requested=thesis_rig_requested,
            thesis_gate_enabled=thesis_gate_enabled,
            calib_present=calib_present,
            enrichments_enabled=bool(args.spawn_enrichments),
            enrich_spawn_report=enrich_spawn_report,
            qa_bundle_written=qa_bundle_written,
            qa_capture_after_enrichment=bool(args.qa_capture_after_enrichment),
            strict_scene_gate=bool(strict_scene_gate),
        )
        scene_readiness_path = out_dir / "scene_readiness_report.json"
        _write_json(scene_readiness_path, scene_readiness)
        perception_status["scene_readiness"] = scene_readiness
        perception_status["scene_readiness_report_path"] = str(scene_readiness_path)

        if strict_scene_gate and not bool(scene_readiness.get("safe_to_start_recording", False)):
            readiness_reason = str(scene_readiness.get("failure_reason", "")).strip()
            failure_reason = "scene_readiness_failed"
            if readiness_reason:
                failure_reason = f"scene_readiness_failed:{readiness_reason}"
            status["failure_reason"] = failure_reason
            status["carla_failed"] = True
            perception_status["ok"] = False
            perception_status["failure_reason"] = "scene_readiness_failed"
            perception_status["failure_detail"] = readiness_reason
            _write_status_bundle(out_dir, status, pair_manifest, perception_status)
            raise _EarlyExit(EXIT_CODE_INFRA_FAILURE)

        perception_status["environment"] = {}

        if bool(thesis_gate.get("gate_required", False)) and not bool(
            thesis_gate.get("enabled", False)
        ):
            sensor_rig_report_payload["reason"] = "rig_attach_gated"
            sensor_rig_report_payload["ok"] = False
            _write_json(sensor_rig_report_path, sensor_rig_report_payload)
            gate_warning = "rig_attach_gated:UP_ENABLE_THESIS_PERCEPTION_CAPTURE"
            if gate_warning not in perception_status.get("warnings", []):
                perception_status["warnings"].append(gate_warning)
            # Keep strict/evidence capture fail-closed, but allow default flows.
            if bool(getattr(args, "strict_artifacts", False)) or bool(
                getattr(args, "require_evidence_pack", False)
            ):
                status["failure_reason"] = "rig_attach_gated"
                status["carla_failed"] = True
                perception_status["failure_reason"] = "rig_attach_gated"
                perception_status["sensors_attached_reason"] = gate_warning
                _write_status_bundle(out_dir, status, pair_manifest, perception_status)
                raise _EarlyExit(2 if args.fail_nonzero else 0)

        if not calib_path.exists():
            sensor_rig_report_payload["reason"] = "calib_missing"
            sensor_rig_report_payload["ok"] = False
            _write_json(sensor_rig_report_path, sensor_rig_report_payload)
            status["failure_reason"] = "calib_missing"
            status["carla_failed"] = True
            perception_status["failure_reason"] = "calib_missing"
            perception_status["sensors_attached_reason"] = "calib_missing"
            _write_status_bundle(out_dir, status, pair_manifest, perception_status)
            raise _EarlyExit(2 if args.fail_nonzero else 0)

        if (
            args.town
            and _is_known_unstable_map(str(args.town))
            and not route_use_current_world
        ):
            print(
                f"[run_perception_safe] NOTE: {args.town} is a known-unstable map — more stable with --use-current-world."
            )

        if args.xodr_in and not args.town and not args.manual_via_xodr:
            try:
                from ultimate_pipeline.experiments.thesis.manual_refs import (
                    resolve_manual_town,
                )

                ref = resolve_manual_town(args.manual_town)
                if str(Path(args.xodr_in).resolve()) == str(
                    Path(ref["manual_xodr_path"]).resolve()
                ):
                    args.town = ref["cooked_town"]
                    args.xodr_in = None
            except Exception:
                pass

        if args.elevation_gate and args.xodr_in:
            elev_report = check_elevation_missing_and_cliffs(
                str(args.xodr_in.resolve()),
                max_zero_ratio=_env_float("UP_ELEV_MAX_ZERO_RATIO", 0.01),
                max_link_dz_m=_env_float("UP_ELEV_MAX_LINK_DZ_M", 50.0),
            )
            _write_json(out_dir / "elevation_gate.json", elev_report)
            if not elev_report.get("ok", True):
                status["failure_reason"] = "elevation_gate_failed"
                status["carla_failed"] = True
                perception_status["failure_reason"] = "elevation_gate_failed"
                _write_status_bundle(out_dir, status, pair_manifest, perception_status)
                raise _EarlyExit(2 if args.fail_nonzero else 0)

        # Normalize geoReference to single-line before CARLA import (avoid parse warnings)
        if args.xodr_in:
            try:
                import xml.etree.ElementTree as ET
                from ultimate_pipeline.core.georef_utils import (
                    normalize_georeference,
                    parse_georeference,
                )

                xodr_src = Path(args.xodr_in).resolve()
                tree = ET.parse(str(xodr_src))
                root = tree.getroot()
                header = root.find("header")
                geo_text = None
                if header is not None:
                    geo = header.find("geoReference")
                    if geo is not None and geo.text:
                        geo_text = geo.text
                        geo.text = normalize_georeference(geo.text)
                normalized_path = out_dir / "_normalized_input.xodr"
                tree.write(str(normalized_path), encoding="utf-8", xml_declaration=True)
                args.xodr_in = normalized_path
                valid, params_complete, _ = parse_georeference(geo_text)
                if valid and not params_complete:
                    perception_status["warnings"].append("georef_incomplete")
            except Exception as e:
                perception_status["warnings"].append(
                    f"georef_normalize_failed:{e.__class__.__name__}"
                )

        recording_dir = out_dir / "recording"
        recording_dir.mkdir(parents=True, exist_ok=True)
        duration_s = float(args.frames) / float(max(float(args.fps), 1.0))

        cmd = [sys.executable, "-m", "ultimate_pipeline.perception.record_route_fixed"]
        if args.town:
            cmd += ["--town", str(args.town)]
            if route_use_current_world:
                cmd.append("--use-current-world")
            expected_capture_map = str(args.expected_map_name or "").strip()
            if expected_capture_map:
                cmd += ["--expected-map-name", expected_capture_map]
        else:
            xodr_cmd_path = Path(args.xodr_in)
            if not xodr_cmd_path.is_absolute():
                xodr_cmd_path = Path.cwd() / xodr_cmd_path
            cmd += ["--xodr", str(xodr_cmd_path)]
            if route_use_current_world:
                cmd.append("--use-current-world")
        tick_timeout_s = max(0.5, _env_float("UP_CAPTURE_TICK_TIMEOUT_S", 2.0))
        max_tick_timeouts = max(1, _env_int("UP_CAPTURE_MAX_TICK_TIMEOUTS", 3))
        first_measurement_timeout_s = max(
            10.0,
            _env_float(
                "UP_CAPTURE_FIRST_MEASUREMENT_TIMEOUT_S",
                10.0,
            ),
        )

        cmd += [
            "--calib",
            str(calib_path),
            "--out-dir",
            str(recording_dir),
            "--host",
            str(args.host),
            "--port",
            str(int(args.port)),
            "--stream-port",
            str(int(stream_port)),
            "--fps",
            str(int(max(1, round(float(args.fps))))),
            "--duration",
            f"{duration_s:.3f}",
            "--rig",
            str(args.rig),
            "--tick-timeout-s",
            str(float(tick_timeout_s)),
            "--max-consecutive-tick-timeouts",
            str(int(max_tick_timeouts)),
            "--first-measurement-timeout-s",
            str(float(first_measurement_timeout_s)),
            "--sensor-spawn-delay",
            str(float(args.sensor_spawn_delay)),
        ]
        if args.skip_stream_check:
            cmd.append("--skip-stream-check")
        enable_semseg = (not bool(args.no_seg)) and (not bool(args.front_only_strict))
        if enable_semseg:
            cmd.append("--seg")
        if args.lowres:
            cmd.append("--low-mem")
        if args.spawn_qa_objects:
            cmd.append("--spawn-sanity-objects")
        if bool(args.front_only_strict):
            cmd.append("--front-only")

        print(f"Calib path resolved to: {calib_path}", flush=True)
        print("Rig attach attempted: pending (prelaunch)", flush=True)

        t0 = time.monotonic()
        timed_out = False
        timeout_diagnostics_path = ""
        capture_timeout_s = float(record_route_timeout_s)
        pair_manifest["status"]["record_route_timeout_s"] = float(capture_timeout_s)
        record_route_env = dict(os.environ)
        if bool(low_memory_profile_active):
            record_route_env["UP_LOW_MEMORY_PROFILE"] = "1"
        record_route_env["UP_SENSOR_SPAWN_DELAY_S"] = str(
            float(args.sensor_spawn_delay)
        )
        if bool(args.front_only_strict):
            record_route_env["UP_FRONT_ONLY_STRICT"] = "1"
        else:
            record_route_env.pop("UP_FRONT_ONLY_STRICT", None)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=float(capture_timeout_s),
                env=record_route_env,
            )
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            proc = subprocess.CompletedProcess(
                cmd,
                124,
                str(getattr(exc, "stdout", "") or ""),
                str(getattr(exc, "stderr", "") or ""),
            )
        (out_dir / "record_route_stdout.txt").write_text(
            proc.stdout or "", encoding="utf-8", errors="replace"
        )
        (out_dir / "record_route_stderr.txt").write_text(
            proc.stderr or "", encoding="utf-8", errors="replace"
        )
        perception_status["record_route_stdout_path"] = str(
            out_dir / "record_route_stdout.txt"
        )
        perception_status["record_route_stderr_path"] = str(
            out_dir / "record_route_stderr.txt"
        )
        (
            stdout_rig_attempted,
            stdout_spawned_sensors,
            stdout_listener_count,
        ) = _extract_rig_attach_diagnostics_from_stdout(str(proc.stdout or ""))

        stderr_tail = str(proc.stderr or "").strip()[-4000:]
        status["failure_detail"] = stderr_tail
        perception_status["failure_detail"] = stderr_tail
        status["record_route_returncode"] = int(proc.returncode)
        status["elapsed_s"] = round(time.monotonic() - t0, 3)
        perception_status["record_route_returncode"] = int(proc.returncode)
        if timed_out and "record_route_timeout" not in perception_status["warnings"]:
            perception_status["warnings"].append("record_route_timeout")
        capture_status_payload = _read_capture_status_payload(recording_dir)
        capture_status_path = recording_dir / "capture_status.json"
        perception_status["capture_status_path"] = (
            str(capture_status_path) if capture_status_path.is_file() else ""
        )
        if isinstance(capture_status_payload, dict) and capture_status_payload:
            perception_status["capture_status"] = str(
                capture_status_payload.get("status", "") or ""
            )
            perception_status["capture_failure_reason"] = str(
                capture_status_payload.get("failure_reason", "") or ""
            )
            perception_status["capture_failure_detail"] = str(
                capture_status_payload.get("failure_detail", "") or ""
            )
            perception_status["capture_tick_watchdog_path"] = str(
                capture_status_payload.get("tick_watchdog_path", "") or ""
            )
            perception_status["capture_sensor_rig_report_path"] = str(
                capture_status_payload.get("sensor_rig_report_path", "") or ""
            )
        manifest_sync = _sync_recorder_manifest(
            recording_dir,
            out_dir,
            fallback_timestamp=timestamp,
            map_name=map_name,
            world_settings_payload=world_settings_payload,
        )
        perception_status["recorder_manifest_path"] = str(manifest_sync.get("path", ""))
        perception_status["recorder_manifest_recording_path"] = str(
            manifest_sync.get("recording_path", "")
        )
        perception_status["recorder_manifest_root_copy_path"] = str(
            manifest_sync.get("root_copy_path", "")
        )
        perception_status["recorder_manifest_written"] = bool(
            manifest_sync.get("written", False)
        )
        perception_status["recorder_manifest_synthesized"] = bool(
            manifest_sync.get("synthesized", False)
        )
        perception_status["recorder_manifest_source"] = str(
            manifest_sync.get("data", {}).get("manifest_source", "")
            if isinstance(manifest_sync.get("data"), dict)
            else ""
        )
        if manifest_sync.get("error"):
            perception_status["warnings"].append(
                f"recorder_manifest_write_failed:{manifest_sync.get('error')}"
            )
        pre_manifest_runtime_failure = ""
        if bool(timed_out) or int(proc.returncode) != 0:
            pre_manifest_runtime_failure = _classify_record_route_failure(
                timed_out=bool(timed_out),
                proc_returncode=int(proc.returncode),
                outputs_present=False,
                integrity_ok=True,
                integrity_reason="",
                first_measurement_ok=False,
                frames_recorded=0,
                stdout_text=str(proc.stdout or ""),
                stderr_text=str(proc.stderr or ""),
                skip_stream_check=bool(args.skip_stream_check),
            )
        known_capture_failure = _enforce_manifest_gate_for_capture(
            require_manifest_gate=bool(require_manifest_gate),
            recording_dir=recording_dir,
            out_dir=out_dir,
            manifest_sync=manifest_sync,
            capture_status_payload=capture_status_payload,
            runtime_failure_hint=pre_manifest_runtime_failure,
        )
        if known_capture_failure:
            status["ok"] = False
            status["carla_failed"] = True
            status["failure_reason"] = str(known_capture_failure)
            perception_status["ok"] = False
            perception_status["failure_reason"] = str(known_capture_failure)
            if str(known_capture_failure) not in perception_status["warnings"]:
                perception_status["warnings"].append(str(known_capture_failure))
            copied_log = copy_latest_carla_log(out_dir)
            if copied_log:
                perception_status["carla_latest_log_path"] = str(copied_log)
            perception_status["diagnostics"] = {
                "capture_status_path": str(capture_status_path)
                if capture_status_path.is_file()
                else "",
                "sensor_rig_report_path": str(out_dir / "sensor_rig_report.json"),
                "record_route_stdout_path": str(out_dir / "record_route_stdout.txt"),
                "record_route_stderr_path": str(out_dir / "record_route_stderr.txt"),
                "carla_latest_log_path": str(
                    perception_status.get("carla_latest_log_path", "") or ""
                ),
            }
        manifest_payload = (
            manifest_sync.get("data", {})
            if isinstance(manifest_sync.get("data"), dict)
            else {}
        )
        semseg_files = _semseg_file_count(recording_dir, manifest_payload)
        write_integrity = _build_write_integrity_status(
            recording_dir=recording_dir,
            manifest_payload=manifest_payload,
        )
        _write_json(out_dir / WRITE_INTEGRITY_STATUS_JSON, write_integrity)
        perception_status["write_integrity_status_path"] = str(
            out_dir / WRITE_INTEGRITY_STATUS_JSON
        )
        perception_status["semseg_files"] = int(semseg_files)
        perception_status["corrupted_png_read"] = int(
            write_integrity.get("corrupted_png_read", 0) or 0
        )
        perception_status["invalid_png_count"] = int(
            write_integrity.get("invalid_png_count", 0) or 0
        )
        perception_status["queue_depth_at_shutdown"] = int(
            write_integrity.get("queue_depth_at_shutdown", 0) or 0
        )
        integrity_ok = bool(
            int(semseg_files) > 0
            and int(write_integrity.get("corrupted_png_read", 0) or 0) == 0
        )
        integrity_reason = ""
        if int(semseg_files) <= 0:
            integrity_reason = "semseg_missing"
        elif int(write_integrity.get("corrupted_png_read", 0) or 0) != 0:
            integrity_reason = "corrupted_png_read"
        if not integrity_ok and integrity_reason not in perception_status["warnings"]:
            perception_status["warnings"].append(integrity_reason)

        rig_src = recording_dir / "sensor_rig_report.json"
        if not rig_src.exists():
            rig_src = recording_dir / "thesis_rig_report.json"
        rig_dst = out_dir / "sensor_rig_report.json"
        rig_attach_failure_reason = ""
        rig_attach_attempted = bool(stdout_rig_attempted)
        spawned_sensors: List[str] = list(stdout_spawned_sensors)
        listener_callbacks_registered = int(stdout_listener_count)
        strict_rig_contract_mode = _rig_verification_strict_mode(args)
        if rig_src.exists():
            try:
                rig_data_loaded = json.loads(
                    rig_src.read_text(encoding="utf-8", errors="replace")
                )
            except Exception:
                rig_data_loaded = {}
            if isinstance(rig_data_loaded, dict):
                rig_attach_attempted = bool(
                    rig_data_loaded.get("rig_attach_attempted", rig_attach_attempted)
                )
                rig_reason = str(rig_data_loaded.get("reason", "") or "").strip()
                rig_error_text = str(rig_data_loaded.get("error", "") or "").strip()
                rig_timeout_detected = any(
                    marker in f"{rig_reason} {rig_error_text}".lower()
                    for marker in (
                        "first_frame_timeout",
                        "thesis_rig_spawn_timeout",
                        "first sample timeout",
                        "first_measurement_no_callbacks",
                        "spawn_timeout",
                    )
                )
                if not bool(rig_data_loaded.get("ok", True)):
                    if rig_reason in ("", "prelaunch"):
                        rig_reason = "rig_attach_gated"
                        rig_data_loaded["reason"] = rig_reason
                    if rig_reason.startswith("calib_missing"):
                        rig_attach_failure_reason = "calib_missing"
                    elif rig_timeout_detected:
                        rig_attach_failure_reason = "sensor_spawn_timeout"
                    elif rig_reason.startswith("attach_attempt_started"):
                        rig_attach_failure_reason = "sensor_spawn_failed"
                    elif rig_reason.startswith("sensor_spawn_failed") or rig_reason.startswith(
                        "rig_attach_failed"
                    ):
                        rig_attach_failure_reason = "sensor_spawn_failed"
                    elif rig_reason:
                        rig_attach_failure_reason = "rig_attach_gated"
                spawned_raw = rig_data_loaded.get("spawned_sensors", [])
                if isinstance(spawned_raw, list):
                    parsed_spawned = [str(x) for x in spawned_raw]
                    if parsed_spawned:
                        spawned_sensors = parsed_spawned
                if not rig_attach_attempted and not spawned_sensors and rig_attach_failure_reason == "":
                    rig_attach_failure_reason = "rig_attach_gated"
                if rig_attach_attempted and spawned_sensors and rig_attach_failure_reason == "rig_attach_gated":
                    rig_attach_failure_reason = ""
                listener_callbacks_registered = _safe_int(
                    rig_data_loaded.get(
                        "listener_callbacks_registered", listener_callbacks_registered
                    ),
                    default=listener_callbacks_registered,
                )
                if not spawned_sensors:
                    sensor_entries = rig_data_loaded.get("sensors", [])
                    if isinstance(sensor_entries, list):
                        spawned_sensors = sorted(
                            [
                                str(item.get("name", ""))
                                for item in sensor_entries
                                if isinstance(item, dict) and str(item.get("name", "")).strip()
                            ]
                        )
                rig_data_loaded["calib_path_resolved"] = str(calib_path_metadata)
                rig_data_loaded["calib_source"] = str(calib_source)
                rig_data_loaded["calib_exists"] = bool(calib_path.exists())
                rig_data_loaded["gating_conditions"] = dict(thesis_gate)
                rig_data_loaded["spawned_sensors"] = list(spawned_sensors)
                rig_data_loaded["listener_callbacks_registered"] = int(
                    listener_callbacks_registered
                )
                _write_json(rig_dst, rig_data_loaded)
                scene_readiness = _finalize_scene_readiness_attachment(
                    scene_readiness,
                    thesis_rig_requested=thesis_rig_requested,
                    rig_report_payload=rig_data_loaded,
                    spawned_sensors=spawned_sensors,
                )
                _write_json(scene_readiness_path, scene_readiness)
                perception_status["scene_readiness"] = scene_readiness
            else:
                rig_dst.write_text(
                    rig_src.read_text(encoding="utf-8", errors="replace"),
                    encoding="utf-8",
                )
            print(
                f"Rig attach attempted: {'yes' if rig_attach_attempted else 'no'}",
                flush=True,
            )
            print(f"Spawned sensors: {spawned_sensors}", flush=True)
            print(
                f"Listener callbacks registered: {int(listener_callbacks_registered)}",
                flush=True,
            )
            perception_status["rig_attach_attempted"] = bool(rig_attach_attempted)
            perception_status["spawned_sensors"] = list(spawned_sensors)
            perception_status["listener_callbacks_registered"] = int(
                listener_callbacks_registered
            )
            # Build thesis-compliant rig_verification.json with explicit compliance booleans
            rig_verification = _build_rig_verification_from_report(
                rig_src,
                recording_dir,
                manifest_payload=manifest_sync.get("data", {}),
                calib_override_path=(
                    (
                        Path.cwd() / Path(args.calib_override).expanduser()
                        if not Path(args.calib_override).expanduser().is_absolute()
                        else Path(args.calib_override).expanduser()
                    )
                    if getattr(args, "calib_override", None)
                    else None
                ),
            )
            rig_verification["low_memory_profile_active"] = bool(low_memory_profile_active)
            if bool(low_memory_profile_active):
                rig_verification["camera_resolution_cap"] = dict(LOW_MEMORY_CAMERA_CAP)
            camera_runtime = _extract_camera_runtime_metrics(rig_verification)
            perception_status["active_camera_count"] = int(
                camera_runtime.get("active_camera_count", 0) or 0
            )
            camera_resolution = camera_runtime.get("camera_resolution", {})
            if isinstance(camera_resolution, dict) and camera_resolution:
                perception_status["camera_resolution"] = dict(camera_resolution)
            override_info = rig_verification.get("calibration_override")
            if isinstance(override_info, dict) and args.calib_override:
                applied_count = int(override_info.get("applied_count", 0) or 0)
                if applied_count > 0:
                    print(
                        f"Calibration override applied from {args.calib_override}"
                    )
                elif override_info.get("error"):
                    print(
                        "WARNING: Failed to apply calibration override: "
                        f"{override_info.get('error')}"
                    )
            diagnostics_payload = rig_verification.get("forward_alignment_diagnostics")
            if isinstance(diagnostics_payload, dict):
                diagnostics_path = out_dir / FORWARD_ALIGNMENT_DIAGNOSTICS
                _write_json(diagnostics_path, diagnostics_payload)
                rig_verification["forward_alignment_diagnostics_path"] = str(
                    diagnostics_path
                )
                perception_status["forward_alignment_diagnostics_path"] = str(
                    diagnostics_path
                )
            rig_contract_errors: List[str] = []
            try:
                rig_verification, rig_contract_errors = _write_canonical_rig_verification(
                    out_dir=out_dir,
                    calib_path=calib_path,
                    rig_report_payload=(
                        rig_data_loaded if isinstance(rig_data_loaded, dict) else None
                    ),
                    existing_verification=rig_verification,
                    note="rig_report_present",
                )
            except Exception as exc:
                rig_write_error = f"rig_verification_write_failed:{exc}"
                if rig_write_error not in perception_status.get("warnings", []):
                    perception_status["warnings"].append(rig_write_error)
                if strict_rig_contract_mode:
                    status["ok"] = False
                    status["carla_failed"] = True
                    status["failure_reason"] = "rig_verification_write_failed"
                    perception_status["ok"] = False
                    perception_status["failure_reason"] = "rig_verification_write_failed"
                    perception_status["failure_detail"] = str(exc)
                    _write_status_bundle(out_dir, status, pair_manifest, perception_status)
                    raise _EarlyExit(EXIT_CODE_INFRA_FAILURE)
                _write_json(out_dir / "rig_verification.json", rig_verification)
            if strict_rig_contract_mode and rig_contract_errors:
                status["ok"] = False
                status["carla_failed"] = True
                status["failure_reason"] = "rig_verification_non_compliant"
                perception_status["ok"] = False
                perception_status["failure_reason"] = "rig_verification_non_compliant"
                perception_status["failure_detail"] = ";".join(rig_contract_errors)
                _write_status_bundle(out_dir, status, pair_manifest, perception_status)
                raise _EarlyExit(EXIT_CODE_INFRA_FAILURE)
            if isinstance(rig_verification.get("forward_alignment"), dict):
                perception_status["forward_alignment"] = dict(
                    rig_verification["forward_alignment"]
                )
            _apply_camera_claim_scope_status(
                perception_status,
                rig_verification.get("forward_alignment")
                if isinstance(rig_verification.get("forward_alignment"), dict)
                else None,
            )
            _apply_calib_override_status(
                perception_status,
                requested_path=str(args.calib_override or ""),
                override_info=override_info
                if isinstance(override_info, dict)
                else None,
                base_calib_path=str(calib_path_metadata),
                base_calib_applied=bool(calib_path.exists()),
            )
            for key in (
                "sensors_attached",
                "sensors_attached_status",
                "sensors_attached_reason",
                "sensors_attached_rule",
                "required_modalities",
                "recorded_modalities",
                "sensors_attached_errors",
                "sensors_attached_missing_modalities",
            ):
                if key in rig_verification:
                    perception_status[key] = rig_verification.get(key)
        else:
            fallback_reason = "rig_attach_gated"
            if int(listener_callbacks_registered) > 0 or len(spawned_sensors) > 0:
                fallback_reason = "FIRST_FRAME_TIMEOUT"
            elif rig_attach_attempted:
                fallback_reason = "sensor_spawn_failed"
            sensor_rig_report_payload["ok"] = False
            sensor_rig_report_payload["reason"] = fallback_reason
            sensor_rig_report_payload["rig_attach_attempted"] = bool(rig_attach_attempted)
            sensor_rig_report_payload["spawned_sensors"] = list(spawned_sensors)
            sensor_rig_report_payload["listener_callbacks_registered"] = int(
                listener_callbacks_registered
            )
            _write_json(rig_dst, sensor_rig_report_payload)
            scene_readiness = _finalize_scene_readiness_attachment(
                scene_readiness,
                thesis_rig_requested=thesis_rig_requested,
                rig_report_payload=sensor_rig_report_payload,
                spawned_sensors=list(spawned_sensors),
            )
            _write_json(scene_readiness_path, scene_readiness)
            perception_status["scene_readiness"] = scene_readiness
            rig_verification_stub = _rig_verification_stub(
                "not_attached", "ERROR: sensor rig not attached"
            )
            if bool(low_memory_profile_active):
                rig_verification_stub["camera_resolution_cap"] = dict(
                    LOW_MEMORY_CAMERA_CAP
                )
                rig_verification_stub["low_memory_profile_active"] = True
            print(
                f"Rig attach attempted: {'yes' if rig_attach_attempted else 'no'}",
                flush=True,
            )
            print(f"Spawned sensors: {list(spawned_sensors)}", flush=True)
            print(
                f"Listener callbacks registered: {int(listener_callbacks_registered)}",
                flush=True,
            )
            rig_attach_failure_reason = str(fallback_reason)
            perception_status["rig_attach_attempted"] = bool(rig_attach_attempted)
            perception_status["spawned_sensors"] = list(spawned_sensors)
            perception_status["listener_callbacks_registered"] = int(
                listener_callbacks_registered
            )
            rig_contract_errors: List[str] = []
            try:
                rig_verification_stub, rig_contract_errors = _write_canonical_rig_verification(
                    out_dir=out_dir,
                    calib_path=calib_path,
                    rig_report_payload=(
                        sensor_rig_report_payload
                        if isinstance(sensor_rig_report_payload, dict)
                        else None
                    ),
                    existing_verification=rig_verification_stub,
                    note="rig_report_missing_fallback",
                )
            except Exception as exc:
                rig_write_error = f"rig_verification_write_failed:{exc}"
                if rig_write_error not in perception_status.get("warnings", []):
                    perception_status["warnings"].append(rig_write_error)
                if strict_rig_contract_mode:
                    status["ok"] = False
                    status["carla_failed"] = True
                    status["failure_reason"] = "rig_verification_write_failed"
                    perception_status["ok"] = False
                    perception_status["failure_reason"] = "rig_verification_write_failed"
                    perception_status["failure_detail"] = str(exc)
                    _write_status_bundle(out_dir, status, pair_manifest, perception_status)
                    raise _EarlyExit(EXIT_CODE_INFRA_FAILURE)
                _write_json(out_dir / "rig_verification.json", rig_verification_stub)
            if strict_rig_contract_mode and rig_contract_errors:
                status["ok"] = False
                status["carla_failed"] = True
                status["failure_reason"] = "rig_verification_non_compliant"
                perception_status["ok"] = False
                perception_status["failure_reason"] = "rig_verification_non_compliant"
                perception_status["failure_detail"] = ";".join(rig_contract_errors)
                _write_status_bundle(out_dir, status, pair_manifest, perception_status)
                raise _EarlyExit(EXIT_CODE_INFRA_FAILURE)
            for key in (
                "sensors_attached",
                "sensors_attached_status",
                "sensors_attached_reason",
                "sensors_attached_rule",
            ):
                if key in rig_verification_stub:
                    perception_status[key] = rig_verification_stub.get(key)
            perception_status["sensors_attached_reason"] = (
                f"{fallback_reason}:missing_rig_report"
            )

        # Run screenshot probes only if the recorder produced artifacts.
        has_recording_artifacts = (
            _count_files(recording_dir, ("*.png", "*.ply", "*.npz")) > 0
        )
        # Save screenshots with stable thesis filenames
        stable_screenshots = _save_stable_screenshots(recording_dir, out_dir)
        
        if has_recording_artifacts:
            _capture_ego_spawn_screenshot(args.host, args.port, out_dir)
            if args.spawn_qa_objects:
                _spawn_sanity_objects_with_screenshot(args.host, args.port, out_dir)

        if require_overlay:
            overlay_path = _ensure_lidar_overlay(out_dir)
            if overlay_path is not None:
                stable_screenshots[SCREENSHOT_LIDAR_OVERLAY] = str(overlay_path)

        rgb_root = _find_rgb_root(recording_dir)
        front_rgb_evidence = _ensure_front_rgb_frame(rgb_root)
        perception_status["front_camera_rgb_path"] = front_rgb_evidence.get(
            "front_alias_path", ""
        )
        perception_status["front_camera_source_dir"] = front_rgb_evidence.get(
            "camera_dir", ""
        )
        png_count = _count_files(rgb_root, ("*.png",)) if rgb_root is not None else 0
        ply_count = _count_files(recording_dir, ("*.ply",))
        npz_count = _count_files(recording_dir, ("*.npz",))
        ply_example_path = ""
        if ply_count > 0:
            try:
                ply_example_path = str(sorted(recording_dir.rglob("*.ply"))[0])
            except Exception:
                ply_example_path = ""

        screenshot_paths: List[str] = []
        stats = {
            "brightness_mean": 0.0,
            "brightness_std": 0.0,
            "laplacian_variance": 0.0,
        }
        camera_name = ""
        if rgb_root is not None:
            cam_dir = _pick_front_cam_dir(rgb_root)
            if cam_dir is not None:
                camera_name = cam_dir.name
                imgs = sorted(cam_dir.glob("*.png"))
                if imgs:
                    screenshot_paths = (
                        [str(imgs[0]), str(imgs[-1])]
                        if len(imgs) > 1
                        else [str(imgs[0])]
                    )
                    stats = _compute_simple_image_stats(list(imgs))
                    try:
                        shots_dir = out_dir / "screenshots"
                        shots_dir.mkdir(parents=True, exist_ok=True)
                        for src in screenshot_paths:
                            src_p = Path(src)
                            if src_p.exists():
                                shutil.copy2(src_p, shots_dir / src_p.name)
                    except Exception:
                        pass

        capture_summary: Dict[str, Any] = {}
        capture_summary_path = recording_dir / "capture_summary.json"
        try:
            if capture_summary_path.is_file():
                capture_summary = json.loads(
                    capture_summary_path.read_text(encoding="utf-8")
                )
        except Exception:
            capture_summary = {}

        run_info_payload: Dict[str, Any] = {}
        run_info_path = recording_dir / "run_info.json"
        try:
            if run_info_path.is_file():
                run_info_payload = json.loads(run_info_path.read_text(encoding="utf-8"))
        except Exception:
            run_info_payload = {}

        tick_watchdog_payload: Dict[str, Any] = {}
        tick_watchdog_path = recording_dir / "tick_watchdog.json"
        try:
            if tick_watchdog_path.is_file():
                tick_watchdog_payload = json.loads(
                    tick_watchdog_path.read_text(encoding="utf-8")
                )
        except Exception:
            tick_watchdog_payload = {}

        recorder_cfg = run_info_payload.get("recorder_config")
        if not isinstance(recorder_cfg, dict):
            recorder_cfg = {}
        sync_evidence = _derive_sync_settings_evidence(
            capture_summary=capture_summary,
            run_info_payload=run_info_payload,
            recorder_cfg=recorder_cfg,
        )
        perception_status["capture_world_settings"] = dict(
            sync_evidence.get("applied_settings", {})
        )
        perception_status["synchronous_mode"] = bool(
            sync_evidence.get("synchronous_mode", False)
        )
        perception_status["fixed_delta_seconds"] = float(
            sync_evidence.get("fixed_delta_seconds", 0.0) or 0.0
        )
        perception_status["settings_applied_before_tick"] = bool(
            sync_evidence.get("settings_applied_before_tick", False)
        )
        perception_status["world_settings_restored"] = bool(
            capture_summary.get("world_settings_restored", False)
        )
        perception_status["tick_watchdog_path"] = (
            str(tick_watchdog_path) if tick_watchdog_path.is_file() else ""
        )
        perception_status["ticks_observed"] = int(
            tick_watchdog_payload.get("n_ticks", 0) or 0
        )
        perception_status["tick_advanced"] = bool(
            tick_watchdog_payload.get("advanced", False)
        )

        first_measurement_ok = bool(
            capture_summary.get("first_measurement_ok", int(png_count) > 0)
        )

        frames_recorded = int(png_count) if png_count > 0 else 0
        min_frames = int(max(0, args.min_frames))
        ok = (
            (proc.returncode == 0)
            and (frames_recorded >= min_frames)
            and bool(integrity_ok)
            and bool(first_measurement_ok)
        )
        outputs_present = (png_count > 0) or (semseg_files > 0) or (ply_count > 0) or (npz_count > 0)
        primary_failure_reason = _classify_record_route_failure(
            timed_out=bool(timed_out),
            proc_returncode=int(proc.returncode),
            outputs_present=bool(outputs_present),
            integrity_ok=bool(integrity_ok),
            integrity_reason=str(integrity_reason or ""),
            first_measurement_ok=bool(first_measurement_ok),
            frames_recorded=int(frames_recorded),
            stdout_text=str(proc.stdout or ""),
            stderr_text=str(proc.stderr or ""),
            skip_stream_check=bool(args.skip_stream_check),
        )
        capture_failure_override = _known_capture_failure_reason(capture_status_payload)
        if capture_failure_override:
            primary_failure_reason = str(capture_failure_override)
        if rig_attach_failure_reason and primary_failure_reason in (
            "no_callbacks",
            "first_measurement_no_callbacks",
            "record_route_timeout",
            "record_route_nonzero",
            "first_measurement_missing",
        ):
            primary_failure_reason = str(rig_attach_failure_reason)
        if primary_failure_reason == "no_callbacks":
            ticks_seen_for_callbacks = _safe_int(
                capture_summary.get("frames_ticks", 0), default=0
            )
            listeners_ready = (
                bool(rig_attach_attempted)
                and len(spawned_sensors) > 0
                and int(listener_callbacks_registered) > 0
                and int(ticks_seen_for_callbacks) >= 3
            )
            if not listeners_ready:
                primary_failure_reason = "sensor_spawn_failed"

        timeout_classified = bool(timed_out) or (
            "timeout" in str(primary_failure_reason or "").lower()
        )
        if timeout_classified:
            timeout_payload: Dict[str, Any] = {
                "schema_version": 1,
                "phase": "record_route",
                "timed_out": bool(timed_out),
                "failure_reason": str(primary_failure_reason or ""),
                "record_route_timeout_s": float(capture_timeout_s),
                "record_route_elapsed_s": float(status.get("elapsed_s", 0.0) or 0.0),
                "record_route_returncode": int(proc.returncode),
                "stdout_path": str(out_dir / "record_route_stdout.txt"),
                "stderr_path": str(out_dir / "record_route_stderr.txt"),
                "requested_map": str(requested_town or ""),
                "actual_map": str(map_name or ""),
                "stream_port": int(stream_port),
                "skip_stream_check": bool(args.skip_stream_check),
            }
            timeout_diagnostics_path = str(
                _write_timeout_diagnostics(out_dir, timeout_payload)
            )
            perception_status["timeout_diagnostics_path"] = timeout_diagnostics_path

        # Write perception_diagnostics.json for frame-related failures (per RCA)
        frame_related_failures = {
            "no_frames", "no_callbacks", "sensor_spawn_failed",
            "first_measurement_no_callbacks", "first_measurement_missing",
            "streaming_unavailable", "streaming_collapse_during_capture",
            "record_route_timeout", "FIRST_FRAME_TIMEOUT",
        }
        classified_frame_failure = (
            primary_failure_reason in frame_related_failures or frames_recorded == 0
        )
        if classified_frame_failure:
            normalized_failure_reason = (
                "NO_FRAMES_RECEIVED"
                if primary_failure_reason in {"no_frames", "no_callbacks", "record_route_timeout"}
                else primary_failure_reason
            )
            tick_progression = {
                "ticks_attempted": int(capture_summary.get("frames_ticks", 0) or 0),
                "frame_ids": list(capture_summary.get("tick_frame_ids", []) or []),
                "elapsed_seconds": list(capture_summary.get("tick_elapsed", []) or []),
            }
            sensor_spawn_status = {}
            for sensor_info in spawned_sensors:
                if isinstance(sensor_info, dict):
                    name = str(sensor_info.get("name", "unknown"))
                    sensor_spawn_status[name] = {
                        "spawned": bool(sensor_info.get("spawned", False)),
                        "actor_id": int(sensor_info.get("actor_id", -1) or -1),
                        "type_id": str(sensor_info.get("type_id", "")),
                    }
            per_sensor_frame_counts = {}
            sensor_counts = capture_summary.get("sensor_frame_counts", {})
            if isinstance(sensor_counts, dict):
                per_sensor_frame_counts = {str(k): int(v or 0) for k, v in sensor_counts.items()}
            streaming_port_reachable = _tcp_port_open(str(args.host), int(stream_port), timeout_s=0.5)
            carla_log_path = ""
            try:
                log_result = copy_latest_carla_log(out_dir)
                if log_result:
                    carla_log_path = str(log_result)
            except Exception:
                pass
            _write_perception_diagnostics(
                out_dir,
                failure_reason=normalized_failure_reason,
                failure_detail=f"{primary_failure_reason}: frames={frames_recorded}, outputs={outputs_present}",
                sensor_spawn_status=sensor_spawn_status,
                listen_errors=list(capture_summary.get("listen_errors", []) or []),
                per_sensor_frame_counts=per_sensor_frame_counts,
                tick_progression=tick_progression,
                map_state={"map_name_raw": str(map_name), "map_name_normalized": normalize_map_name(str(map_name)), "map_match": True},
                sync_settings={"synchronous_mode": bool(sync_evidence.get("synchronous_mode", False)), "fixed_delta_seconds": float(sync_evidence.get("fixed_delta_seconds", 0.0) or 0.0), "no_rendering_mode": bool(capture_summary.get("no_rendering_mode", False))},
                ego_spawn={"x": float(capture_summary.get("ego_spawn_x", 0.0) or 0.0), "y": float(capture_summary.get("ego_spawn_y", 0.0) or 0.0), "z": float(capture_summary.get("ego_spawn_z", 0.0) or 0.0)},
                streaming_port_reachable=streaming_port_reachable,
                carla_log_path=carla_log_path,
            )
            manifest_path = out_dir / "recorder_manifest.json"
            recording_manifest_path = recording_dir / "recorder_manifest.json"
            if not manifest_path.exists() and not recording_manifest_path.exists():
                _synthesize_minimal_recorder_manifest(
                    out_dir, failure_reason=normalized_failure_reason,
                    expected_sensors=list(sensor_spawn_status.keys()),
                    map_name=str(map_name), world_settings=sync_evidence.get("applied_settings", {}),
                )
                perception_status["recorder_manifest_synthesized"] = True
            perception_status["classified_frame_failure"] = True

        rec_summary = {
            "status": "PASS"
            if ok
            else (
                "FAIL"
                if (frames_recorded == 0 or bool(integrity_reason))
                else "PASS_PARTIAL"
            ),
            "failure_reason": ""
            if ok
            else (
                primary_failure_reason
                or (proc.stderr or "").strip()[:300]
                or ("no_frames" if frames_recorded == 0 else "partial")
            ),
            "frames_recorded": frames_recorded,
            "frames_requested": int(args.frames),
            "first_measurement_ok": bool(first_measurement_ok),
            "fps": float(args.fps),
            "host": args.host,
            "port": int(args.port),
            "camera": camera_name,
            "image_size": {"width": 0, "height": 0},
            "brightness_mean": float(stats["brightness_mean"]),
            "brightness_std": float(stats["brightness_std"]),
            "laplacian_variance": float(stats["laplacian_variance"]),
            "screenshot_paths": screenshot_paths,
            "png_count": int(png_count),
            "semseg_files": int(semseg_files),
            "ply_count": int(ply_count),
            "npz_count": int(npz_count),
            "min_frames_required": int(min_frames),
            "corrupted_png_read": int(
                write_integrity.get("corrupted_png_read", 0) or 0
            ),
            "invalid_png_count": int(write_integrity.get("invalid_png_count", 0) or 0),
            "queue_depth_at_shutdown": int(
                write_integrity.get("queue_depth_at_shutdown", 0) or 0
            ),
        }
        _write_json(out_dir / "recording_summary.json", rec_summary)

        if ok:
            status["ok"] = True
            status["carla_failed"] = False
            status["failure_reason"] = None
        else:
            status["ok"] = False
            status["carla_failed"] = True
            status["failure_reason"] = (
                primary_failure_reason
                or ("no_frames" if frames_recorded == 0 else rec_summary["failure_reason"])
            )

        perception_status["png_files"] = int(png_count)
        perception_status["semseg_files"] = int(semseg_files)
        perception_status["camera_callbacks_observed"] = int(png_count > 0)
        perception_status["semseg_callbacks_observed"] = int(semseg_files > 0)
        perception_status["ply_files"] = int(ply_count)
        perception_status["ply_example_path"] = str(ply_example_path)
        perception_status["npz_files"] = int(npz_count)
        perception_status["corrupted_png_read"] = int(
            write_integrity.get("corrupted_png_read", 0) or 0
        )
        perception_status["invalid_png_count"] = int(
            write_integrity.get("invalid_png_count", 0) or 0
        )
        perception_status["queue_depth_at_shutdown"] = int(
            write_integrity.get("queue_depth_at_shutdown", 0) or 0
        )
        perception_status["frames_recorded"] = int(frames_recorded)
        perception_status["first_measurement_ok"] = bool(first_measurement_ok)
        perception_status["failure_reason"] = (
            None
            if (outputs_present and integrity_ok and first_measurement_ok)
            else str(primary_failure_reason or status["failure_reason"])
        )
        if (
            primary_failure_reason
            and primary_failure_reason in KNOWN_CAPTURE_FAILURE_REASONS
            and primary_failure_reason not in perception_status.get("warnings", [])
        ):
            perception_status["warnings"].append(str(primary_failure_reason))
        if int(proc.returncode) == 0:
            perception_status["environment"] = _collect_environment_info(
                args.host, int(args.port)
            )
        if outputs_present:
            perception_status["ok"] = bool(integrity_ok)
            if proc.returncode != 0 and primary_failure_reason not in {"streaming_unavailable", "streaming_collapse_during_capture"}:
                perception_status["warnings"].append("record_route_nonzero")
            if primary_failure_reason == "streaming_unavailable" and "streaming_unavailable" not in perception_status["warnings"]:
                perception_status["warnings"].append("streaming_unavailable")
            if primary_failure_reason == "streaming_collapse_during_capture" and "streaming_collapse_during_capture" not in perception_status["warnings"]:
                perception_status["warnings"].append("streaming_collapse_during_capture")
            if primary_failure_reason == "no_callbacks" and "no_callbacks" not in perception_status["warnings"]:
                perception_status["warnings"].append("no_callbacks")
            if primary_failure_reason == "sensor_spawn_failed" and "sensor_spawn_failed" not in perception_status["warnings"]:
                perception_status["warnings"].append("sensor_spawn_failed")
            if primary_failure_reason == "FIRST_FRAME_TIMEOUT" and "FIRST_FRAME_TIMEOUT" not in perception_status["warnings"]:
                perception_status["warnings"].append("FIRST_FRAME_TIMEOUT")
            if primary_failure_reason == "first_measurement_no_callbacks" and "first_measurement_no_callbacks" not in perception_status["warnings"]:
                perception_status["warnings"].append("first_measurement_no_callbacks")
            if primary_failure_reason == "rig_attach_gated" and "rig_attach_gated" not in perception_status["warnings"]:
                perception_status["warnings"].append("rig_attach_gated")
            if primary_failure_reason == "calib_missing" and "calib_missing" not in perception_status["warnings"]:
                perception_status["warnings"].append("calib_missing")
            if frames_recorded < min_frames:
                perception_status["warnings"].append("partial_frames")
            if not first_measurement_ok:
                perception_status["warnings"].append("first_measurement_missing")
            if int(semseg_files) <= 0 and "semseg_missing" not in perception_status["warnings"]:
                perception_status["warnings"].append("semseg_missing")
            if int(write_integrity.get("corrupted_png_read", 0) or 0) != 0 and "corrupted_png_read" not in perception_status["warnings"]:
                perception_status["warnings"].append("corrupted_png_read")
        else:
            perception_status["ok"] = False
            if primary_failure_reason == "streaming_unavailable":
                if "streaming_unavailable" not in perception_status["warnings"]:
                    perception_status["warnings"].append("streaming_unavailable")
            if primary_failure_reason == "streaming_collapse_during_capture":
                if "streaming_collapse_during_capture" not in perception_status["warnings"]:
                    perception_status["warnings"].append("streaming_collapse_during_capture")
            if primary_failure_reason == "no_callbacks":
                if "no_callbacks" not in perception_status["warnings"]:
                    perception_status["warnings"].append("no_callbacks")
            if primary_failure_reason == "sensor_spawn_failed":
                if "sensor_spawn_failed" not in perception_status["warnings"]:
                    perception_status["warnings"].append("sensor_spawn_failed")
            if primary_failure_reason == "FIRST_FRAME_TIMEOUT":
                if "FIRST_FRAME_TIMEOUT" not in perception_status["warnings"]:
                    perception_status["warnings"].append("FIRST_FRAME_TIMEOUT")
            if primary_failure_reason == "first_measurement_no_callbacks":
                if "first_measurement_no_callbacks" not in perception_status["warnings"]:
                    perception_status["warnings"].append("first_measurement_no_callbacks")
            if primary_failure_reason == "rig_attach_gated":
                if "rig_attach_gated" not in perception_status["warnings"]:
                    perception_status["warnings"].append("rig_attach_gated")
            if primary_failure_reason == "calib_missing":
                if "calib_missing" not in perception_status["warnings"]:
                    perception_status["warnings"].append("calib_missing")

        _write_status_bundle(out_dir, status, pair_manifest, perception_status)

        if args.fail_nonzero and not ok:
            raise _EarlyExit(2)
        raise _EarlyExit(0)
    except _EarlyExit as exc:
        exit_code = int(exc.code)
    except Exception as exc:
        err_text = str(exc)
        manifest_gate_errors = {
            "MISSING_RECORDER_MANIFEST",
            "EMPTY_RECORDER_MANIFEST",
            "MISSING_MAP_PROVENANCE",
        }
        status["ok"] = False
        status["carla_failed"] = True
        status["failure_detail"] = err_text
        perception_status["failure_detail"] = err_text
        if err_text in manifest_gate_errors:
            status["failure_reason"] = err_text
            perception_status["failure_reason"] = err_text
            if err_text not in perception_status.get("warnings", []):
                perception_status["warnings"].append(err_text)
        else:
            status["failure_reason"] = "unexpected_exception"
            perception_status["failure_reason"] = "unexpected_exception"
        try:
            (out_dir / "stderr.log").write_text(
                traceback.format_exc(), encoding="utf-8", errors="replace"
            )
        except Exception:
            pass
        exit_code = 2
    finally:
        try:
            if recording_dir.is_dir():
                manifest_sync = _sync_recorder_manifest(
                    recording_dir,
                    out_dir,
                    fallback_timestamp=timestamp,
                    map_name=map_name,
                    world_settings_payload=world_settings_payload,
                )
                perception_status["recorder_manifest_path"] = str(
                    manifest_sync.get("path", "")
                )
                perception_status["recorder_manifest_recording_path"] = str(
                    manifest_sync.get("recording_path", "")
                )
                perception_status["recorder_manifest_root_copy_path"] = str(
                    manifest_sync.get("root_copy_path", "")
                )
                perception_status["recorder_manifest_written"] = bool(
                    manifest_sync.get("written", False)
                )
                perception_status["recorder_manifest_synthesized"] = bool(
                    manifest_sync.get("synthesized", False)
                )
                perception_status["recorder_manifest_source"] = str(
                    manifest_sync.get("data", {}).get("manifest_source", "")
                    if isinstance(manifest_sync.get("data"), dict)
                    else ""
                )
                if manifest_sync.get("error"):
                    warn = (
                        f"recorder_manifest_write_failed:{manifest_sync.get('error')}"
                    )
                    if warn not in perception_status.get("warnings", []):
                        perception_status["warnings"].append(warn)
            # Skip manifest gate assertion if we already have a classified frame failure with diagnostics
            has_classified_frame_failure = bool(
                perception_status.get("classified_frame_failure", False)
            )
            prelaunch_failure_active = _has_terminal_prelaunch_failure(
                status=status,
                perception_status=perception_status,
            )
            if (
                require_manifest_gate
                and not has_classified_frame_failure
                and not prelaunch_failure_active
            ):
                try:
                    capture_status_payload_final = _read_capture_status_payload(recording_dir)
                    known_capture_failure_final = _enforce_manifest_gate_for_capture(
                        require_manifest_gate=bool(require_manifest_gate),
                        recording_dir=recording_dir,
                        out_dir=out_dir,
                        manifest_sync=manifest_sync,
                        capture_status_payload=capture_status_payload_final,
                    )
                    if known_capture_failure_final:
                        status["ok"] = False
                        status["carla_failed"] = True
                        status["failure_reason"] = str(known_capture_failure_final)
                        perception_status["ok"] = False
                        perception_status["failure_reason"] = str(
                            known_capture_failure_final
                        )
                        if (
                            str(known_capture_failure_final)
                            not in perception_status.get("warnings", [])
                        ):
                            perception_status["warnings"].append(
                                str(known_capture_failure_final)
                            )
                        copied_log = copy_latest_carla_log(out_dir)
                        if copied_log:
                            perception_status["carla_latest_log_path"] = str(copied_log)
                except RuntimeError as manifest_exc:
                    manifest_err = str(manifest_exc)
                    status["ok"] = False
                    status["carla_failed"] = True
                    status["failure_reason"] = manifest_err
                    perception_status["ok"] = False
                    perception_status["failure_reason"] = manifest_err
                    if manifest_err not in perception_status.get("warnings", []):
                        perception_status["warnings"].append(manifest_err)
                    exit_code = 2

            manifest_payload_final = (
                manifest_sync.get("data", {})
                if isinstance(manifest_sync.get("data"), dict)
                else {}
            )
            semseg_files_final = (
                _semseg_file_count(recording_dir, manifest_payload_final)
                if recording_dir.is_dir()
                else 0
            )
            write_integrity_final = (
                _build_write_integrity_status(
                    recording_dir=recording_dir,
                    manifest_payload=manifest_payload_final,
                )
                if recording_dir.is_dir()
                else {
                    "schema_version": 1,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "png_files_checked": 0,
                    "corrupted_png_read": 0,
                    "invalid_png_count": 0,
                    "invalid_png_examples": [],
                    "queue_depth_at_shutdown": 0,
                }
            )
            _write_json(out_dir / WRITE_INTEGRITY_STATUS_JSON, write_integrity_final)
            perception_status["write_integrity_status_path"] = str(
                out_dir / WRITE_INTEGRITY_STATUS_JSON
            )
            perception_status["semseg_files"] = int(semseg_files_final)
            perception_status["corrupted_png_read"] = int(
                write_integrity_final.get("corrupted_png_read", 0) or 0
            )
            perception_status["invalid_png_count"] = int(
                write_integrity_final.get("invalid_png_count", 0) or 0
            )
            perception_status["queue_depth_at_shutdown"] = int(
                write_integrity_final.get("queue_depth_at_shutdown", 0) or 0
            )

            counts = _scan_outputs(out_dir)
            perception_status["png_files"] = counts["png"]
            perception_status["ply_files"] = counts["ply"]
            perception_status["ply_example_path"] = counts.get("ply_example_path", "")
            perception_status["npz_files"] = counts["npz"]
            outputs_present = (
                (counts["png"] > 0)
                or (int(semseg_files_final) > 0)
                or (counts["ply"] > 0)
            )
            corrupted_png_final = int(
                write_integrity_final.get("corrupted_png_read", 0) or 0
            )
            if require_manifest_gate:
                integrity_pass_final = bool(
                    int(semseg_files_final) > 0 and corrupted_png_final == 0
                )
                integrity_reason_final = (
                    "semseg_missing"
                    if int(semseg_files_final) <= 0
                    else (
                        "corrupted_png_read"
                        if corrupted_png_final != 0
                        else ""
                    )
                )
            else:
                min_frames_final = int(max(0, args.min_frames))
                integrity_pass_final = bool(int(counts["png"]) >= int(min_frames_final))
                integrity_reason_final = (
                    ""
                    if integrity_pass_final
                    else "insufficient_frames"
                )
                if not prelaunch_failure_active:
                    if int(semseg_files_final) <= 0 and "semseg_missing_optional" not in perception_status["warnings"]:
                        perception_status["warnings"].append("semseg_missing_optional")
                    if corrupted_png_final != 0 and "corrupted_png_read_optional" not in perception_status["warnings"]:
                        perception_status["warnings"].append("corrupted_png_read_optional")
            if outputs_present and integrity_pass_final and not perception_status.get("ok", False):
                perception_status["ok"] = True
                perception_status["failure_reason"] = None
                if "outputs_present" not in perception_status["warnings"]:
                    perception_status["warnings"].append("outputs_present")
            if outputs_present and not integrity_pass_final and not prelaunch_failure_active:
                perception_status["ok"] = False
                perception_status["failure_reason"] = str(integrity_reason_final)
                status["ok"] = False
                status["carla_failed"] = True
                status["failure_reason"] = str(integrity_reason_final)
                if integrity_reason_final not in perception_status["warnings"]:
                    perception_status["warnings"].append(integrity_reason_final)
                if args.fail_nonzero:
                    exit_code = 2
            if outputs_present and _detect_destroyed_actor(out_dir):
                if "ego_destroyed" not in perception_status["warnings"]:
                    perception_status["warnings"].append("ego_destroyed")
                if perception_status.get("sensors_attached") is False:
                    perception_status["sensors_attached"] = "unknown"
                    perception_status["sensors_attached_status"] = "unknown"
                    perception_status["sensors_attached_reason"] = (
                        "carla_teardown_before_frame_capture"
                    )
            missing = _validate_evidence_pack(out_dir, require_overlay, require_objects)
            perception_status["missing_artifacts"] = missing
            perception_status["evidence_pack_ok"] = len(missing) == 0
            qa_spawn_report = _build_qa_spawn_report(
                out_dir, spawn_requested=bool(args.spawn_qa_objects)
            )
            _write_json(out_dir / QA_SPAWN_REPORT_JSON, qa_spawn_report)
            perception_status["qa_spawn_report_path"] = str(
                out_dir / QA_SPAWN_REPORT_JSON
            )
            for key in (
                "qa_objects_attempted",
                "qa_objects_spawned",
                "qa_objects_spawn_success_rate",
                "qa_objects_collision_free_rate",
            ):
                perception_status[key] = qa_spawn_report.get(key)
            perception_status["produced_artifacts"] = {
                "ego_spawn_png": bool((out_dir / SCREENSHOT_EGO_SPAWN).is_file()),
                "camera_front_png": bool((out_dir / SCREENSHOT_CAMERA_FRONT).is_file()),
                "lidar_bev_png": bool((out_dir / SCREENSHOT_LIDAR_BEV).is_file()),
                "lidar_overlay_png": bool(
                    (out_dir / SCREENSHOT_LIDAR_OVERLAY).is_file()
                ),
                "objects_placed_json": bool((out_dir / OBJECTS_PLACED_JSON).is_file()),
                "objects_placed_png": bool((out_dir / OBJECTS_PLACED_PNG).is_file()),
                "qa_spawn_report_json": bool(
                    (out_dir / QA_SPAWN_REPORT_JSON).is_file()
                ),
            }
            classified_frame_failure_final = bool(
                perception_status.get("classified_frame_failure", False)
            )
            if require_evidence_pack and missing and not prelaunch_failure_active:
                perception_status["ok"] = False
                if not classified_frame_failure_final:
                    perception_status["failure_reason"] = "missing_evidence_pack"
                if "missing_evidence_pack" not in perception_status["warnings"]:
                    perception_status["warnings"].append("missing_evidence_pack")
                exit_code = 2
        except Exception:
            pass
        try:
            _write_real_u_proxy_metrics(out_dir, model_outputs=None)
        except Exception:
            pass
        try:
            summary_path = out_dir / "recording_summary.json"
            if not summary_path.exists():
                _write_json(
                    summary_path,
                    {
                        "status": "UNKNOWN",
                        "failure_reason": perception_status.get("failure_reason")
                        or status.get("failure_reason")
                        or "",
                        "frames_recorded": int(
                            perception_status.get("frames_recorded", 0) or 0
                        ),
                        "frames_requested": int(args.frames),
                        "fps": float(args.fps),
                        "host": args.host,
                        "port": int(args.port),
                        "camera": "",
                        "image_size": {"width": 0, "height": 0},
                        "brightness_mean": 0.0,
                        "brightness_std": 0.0,
                        "laplacian_variance": 0.0,
                        "screenshot_paths": [],
                    },
                )
        except Exception:
            pass
        _write_status_bundle(out_dir, status, pair_manifest, perception_status)
        if lock_acquired:
            _release_run_lock(lock_path)
        if actor_ids_to_destroy and not bool(args.keep_enrichments_alive):
            print(f"[run_perception_safe] Cleaning up {len(actor_ids_to_destroy)} enrichment actors...")
            destroy_runtime_enrichments(args.host, int(args.port), actor_ids_to_destroy)

    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
