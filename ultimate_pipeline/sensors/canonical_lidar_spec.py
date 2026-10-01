#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/sensors/canonical_lidar_spec.py

NEW-301: Canonical LiDAR runtime-spec builder.

This module provides a single canonical LiDAR spec resolver so that
there is exactly ONE source of truth for LiDAR parameters across:
- ThesisSensorRig (spawn_rig)
- DominikSensorSetup (_make_specs)
- attach_sensors_safe (LIADR attribute setting)
- RQ3 runtime rig identity hashing (NEW-299)

The spec is resolved from calibration data with optional profile overrides,
and the resulting attribute dict is consumed by all rig constructors.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple


# --- Thesis protocol constants (single authority for timing) ---
THESIS_SYNC_SETTINGS = {
    "synchronous_mode": True,
    "fixed_delta_seconds": 0.05,
    "target_fps": 20,
    "traffic_manager_synchronous": True,
    "traffic_manager_delta_seconds": 0.05,
}

# Canonical LiDAR defaults (matches DominikSensorSetup defaults, NOT the
# hard-coded values previously scattered in attach_sensors_safe).
DEFAULT_LIDAR_SPEC = {
    "range": 80.0,
    "rotation_frequency": 20.0,
    "channels": 64,
    "points_per_second": 200_000,
    "upper_fov": 10.0,
    "lower_fov": -30.0,
    "sensor_tick": 0.0,
}

# Low-memory profile overrides
LOW_MEMORY_LIDAR_OVERRIDES = {
    "channels": 32,
    "points_per_second": 200_000,
    "rotation_frequency": 10.0,
}


