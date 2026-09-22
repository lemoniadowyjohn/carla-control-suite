#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/perception/rq3_capture_contract.py

Governed RQ3 paired-capture contract engine.

The manual and automatic Ingolstadt capture arms must share identical sensor
rig, calibration, route, weather, synchronous settings, fixed delta,
frame-completeness rule and listener lifecycle; the capture manifest must bind
CARLA version, map identity, route/calibration/sensor-rig/weather hashes, frame
counts and the software commit.

This module is the SINGLE authority that decides whether two captures may be
labeled a valid (paired) RQ3 experiment, and at which claim level:

    SENSOR_SMOKE
    UNPAIRED_CAPTURE
    PAIRED_PROTOCOL_VALID
    PAIRED_INGOLSTADT_CAPTURE

Design rules:
* No CARLA import at module level -> fully offline-testable.
* Every equality is decided by content digest (SHA-256) over canonical JSON,
  or by exact equality of normalized identity fields.
* `pair_valid` is only ever true when ALL mandatory equalities hold.
* A pair using Town10HD as one arm can never be `PAIRED_INGOLSTADT_CAPTURE`.
* Hidden spawn recovery is forbidden by `enforce_spawn_policy` in
  THESIS_PAIRED_STRICT mode.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

MANIFEST_SCHEMA_VERSION = "paired_capture_manifest_v1"

CLAIM_SENSOR_SMOKE = "SENSOR_SMOKE"
CLAIM_UNPAIRED_CAPTURE = "UNPAIRED_CAPTURE"
CLAIM_PAIRED_PROTOCOL_VALID = "PAIRED_PROTOCOL_VALID"
CLAIM_PAIRED_INGOLSTADT_CAPTURE = "PAIRED_INGOLSTADT_CAPTURE"

MODE_SMOKE_RECOVERY = "SMOKE_RECOVERY"
MODE_THESIS_PAIRED_STRICT = "THESIS_PAIRED_STRICT"
VALID_MODES = (MODE_SMOKE_RECOVERY, MODE_THESIS_PAIRED_STRICT)

PAIR_ROUTE_INVALID = "PAIR_ROUTE_INVALID"
INCOMPLETE_PAIR = "INCOMPLETE_PAIR"

COMPLETION_PASS = "PASS"
COMPLETION_INCOMPLETE = "INCOMPLETE"
COMPLETION_FAIL = "FAIL"

INGOLSTADT_MANUAL_COOKED_TOWNS = ("Grid0821", "Grid0828")

# Wall-clock / process-scoped fields excluded from deterministic digests.
DETERMINISM_EXCLUDED_FIELDS = frozenset(
    {
        "timestamp_utc",
        "created_utc",
        "closed_utc",
        "started_utc",
        "wall_clock_ms",
        "elapsed_seconds",
        "attempted_at_utc",
        "recorded_at_utc",
        "write_time_utc",
    }
)


def canonical_dumps(obj: Any) -> str:
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _sha256_of_path(path: str) -> str:
    """Content SHA-256 of a file regardless of encoding (bytes-level)."""
    try:
        return sha256_bytes(Path(path).read_bytes())
    except Exception:
        return ""


def sha256_file(path: str) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def canonical_digest(payload: Any, *, exclude_fields: Iterable[str] = ()) -> str:
    """Digest of a payload with selected wall-clock fields excluded.

    Used to prove that capture manifests are byte-deterministic apart from
    explicitly allowed non-reproducibility fields.
    """
    excluded = set(exclude_fields) or set(DETERMINISM_EXCLUDED_FIELDS)
    scrubbed = _scrub(payload, excluded)

    def _sorted(obj: Any) -> Any:
        # Deep sort so that dict insertion order cannot affect the digest.
        if isinstance(obj, dict):
            return {k: _sorted(obj[k]) for k in sorted(obj, key=str)}
        if isinstance(obj, (list, tuple)):
            return [_sorted(v) for v in obj]
        return obj

    return sha256_text(canonical_dumps(_sorted(scrubbed)))


def _scrub(obj: Any, excluded: set) -> Any:
    if isinstance(obj, dict):
        out = {
            k: _scrub(v, excluded)
            for k, v in obj.items()
            if k not in excluded and not str(k).startswith("_")
        }
        if "sha256" in out:
            del out["sha256"]
        return out
    if isinstance(obj, (list, tuple)):
        return [_scrub(v, excluded) for v in obj]
    return obj


def deterministic_digest(manifest: Mapping[str, Any], exclude_fields: Iterable[str] = ()) -> str:
    return canonical_digest(dict(manifest), exclude_fields=exclude_fields)


# ---------------------------------------------------------------------------
# Calibration / sensor-rig identity
# ---------------------------------------------------------------------------


def _calib_effective_sensors(
    calib_data: Mapping[str, Any],
    *,
    front_only: bool = False,
) -> List[Dict[str, Any]]:
    """Normalize the calibratable sensor list into effective-rig spec entries.

    The effective rig is what the capture actually runs AFTER profile
    filtering / degraded-mode decisions (e.g. `--front-only` drops all
    non-front cameras).
    """
    sensors: List[Dict[str, Any]] = []
    cameras = calib_data.get("cameras") or {}
    lidars = calib_data.get("lidars") or {}

    for name, cam in cameras.items():
        if front_only and "front" not in str(name).strip().lower():
            continue
        size = cam.get("image_size")
        sensors.append(
            {
                "sensor_name": str(name),
                "blueprint": "sensor.camera.rgb",
                "relative_transform": _matrix_to_rows(cam.get("cTv")),
                "resolution": {"width": int(size[0]), "height": int(size[1])} if size else None,
                "fov": _float_or_none(cam.get("fov")) if cam.get("fov") is not None else None,
                "sensor_tick": _float_or_none(cam.get("sensor_tick"))
                if cam.get("sensor_tick") is not None
                else None,
                "mode": "rgb",
            }
        )

    for name, lid in lidars.items():
        sensors.append(
            {
                "sensor_name": str(name),
                "blueprint": "sensor.lidar.ray_cast",
                "relative_transform": _matrix_to_rows(lid.get("vTl")),
                "resolution": None,
                "fov": None,
                "sensor_tick": None,
                "mode": "lidar",
            }
        )
    return sorted(sensors, key=lambda s: str(s["sensor_name"]))


def _matrix_to_rows(matrix: Any) -> Optional[List[List[float]]]:
    if not isinstance(matrix, (list, tuple)):
        return None
    rows = []
    for row in matrix:
        if isinstance(row, (list, tuple)):
            rows.append([_round6(float(v)) for v in row])
        else:
            rows.append(_round6(float(row)))
    return rows


def _float_or_none(v: Any) -> Optional[float]:
    try:
        return _round6(float(v))
    except (TypeError, ValueError):
        return None


def _round6(v: float) -> float:
    return round(float(v), 6)


def calibration_identity(calib_path: str) -> Dict[str, Any]:
    """Content-authenticated calibration identity (bytes of the JSON file)."""
    return {
        "calib_path": str(calib_path),
        "calib_sha256": sha256_file(calib_path),
    }