@dataclass
class LidarRuntimeSpec:
    """Resolved LiDAR runtime specification from calibration + profile."""
    name: str
    active: bool
    range: float
    rotation_frequency: float
    channels: int
    points_per_second: int
    upper_fov: float
    lower_fov: float
    sensor_tick: float
    calibration_values: Dict[str, Any]
    overrides_applied: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_carla_attributes(self) -> Dict[str, str]:
        """Convert to CARLA blueprint attribute strings."""
        return {
            "range": str(self.range),
            "rotation_frequency": str(int(self.rotation_frequency)),
            "channels": str(self.channels),
            "points_per_second": str(self.points_per_second),
            "upper_fov": str(self.upper_fov),
            "lower_fov": str(self.lower_fov),
            "sensor_tick": str(self.sensor_tick),
        }

    def spec_sha256(self) -> str:
        """Content hash of the resolved spec (excluding calibration_values)."""
        spec_dict = {
            "name": self.name,
            "active": self.active,
            "range": self.range,
            "rotation_frequency": self.rotation_frequency,
            "channels": self.channels,
            "points_per_second": self.points_per_second,
            "upper_fov": self.upper_fov,
            "lower_fov": self.lower_fov,
            "sensor_tick": self.sensor_tick,
            "overrides_applied": sorted(self.overrides_applied),
        }
        blob = json.dumps(spec_dict, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _coerce_float(value: Any, default: float) -> float:
    try:
        f = float(value)
        if not math.isfinite(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        f = float(value)
        if not math.isfinite(f) or f < 0:
            return default
        return int(f)
    except (TypeError, ValueError):
        return default


def resolve_active_lidars(
    calib_data: Dict[str, Any],
    *,
    active_names: Optional[List[str]] = None,
    low_memory_profile: bool = False,
    env_overrides: Optional[Dict[str, str]] = None,
) -> List[LidarRuntimeSpec]:
    """
    Resolve the active LiDAR set and their runtime specs.

    NEW-300: Active sensor policy is explicit. A LiDAR becomes active only if
    it appears in `active_names` (default: ["middle_lidar"]).
    `middle_lidar_old` is NOT active unless explicitly listed.

    The spec is resolved from calibration data with optional profile overrides.
    All rig constructors (ThesisSensorRig, DominikSensorSetup, attach_sensors_safe)
    consume this same resolved spec.
    """
    lidars_cfg = calib_data.get("lidars", {}) or {}
    if active_names is None:
        active_names = ["middle_lidar"]
    else:
        active_names = [str(n) for n in active_names]

    env = dict(env_overrides if env_overrides else {})

    specs: List[LidarRuntimeSpec] = []
    for name in active_names:
        if name not in lidars_cfg:
            continue
        calib_entry = lidars_cfg[name]
        overrides: List[str] = []
        calibration_values = dict(calib_entry) if isinstance(calib_entry, dict) else {}

        # Start with canonical defaults
        spec = dict(DEFAULT_LIDAR_SPEC)

        # Apply calibration values if present
        for key in ("range", "rotation_frequency", "channels", "points_per_second",
                    "upper_fov", "lower_fov", "sensor_tick"):
            if key in calibration_values:
                if key in ("channels", "points_per_second"):
                    spec[key] = _coerce_int(calibration_values[key], spec[key])
                else:
                    spec[key] = _coerce_float(calibration_values[key], spec[key])
                overrides.append(f"calib:{key}")

        # Apply low-memory profile overrides
        if low_memory_profile:
            for key, val in LOW_MEMORY_LIDAR_OVERRIDES.items():
                spec[key] = val
                overrides.append(f"low_mem:{key}")

        # Apply env overrides (highest priority)
        env_map = {
            "UP_LIDAR_CHANNELS": "channels",
            "UP_LIDAR_PPS": "points_per_second",
            "UP_LIDAR_HZ": "rotation_frequency",
            "UP_LIDAR_RANGE": "range",
        }
        for env_key, spec_key in env_map.items():
            raw = env.get(env_key, "")
            if raw is not None and str(raw).strip():
                if spec_key in ("channels", "points_per_second"):
                    spec[spec_key] = _coerce_int(raw, spec[spec_key])
                else:
                    spec[spec_key] = _coerce_float(raw, spec[spec_key])
                overrides.append(f"env:{env_key}")

        # Clamp
        spec["channels"] = max(1, min(spec["channels"], 128))
        spec["points_per_second"] = max(1000, min(spec["points_per_second"], 5_000_000))
        spec["rotation_frequency"] = max(1.0, min(spec["rotation_frequency"], 30.0))
        spec["range"] = max(1.0, min(spec["range"], 500.0))

        specs.append(LidarRuntimeSpec(
            name=name,
            active=True,
            range=float(spec["range"]),
            rotation_frequency=float(spec["rotation_frequency"]),
            channels=int(spec["channels"]),
            points_per_second=int(spec["points_per_second"]),
            upper_fov=float(spec["upper_fov"]),
            lower_fov=float(spec["lower_fov"]),
            sensor_tick=float(spec["sensor_tick"]),
            calibration_values=calibration_values,
            overrides_applied=overrides,
        ))

    return specs


def all_lidar_specs(
    calib_data: Dict[str, Any],
    *,
    low_memory_profile: bool = False,
    env_overrides: Optional[Dict[str, str]] = None,
) -> List[LidarRuntimeSpec]:
    """
    Return ALL LiDAR specs from calibration, with explicit active flags.
    Used for RQ3 rig identity to prove inactive entries are not hashed.
    """
    lidars_cfg = calib_data.get("lidars", {}) or {}
    active_names = ["middle_lidar"]  # New-300: canonical active set

    specs: List[LidarRuntimeSpec] = []
    for name, calib_entry in lidars_cfg.items():
        calib_entry = calib_entry if isinstance(calib_entry, dict) else {}
        spec = dict(DEFAULT_LIDAR_SPEC)
        for key in ("range", "rotation_frequency", "channels", "points_per_second",
                    "upper_fov", "lower_fov", "sensor_tick"):
            if key in calib_entry:
                if key in ("channels", "points_per_second"):
                    spec[key] = _coerce_int(calib_entry[key], spec[key])
                else:
                    spec[key] = _coerce_float(calib_entry[key], spec[key])

        if low_memory_profile:
            for key, val in LOW_MEMORY_LIDAR_OVERRIDES.items():
                spec[key] = val

        is_active = str(name) in active_names
        specs.append(LidarRuntimeSpec(
            name=str(name),
            active=is_active,
            range=float(spec["range"]),
            rotation_frequency=float(spec["rotation_frequency"]),
            channels=int(spec["channels"]),
            points_per_second=int(spec["points_per_second"]),
            upper_fov=float(spec["upper_fov"]),
            lower_fov=float(spec["lower_fov"]),
            sensor_tick=float(spec["sensor_tick"]),
            calibration_values=dict(calib_entry),
            overrides_applied=[],
        ))

    return specs


def active_lidar_policy() -> Dict[str, Any]:
    """
    NEW-300: Return the active-sensor policy.
    
    For thesis production, select one canonical primary LiDAR unless the
    experiment explicitly requires two.
    """
    return {
        "active_lidars": ["middle_lidar"],
        "inactive_calibration_entries": ["middle_lidar_old"],
        "policy_source": "New-300 canonical active LiDAR policy",
        "rationale": "middle_lidar is the canonical primary LiDAR; middle_lidar_old remains as historical calibration info only",
    }


def canonical_lidar_hash(
    calib_data: Dict[str, Any],
    *,
    low_memory_profile: bool = False,
    env_overrides: Optional[Dict[str, str]] = None,
    active_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    NEW-301: Compute canonical LiDAR spec hash from resolved active spec.
    This is the hash used for RQ3 runtime rig identity (NEW-299).
    """
    if active_names is None:
        active_names = ["middle_lidar"]

    active_specs = resolve_active_lidars(
        calib_data,
        active_names=active_names,
        low_memory_profile=low_memory_profile,
        env_overrides=env_overrides,
    )

    all_specs = all_lidar_specs(
        calib_data,
        low_memory_profile=low_memory_profile,
        env_overrides=env_overrides,
    )

    active_names_resolved = [s.name for s in active_specs]
    inactive_names = [s.name for s in all_specs if s.name not in active_names_resolved]

    payload = {
        "active_lidar_specs": [s.to_dict() for s in active_specs],
        "active_lidar_names": active_names_resolved,
        "active_lidar_count": len(active_specs),
        "inactive_lidar_names": inactive_names,
        "inactive_lidar_count": len(inactive_names),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return {
        "active_specs": [s.to_dict() for s in active_specs],
        "inactive_specs": [s.to_dict() for s in all_specs if s.active is False],
        "active_lidar_names": active_names_resolved,
        "inactive_lidar_names": inactive_names,
        "lidar_spec_sha256": hashlib.sha256(blob.encode("utf-8")).hexdigest(),
        "active_lidar_count": len(active_specs),
    }


def thesis_sync_settings() -> Dict[str, Any]:
    """
    NEW-298: Return the authoritative thesis protocol timing settings.
    """
    normalized = {
        "synchronous_mode": bool(THESIS_SYNC_SETTINGS["synchronous_mode"]),
        "fixed_delta_seconds": float(THESIS_SYNC_SETTINGS["fixed_delta_seconds"]),
        "target_fps": float(THESIS_SYNC_SETTINGS["target_fps"]),
        "traffic_manager_synchronous": bool(THESIS_SYNC_SETTINGS["traffic_manager_synchronous"]),
        "traffic_manager_delta_seconds": float(THESIS_SYNC_SETTINGS["traffic_manager_delta_seconds"]),
    }
    blob = json.dumps(normalized, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return {
        "settings": normalized,
        "sim_timing_sha256": hashlib.sha256(blob.encode("utf-8")).hexdigest(),
    }


def validate_effective_timing(
    world_settings: Dict[str, Any],
    *,
    traffic_manager_sync: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    NEW-298: Validate effective timing matches thesis protocol.

    world_settings is a dict with keys like:
        synchronous_mode, fixed_delta_seconds, max_substep_delta_time, max_substeps
    """
    expected = THESIS_SYNC_SETTINGS
    effective = {
        "synchronous_mode": bool(world_settings.get("synchronous_mode", False)),
        "fixed_delta_seconds": float(world_settings.get("fixed_delta_seconds", 0.0)),
        "traffic_manager_synchronous": bool(traffic_manager_sync or False),
        "target_fps": _compute_effective_fps(
            float(world_settings.get("fixed_delta_seconds", 0.0))
        ),
    }

    mismatches = []
    if effective["synchronous_mode"] != expected["synchronous_mode"]:
        mismatches.append(f"synchronous_mode: expected={expected['synchronous_mode']}, got={effective['synchronous_mode']}")
    if abs(effective["fixed_delta_seconds"] - expected["fixed_delta_seconds"]) > 1e-9:
        mismatches.append(f"fixed_delta_seconds: expected={expected['fixed_delta_seconds']}, got={effective['fixed_delta_seconds']}")
    if effective["traffic_manager_synchronous"] != expected["traffic_manager_synchronous"]:
        mismatches.append(f"traffic_manager_synchronous: expected={expected['traffic_manager_synchronous']}, got={effective['traffic_manager_synchronous']}")
    if abs(effective["target_fps"] - expected["target_fps"]) > 1e-6:
        mismatches.append(f"target_fps: expected={expected['target_fps']}, got={effective['target_fps']}")

    return {
        "requested_timing": expected,
        "effective_timing": effective,
        "mismatches": mismatches,
        "valid": not mismatches,
    }


def _compute_effective_fps(fixed_delta: float) -> float:
    if fixed_delta <= 0:
        return 0.0
    return round(1.0 / fixed_delta, 6)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()