def sensor_rig_identity(
    effective_sensors: Sequence[Mapping[str, Any]],
    *,
    calibration_sha256: str = "",
) -> Dict[str, Any]:
    """Digest the exact effective sensor rig (post filtering / degraded mode).

    Two arms share an identical rig iff `sensor_rig_sha256` matches.
    """
    normalized: List[Dict[str, Any]] = []
    for s in effective_sensors:
        entry = {
            "sensor_name": str(s.get("sensor_name", "")),
            "blueprint": str(s.get("blueprint", "")),
            "relative_transform": s.get("relative_transform"),
            "resolution": s.get("resolution"),
            "fov": _float_or_none(s.get("fov")) if s.get("fov") is not None else None,
            "sensor_tick": _float_or_none(s.get("sensor_tick"))
            if s.get("sensor_tick") is not None
            else None,
            "mode": str(s.get("mode", "")),
        }
        normalized.append(entry)
    normalized.sort(key=lambda e: str(e["sensor_name"]))
    payload = {
        "calibration_sha256": str(calibration_sha256),
        "sensor_rig": normalized,
    }
    return {
        "effective_sensors": normalized,
        "sensor_rig_sha256": sha256_text(canonical_dumps(payload)),
        "sensor_count": len(normalized),
        "camera_names": [
            e["sensor_name"] for e in normalized if "camera" in str(e["blueprint"]).lower()
        ],
        "lidar_names": [
            e["sensor_name"] for e in normalized if "lidar" in str(e["blueprint"]).lower()
        ],
    }


def sensor_rig_from_calib(
    calib_path: str,
    *,
    front_only: bool = False,
) -> Dict[str, Any]:
    """Build the effective-rig identity directly from a calib JSON file."""
    try:
        data = json.loads(Path(calib_path).read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "effective_sensors": [],
            "sensor_rig_sha256": "",
            "calib_sha256": sha256_file(calib_path),
            "error": f"calib_read_failed:{type(exc).__name__}:{exc}",
        }
    calib_sha = _sha256_of_path(calib_path)
    return sensor_rig_identity(
        _calib_effective_sensors(data, front_only=front_only),
        calibration_sha256=calib_sha,
    )


# ---------------------------------------------------------------------------
# Weather identity
# ---------------------------------------------------------------------------


def weather_identity(weather_params: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalized weather digest from ACTUAL world parameters.

    Only a preset name is never enough for a paired claim; we digest the
    effective parameters so two arms with nominally identical presets but
    different actual values diverge.
    """
    normalized: Dict[str, Any] = {}
    for k, v in weather_params.items():
        if v is None:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            normalized[str(k)] = _round6(float(v))
        elif isinstance(v, (str, bool)):
            normalized[str(k)] = v
        else:
            normalized[str(k)] = repr(v)
    return {
        "weather_sha256": sha256_text(canonical_dumps(normalized)) if normalized else "",
        "parameters": normalized,
        "parameter_count": len(normalized),
    }


def weather_from_world(world: Any) -> Dict[str, Any]:
    """Read the effective weather from a duck-typed CARLA world."""
    weather = None
    try:
        weather = world.get_weather()
    except Exception:
        try:
            weather = world.weather_forecast
        except Exception:
            weather = None
    if weather is None:
        return weather_identity({})
    keys = ("cloudiness", "precipitation", "precipitation_deposits", "wind_intensity",
            "sun_azimuth_angle", "sun_altitude_angle", "fog_density", "fog_distance",
            "wetness", "scattering_intensity", "mie_scattering_scale")
    params = {}
    for key in keys:
        if hasattr(weather, key):
            try:
                params[key] = getattr(weather, key)
            except Exception:
                continue
    return weather_identity(params)


# ---------------------------------------------------------------------------
# Simulation timing identity
# ---------------------------------------------------------------------------


def sim_timing_identity(
    *,
    synchronous_mode: bool,
    fixed_delta_seconds: float,
    traffic_manager_sync: bool,
    fps_target: float,
    warmup_ticks: Optional[int] = None,
    capture_ticks: Optional[int] = None,
) -> Dict[str, Any]:
    normalized = {
        "synchronous_mode": bool(synchronous_mode),
        "fixed_delta_seconds": _round6(float(fixed_delta_seconds)),
        "traffic_manager_sync": bool(traffic_manager_sync),
        "fps_target": _round6(float(fps_target)),
        "warmup_ticks": int(warmup_ticks) if warmup_ticks is not None else None,
        "capture_ticks": int(capture_ticks) if capture_ticks is not None else None,
    }
    return {
        "timing": normalized,
        "sim_timing_sha256": sha256_text(canonical_dumps(normalized)),
    }


# ---------------------------------------------------------------------------
# Capture-config identity
# ---------------------------------------------------------------------------


def capture_config_identity(config: Any) -> Dict[str, Any]:
    """Digest the frozen `PairedCaptureConfig` fields that affect comparability."""
    fields = {
        "frames": int(getattr(config, "frames")),
        "fps": int(getattr(config, "fps")),
        "rig": str(getattr(config, "rig")),
        "front_only": bool(getattr(config, "front_only")),
        "seg": bool(getattr(config, "seg")),
        "lidar_format": str(getattr(config, "lidar_format")),
        "vehicle": str(getattr(config, "vehicle")),
        "seed": int(getattr(config, "seed")),
    }
    return {
        "fields": fields,
        "capture_config_sha256": sha256_text(canonical_dumps(fields)),
    }


# ---------------------------------------------------------------------------
# Frame completeness policy
# ---------------------------------------------------------------------------


def evaluate_frame_completeness(
    expected_cameras: Mapping[str, int],
    actual_counts: Mapping[str, int],
    *,
    timed_out: bool = False,
    save_errors: Optional[Sequence[str]] = None,
    expected_lidars: Mapping[str, int] | None = None,
) -> Dict[str, Any]:
    """Decide PASS / INCOMPLETE / FAIL for one capture arm.

    PASS requires, for every required sensor, actual >= expected. A timeout
    with partial frames is INCOMPLETE (never PASS). Missing required sensors
    or zero frames is FAIL.
    """
    expected = dict(expected_cameras)
    for name, count in (expected_lidars or {}).items():
        expected[name] = int(count)

    per_sensor: List[Dict[str, Any]] = []
    missing: List[str] = []
    satisfied = True
    for name in sorted(expected):
        expected_count = int(expected[name])
        actual = int(actual_counts.get(name, 0))
        ok = actual >= expected_count
        if not ok:
            satisfied = False
            if actual == 0:
                missing.append(name)
        entry = {
            "sensor_name": str(name),
            "expected_frames": expected_count,
            "actual_frames": actual,
            "complete": ok,
        }
        per_sensor.append(entry)

    save_errors = list(save_errors or [])
    if satisfied and not timed_out and not save_errors:
        status = COMPLETION_PASS
    elif satisfied and save_errors:
        status = COMPLETION_FAIL
    elif timed_out and not satisfied:
        status = COMPLETION_INCOMPLETE
    else:
        status = COMPLETION_FAIL

    return {
        "status": status,
        "complete": status == COMPLETION_PASS,
        "timed_out": bool(timed_out),
        "save_error_count": len(save_errors),
        "missing_sensors": missing,
        "per_sensor": per_sensor,
        "closure": status,
    }


def compute_strict_completion_status(
    *,
    expected_cameras: Mapping[str, int],
    actual_counts: Mapping[str, int],
    save_errors: Optional[Sequence[str]] = None,
    ego_destroyed: bool = False,
    sensor_failures: Optional[Sequence[str]] = None,
    timed_out: bool = False,
) -> Dict[str, Any]:
    """Strict per-sensor completion status for RQ3 evidence (LocalPerceptionRunner).

    This is deliberately stricter than the loose diagnostic `ok` (any output
    present): every expected camera and lidar must reach its expected frame
    count, with no save errors, no destroyed ego and no sensor failures.
    """
    sensor_failures = list(sensor_failures or [])
    base = evaluate_frame_completeness(
        expected_cameras,
        actual_counts,
        timed_out=timed_out,
        save_errors=save_errors,
    )
    hard_conditions = bool(ego_destroyed) or bool(sensor_failures)
    if base["status"] == COMPLETION_PASS and hard_conditions:
        base["status"] = COMPLETION_FAIL
        base["complete"] = False
        base["closure"] = COMPLETION_FAIL
    base["ego_destroyed"] = bool(ego_destroyed)
    base["sensor_failures"] = sensor_failures
    base["expected_cameras"] = {str(k): int(v) for k, v in expected_cameras.items()}
    base["actual_counts"] = {str(k): int(v) for k, v in actual_counts.items()}
    return base


# ---------------------------------------------------------------------------
# Spawn policy (hidden recovery guard)
# ---------------------------------------------------------------------------


def enforce_spawn_policy(
    route_mode: str,
    spawn_record: Mapping[str, Any],
) -> List[str]:
    """Return invalid-reason strings (empty list == policy satisfied).

    In THESIS_PAIRED_STRICT mode a capture may use NO hidden spawn recovery:
    no shuffle, no fallback to a different spawn point, and no silent pose
    adjustment. Recovery is only ever allowed in SMOKE_RECOVERY mode.
    """
    if route_mode not in VALID_MODES:
        return [f"unknown_route_mode:{route_mode}"]

    reasons: List[str] = []
    if route_mode == MODE_THESIS_PAIRED_STRICT:
        if bool(spawn_record.get("shuffle_used")):
            reasons.append("spawn_shuffle_used_in_strict_mode")
        if bool(spawn_record.get("recovery_fallback_used")):
            reasons.append("spawn_recovery_used_in_strict_mode")
        for pose_idx in spawn_record.get("poses_adjusted", []):
            reasons.append(f"route_pose_adjusted_in_strict_mode:{pose_idx}")
        if not bool(spawn_record.get("spawned_at_requested_pose", False)):
            reasons.append("spawn_not_at_requested_pose")
    return reasons


# ---------------------------------------------------------------------------
# Map identity binding
# ---------------------------------------------------------------------------


def xodr_arm_map_identity(
    *,
    xodr_path: str,
    xodr_sha256: str,
    final_artifact_authority_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "map_type": "auto_xodr" if False else "xodr",
        "xodr_path": str(xodr_path),
        "xodr_sha256": str(xodr_sha256),
        "final_artifact_authority_sha256": final_artifact_authority_sha256,
    }


def cooked_arm_map_identity(
    *,
    requested_map_name: str,
    resolved_carla_map_name: str,
    registry_identity: Optional[str] = None,
    manual_source_xodr_sha256: Optional[str] = None,
    cooked_package_identity: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "map_type": "cooked_manual",
        "requested_map_name": str(requested_map_name),
        "resolved_carla_map_name": str(resolved_carla_map_name),
        "registry_identity": registry_identity,
        "manual_source_xodr_sha256": manual_source_xodr_sha256,
        "cooked_package_build_identity": cooked_package_identity,
    }


def is_ingolstadt_manual_arm(map_identity: Mapping[str, Any]) -> bool:
    if map_identity.get("map_type") != "cooked_manual":
        return False
    requested = str(map_identity.get("requested_map_name", ""))
    return requested in INGOLSTADT_MANUAL_COOKED_TOWNS


def is_ingolstadt_auto_arm(map_identity: Mapping[str, Any], *, ingolstadt_xodr_sha256=None) -> bool:
    if map_identity.get("map_type") != "xodr":
        return False
    if ingolstadt_xodr_sha256:
        return str(map_identity.get("xodr_sha256", "")) == str(ingolstadt_xodr_sha256)
    path = str(map_identity.get("xodr_path", "")).replace("\\", "/")
    return "ingolstadt" in path.lower() or "campaigns/" in path.lower()


# ---------------------------------------------------------------------------
# Claim level boundary
# ---------------------------------------------------------------------------


def classify_claim_level(
    *,
    is_pair: bool,
    pair_valid: bool,
    route_valid: bool,
    both_arms_ingolstadt: bool,
    manual_arm: Optional[Mapping[str, Any]] = None,
    auto_arm: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compute the maximum claim a capture is allowed to make.

    Boundary rules:
      * A non-pair is always UNPAIRED_CAPTURE.
      * If the route is unrepresentable on either arm, or any mandatory
        equality fails, the pair is invalid (never a protocol-valid pair).
      * A Town10HD/control arm yields SENSOR_SMOKE at most and can never be
        PAIRED_INGOLSTADT_CAPTURE.
    """
    reasons: List[str] = []

    if not is_pair:
        return {"claim_level": CLAIM_UNPAIRED_CAPTURE, "reasons": reasons}

    if not route_valid:
        reasons.append(PAIR_ROUTE_INVALID)
    if not pair_valid:
        reasons.append("pair_invalid_mandatory_equalities")

    if bool(reasons):
        return {"claim_level": CLAIM_UNPAIRED_CAPTURE, "reasons": reasons}

    if both_arms_ingolstadt:
        return {"claim_level": CLAIM_PAIRED_INGOLSTADT_CAPTURE, "reasons": []}

    return {"claim_level": CLAIM_PAIRED_PROTOCOL_VALID, "reasons": []}


# ---------------------------------------------------------------------------
# Pair manifest builder + validator
# ---------------------------------------------------------------------------


def build_pair_manifest(
    *,
    pair_id: str,
    software_git_sha: str,
    carla_client_version: str,
    carla_server_version: str,
    manual_map_identity: Mapping[str, Any],
    auto_map_identity: Mapping[str, Any],
    route_manifest_path: str,
    route_manifest_sha256: str,
    calibration_sha256: str,
    sensor_rig_sha256: str,
    weather_sha256: str,
    capture_config_sha256: str,
    manual_arm: Mapping[str, Any],
    auto_arm: Mapping[str, Any],
    pair_valid: bool,
    invalid_reasons: Sequence[str],
    claim_level: str,
    route_mode: str = MODE_THESIS_PAIRED_STRICT,
    pair_route_closure: str = "PAIR_ROUTE_VALID",
) -> Dict[str, Any]:
    manifest: Dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "pair_id": str(pair_id),
        "software_git_sha": str(software_git_sha),
        "carla_client_version": str(carla_client_version),
        "carla_server_version": str(carla_server_version),
        "route_mode": str(route_mode),
        "manual_map_identity": dict(manual_map_identity),
        "auto_map_identity": dict(auto_map_identity),
        "route_manifest_path": str(route_manifest_path),
        "route_manifest_sha256": str(route_manifest_sha256),
        "calibration_sha256": str(calibration_sha256),
        "sensor_rig_sha256": str(sensor_rig_sha256),
        "weather_sha256": str(weather_sha256),
        "capture_config_sha256": str(capture_config_sha256),
        "manual_arm": dict(manual_arm),
        "auto_arm": dict(auto_arm),
        "pair_route_closure": str(pair_route_closure),
        "pair_valid": bool(pair_valid),
        "invalid_reasons": sorted(set(str(r) for r in invalid_reasons)),
        "claim_level": str(claim_level),
    }
    return manifest


def validate_pair_manifest(manifest: Mapping[str, Any]) -> Dict[str, Any]:
    """Fail-closed validation of an existing pair manifest.

    `pair_valid` may only be true when every mandatory equality holds and the
    claim-level boundary is respected.
    """
    reasons: List[str] = []
    manual = manifest.get("manual_arm") or {}
    auto = manifest.get("auto_arm") or {}

    for key in ("calibration_sha256", "sensor_rig_sha256", "weather_sha256",
                "capture_config_sha256", "route_manifest_sha256"):
        ml = manual.get(key)
        al = auto.get(key)
        top = manifest.get(key)
        if not top:
            reasons.append(f"{key}_missing")
        if ml is not None and al is not None and ml != al:
            reasons.append(f"{key}_mismatch_manual_vs_auto:{ml}!={al}")
        if ml is not None and top is not None and ml != top:
            reasons.append(f"{key}_mismatch_manual_vs_top:{ml}!={top}")
        if al is not None and top is not None and al != top:
            reasons.append(f"{key}_mismatch_auto_vs_top:{al}!={top}")

    ml = manual.get("pair_frame_index")
    al = auto.get("pair_frame_index")
    if ml is not None and al is not None and ml != al:
        reasons.append("pair_frame_index_mismatch")

    claim = manifest.get("claim_level")
    pair_valid = bool(manifest.get("pair_valid"))

    if claim == CLAIM_PAIRED_INGOLSTADT_CAPTURE:
        manual_map = manifest.get("manual_map_identity") or {}
        auto_map = manifest.get("auto_map_identity") or {}
        if not is_ingolstadt_manual_arm(manual_map):
            reasons.append("claim_ingolstadt_requires_manual_ingolstadt_arm")
        if not is_ingolstadt_auto_arm(auto_map):
            reasons.append("claim_ingolstadt_requires_auto_ingolstadt_xodr_arm")
    if claim == CLAIM_PAIRED_PROTOCOL_VALID and pair_valid and not reasons:
        pass
    if pair_valid and reasons:
        return {"valid": False, "pair_valid": pair_valid, "claim_level": claim,
                "invalid_reasons": reasons,
                "pair_route_closure": manifest.get("pair_route_closure")}
    return {"valid": not reasons, "pair_valid": pair_valid, "claim_level": claim,
            "invalid_reasons": reasons,
            "pair_route_closure": manifest.get("pair_route_closure")}


# ---------------------------------------------------------------------------
# Software / CARLA identity
# ---------------------------------------------------------------------------


def git_sha_of_repo(repo_root: Optional[str] = None) -> str:
    import os

    root = repo_root
    if not root:
        root = os.environ.get("UP_REPO_ROOT", "")
    if not root:
        root = str(Path(__file__).resolve().parents[2])
    try:
        out = subprocess.run(
            ["git", "-C", root, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return os.environ.get("GIT_SHA", "unknown")


def carla_client_version(client: Any = None) -> str:
    if client is not None:
        try:
            v = client.get_client_version()
            if v:
                return str(v)
            v = client.get_version()
            if v:
                return str(v)
        except Exception:
            pass
    try:
        import carla  # type: ignore

        return str(getattr(carla, "__version__", "unknown"))
    except Exception:
        return "unavailable"


def carla_server_version(client: Any = None) -> str:
    if client is not None:
        try:
            v = client.get_server_version()
            if v:
                return str(v)
        except Exception:
            pass
    return "unavailable"


# ---------------------------------------------------------------------------
# Frame-count collection helpers
# ---------------------------------------------------------------------------

_PNG_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp")
_PLY_SUFFIXES = (".ply", ".npz")


def count_frames_by_sensor(out_dir: str) -> Dict[str, Dict[str, int]]:
    """Count saved frames per sensor from a capture output directory.

    Supports both recorder-style `rgb/<camera>/*.png` subdirectories and
    flat `camera_frame.png` filename conventions. Returned dict maps
    modality to {sensor_name: count}.
    """
    root = Path(out_dir)
    images: Dict[str, int] = {}
    point_clouds: Dict[str, int] = {}

    def _walk(directory: Path, sensor_name: Optional[str]) -> None:
        for p in directory.iterdir():
            if p.is_dir():
                _walk(p, sensor_name or p.name)
            elif p.is_file():
                name = sensor_name or (p.name.rsplit("_", 1)[0] if "_" in p.name else p.stem)
                if p.name.lower().endswith(_PNG_SUFFIXES):
                    images[name] = images.get(name, 0) + 1
                elif p.name.lower().endswith(_PLY_SUFFIXES):
                    point_clouds[name] = point_clouds.get(name, 0) + 1

    if root.is_dir():
        _walk(root, None)
    return {"camera_frames": images, "lidar_frames": point_clouds}