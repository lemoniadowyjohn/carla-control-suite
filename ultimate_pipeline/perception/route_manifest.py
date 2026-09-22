#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ultimate_pipeline/perception/route_manifest.py

Immutable geographic route/pose authority for RQ3 paired perception capture.

Why this exists
---------------
"spawn_index = N" on two different CARLA maps does NOT prove the same
geographic route:

* spawn-point ordering can differ between maps (same index -> different place);
* spawn transforms can differ at the same index;
* manual and auto road-graph topology can differ;
* hidden spawn recovery may silently pick a different point;
* LocalPerceptionRunner can shuffle candidate spawns;
* autopilot trajectories diverge over time.

This module introduces a spawn-list-independent route authority
(`paired_route_manifest_v1`): a coordinate-frame-bound set of capture poses and
route waypoints that both capture arms MUST be driven through, hashed with
SHA-256 so equality is decided by digest, never by an integer index.

CARLA is never imported at module level: every function here is testable
offline with duck-typed objects.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, Iterable, List, Optional, Sequence

ROUTE_SCHEMA_VERSION = "paired_route_manifest_v1"

PAIR_ROUTE_INVALID = "PAIR_ROUTE_INVALID"

_DEFAULT_THRESHOLDS = {
    "max_projection_distance_m": 2.0,
    "max_orientation_mismatch_deg": 15.0,
    "require_driving_lane": True,
}

# Pose field keys fixed by the schema.
POSE_FIELDS = ("x", "y", "z", "yaw", "pitch", "roll", "sequence_index")
WAYPOINT_FIELDS = ("x", "y", "z", "yaw", "sequence_index")


def canonical_dumps(obj: Any) -> str:
    """Deterministic JSON serialization (sorted keys, no whitespace).

    Used as the canonical byte source for every content digest in this module.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def manifest_payload_without_digest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """Return the manifest with the self-hash removed (the digest input)."""
    out = dict(manifest)
    out.pop("sha256", None)
    return out


def route_digest(manifest: Dict[str, Any]) -> str:
    """Recompute the sha256 over the canonical payload (excluding itself)."""
    return sha256_text(canonical_dumps(manifest_payload_without_digest(manifest)))


def _require_pose_shape(pose: Dict[str, Any]) -> None:
    for f in POSE_FIELDS:
        if f not in pose:
            raise ValueError(f"pose missing required field '{f}'")
        if f == "sequence_index":
            int(pose[f])
        else:
            float(pose[f])


def build_route_manifest(
    *,
    route_id: str,
    coordinate_frame: str,
    capture_poses: Sequence[Dict[str, Any]],
    waypoints: Optional[Sequence[Dict[str, Any]]] = None,
    source: Optional[str] = None,
    crs: Optional[str] = None,
    geo_reference: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a frozen `paired_route_manifest_v1` dict with a self-digest.

    Poses are normalization-sorted by `sequence_index` before hashing so that
    byte-equal digests mean semantically-equal routes. Reconstruction is
    possible independently of any CARLA spawn list.
    """
    if not isinstance(route_id, str) or not route_id.strip():
        raise ValueError("route_id must be a non-empty string")
    if not isinstance(coordinate_frame, str) or not coordinate_frame.strip():
        raise ValueError("coordinate_frame must be a non-empty string (e.g. CRS identity)")
    if not capture_poses:
        raise ValueError("capture_poses must not be empty")

    poses: List[Dict[str, Any]] = []
    for idx, pose in enumerate(capture_poses):
        p = {k: pose[k] for k in POSE_FIELDS if k in pose}
        if len(p) != len(POSE_FIELDS):
            raise ValueError(
                f"capture_pose[{idx}] missing one of {POSE_FIELDS}: {sorted(pose.keys())}"
            )
        p["sequence_index"] = int(pose["sequence_index"])
        for f in ("x", "y", "z", "yaw", "pitch", "roll"):
            p[f] = float(pose[f])
        poses.append(p)
    poses = sorted(poses, key=lambda p: int(p["sequence_index"]))

    sorted_waypoints: List[Dict[str, Any]] = []
    if waypoints is not None:
        for idx, wp in enumerate(waypoints):
            w = {k: wp[k] for k in WAYPOINT_FIELDS if k in wp}
            if len(w) != len(WAYPOINT_FIELDS):
                raise ValueError(
                    f"waypoint[{idx}] missing one of {WAYPOINT_FIELDS}: {sorted(wp.keys())}"
                )
            w["sequence_index"] = int(wp["sequence_index"])
            for f in ("x", "y", "z", "yaw"):
                w[f] = float(wp[f])
            sorted_waypoints.append(w)
        sorted_waypoints = sorted(sorted_waypoints, key=lambda w: int(w["sequence_index"]))

    payload_without_hashes = {
        "schema_version": ROUTE_SCHEMA_VERSION,
        "route_id": str(route_id),
        "coordinate_frame": str(coordinate_frame),
        "waypoints": sorted_waypoints,
        "capture_poses": poses,
        "source": str(source) if source else None,
    }
    if crs:
        payload_without_hashes["crs"] = str(crs)
    if geo_reference:
        payload_without_hashes["geo_reference"] = geo_reference

    out = dict(payload_without_hashes)
    out["sha256"] = sha256_text(canonical_dumps(payload_without_hashes))
    manifest_payload_without_digest(out)  # sanity: digest input never contains the digest
    return out


def validate_route_manifest(manifest: Dict[str, Any]) -> List[str]:
    """Structural + digest validation. Returns a list of reason strings (empty = valid)."""
    reasons: List[str] = []
    if not isinstance(manifest, dict):
        return ["route_manifest_not_dict"]
    if manifest.get("schema_version") != ROUTE_SCHEMA_VERSION:
        reasons.append(f"route_manifest_bad_schema_version:{manifest.get('schema_version')}")
    if not manifest.get("route_id"):
        reasons.append("route_manifest_missing_route_id")
    if not manifest.get("coordinate_frame"):
        reasons.append("route_manifest_missing_coordinate_frame")
    poses = manifest.get("capture_poses")
    if not poses:
        reasons.append("route_manifest_empty_capture_poses")
    else:
        for idx, pose in enumerate(poses):
            missing = [f for f in POSE_FIELDS if f not in pose]
            if missing:
                for f in missing:
                    reasons.append(f"route_manifest_pose[{idx}]_missing_{f}")
                continue
            reason = _check_finite(pose, POSE_FIELDS, f"capture_pose[{idx}]")
            if reason:
                reasons.append(reason)
    seqs = [int(p["sequence_index"]) for p in poses if "sequence_index" in p]
    if seqs:
        if len(set(seqs)) != len(seqs):
            reasons.append("route_manifest_duplicate_sequence_index")
        if seqs != sorted(seqs):
            reasons.append("route_manifest_sequence_index_not_sorted")
    if manifest.get("sha256") != route_digest(manifest):
        reasons.append("route_manifest_digest_mismatch")
    return reasons


def _check_finite(entry: Dict[str, Any], fields: Iterable[str], label: str) -> Optional[str]:
    for f in fields:
        if f == "sequence_index":
            continue
        try:
            v = float(entry[f])
        except (TypeError, ValueError):
            return f"route_manifest_{label}_non_finite_{f}"
        if not math.isfinite(v):
            return f"route_manifest_{label}_non_finite_{f}"
    return None


def pose_payload(
    *,
    x: float,
    y: float,
    z: float,
    yaw: float,
    pitch: float,
    roll: float,
    sequence_index: int,
) -> Dict[str, float]:
    return {
        "x": float(x),
        "y": float(y),
        "z": float(z),
        "yaw": float(yaw),
        "pitch": float(pitch),
        "roll": float(roll),
        "sequence_index": int(sequence_index),
    }


def pose_from_transform(
    transform: Any,
    sequence_index: int,
    *,
    location_transform: Any = None,
    rotation_transform: Any = None,
) -> Dict[str, float]:
    """Build a pose dict from a duck-typed CARLA-like transform.

    The transform duck-type exposes `.location` with `.x/.y/.z` and
    `.rotation` with `.yaw/.pitch/.roll`. Optional location/rotation
    transforms allow tests to wrap fake objects.
    """
    loc = location_transform(transform.location) if location_transform else transform.location
    rot = rotation_transform(transform.rotation) if rotation_transform else transform.rotation
    return pose_payload(
        x=float(getattr(loc, "x")),
        y=float(getattr(loc, "y")),
        z=float(getattr(loc, "z")),
        yaw=float(getattr(rot, "yaw")),
        pitch=float(getattr(rot, "pitch")),
        roll=float(getattr(rot, "roll")),
        sequence_index=sequence_index,
    )


def pose_distance_m(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    return math.sqrt(
        (float(a["x"]) - float(b["x"])) ** 2
        + (float(a["y"]) - float(b["y"])) ** 2
        + (float(a["z"]) - float(b["z"])) ** 2
    )


def orientation_mismatch_deg(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Minimal wrapped heading/attitude mismatch (deg) between two poses' yaws."""
    yaw_a, yaw_b = float(a["yaw"]) % 360.0, float(b["yaw"]) % 360.0
    diff = (yaw_a - yaw_b + 180.0) % 360.0 - 180.0
    return abs(diff)


# ---------------------------------------------------------------------------
# Route correspondence validation (projection onto a specific map)
# ---------------------------------------------------------------------------


class RouteMapAdapter:
    """Protocol for a map-backed waypoint probe used by pose projection.

    Implementations must expose `resolve_drivable_waypoint(pose)` returning an
    object/dict with at least:

        x, y, z, yaw,
        road_id, lane_id,
        projection_distance_m,
        is_driving (bool)
    """

    def resolve_drivable_waypoint(self, pose: Dict[str, Any]) -> Any:
        raise NotImplementedError


def project_pose(
    pose: Dict[str, Any],
    probe: Any,
    *,
    thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Project one capture pose onto a map and report the correspondence.

    Returns a record with the requested pose, the projected drivable
    waypoint, projection distance, road/lane identity, orientation mismatch,
    and whether the pose had to be adjusted to be usable. A pose is usable
    on this map only when every value is within the thresholds and the
    projection lands on a driving lane.
    """
    t = dict(_DEFAULT_THRESHOLDS)
    if thresholds:
        t.update({k: v for k, v in thresholds.items() if v is not None})

    probe_dict = {
        "x": float(getattr(probe, "x")),
        "y": float(getattr(probe, "y")),
        "z": float(getattr(probe, "z", pose["z"])),
        "yaw": float(getattr(probe, "yaw", pose["yaw"])),
    }
    proj_distance = float(getattr(probe, "projection_distance_m", 0.0))
    is_driving = bool(getattr(probe, "is_driving", False))
    mismatch = orientation_mismatch_deg(pose, probe_dict)

    reasons: List[str] = []
    if proj_distance > float(t["max_projection_distance_m"]):
        reasons.append(
            f"projection_distance_{proj_distance:.3f}_exceeds_{t['max_projection_distance_m']}"
        )
    if mismatch > float(t["max_orientation_mismatch_deg"]):
        reasons.append(f"orientation_mismatch_{mismatch:.2f}_exceeds_{t['max_orientation_mismatch_deg']}")
    if bool(t["require_driving_lane"]) and not is_driving:
        reasons.append("not_driving_lane")
    usable = not reasons

    return {
        "sequence_index": int(pose["sequence_index"]),
        "requested_pose": {
            "x": float(pose["x"]),
            "y": float(pose["y"]),
            "z": float(pose["z"]),
            "yaw": float(pose["yaw"]),
            "pitch": float(pose["pitch"]),
            "roll": float(pose["roll"]),
        },
        "projected_waypoint": {
            "x": probe_dict["x"],
            "y": probe_dict["y"],
            "z": probe_dict["z"],
            "yaw": probe_dict["yaw"],
        },
        "projection_distance_m": float(proj_distance),
        "road_id": getattr(probe, "road_id", None),
        "lane_id": getattr(probe, "lane_id", None),
        "orientation_mismatch_deg": float(mismatch),
        "adjusted": not usable,
        "usable": usable,
        "reasons": reasons,
    }


def validate_route_on_map(
    route_manifest: Dict[str, Any],
    map_adapter: RouteMapAdapter,
    *,
    thresholds: Optional[Dict[str, float]] = None,
    map_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Prove every capture pose is representable on the given map.

    If any pose must be adjusted, or is not on a drivable lane, the route is
    not usable on this map: the pair must be rejected (`PAIR_ROUTE_INVALID`)
    instead of silently altering one arm's route.
    """
    reasons = validate_route_manifest(route_manifest)
    per_pose = []
    invalid_poses: List[int] = []
    for pose in route_manifest.get("capture_poses", []):
        try:
            probe = map_adapter.resolve_drivable_waypoint(pose)
        except Exception as exc:  # noqa: BLE001 - map probe failure is a route-level reason
            entry = {
                "sequence_index": int(pose["sequence_index"]),
                "usable": False,
                "adjusted": True,
                "reasons": [f"map_probe_failed:{type(exc).__name__}"],
            }
            per_pose.append(entry)
            invalid_poses.append(int(pose["sequence_index"]))
            continue
        entry = project_pose(pose, probe, thresholds=thresholds)
        per_pose.append(entry)
        if not entry["usable"]:
            invalid_poses.append(int(pose["sequence_index"]))

    usable = not reasons and not invalid_poses
    return {
        "map_name": map_name,
        "valid": bool(usable),
        "manifest_sha256": route_digest(route_manifest),
        "pose_count": len(per_pose),
        "invalid_pose_count": len(invalid_poses),
        "invalid_poses": invalid_poses,
        "per_pose": per_pose,
        "closure": PAIR_ROUTE_INVALID if invalid_poses else "ROUTE_REPRESENTABLE",
        "manifest_errors": reasons,
    }


def validate_paired_route(
    route_sha256: str,
    manual_validation: Dict[str, Any],
    auto_validation: Dict[str, Any],
) -> Dict[str, Any]:
    """Combine per-arm route validations into the paired verdict.

    Both arms must (a) reference the same route digest and (b) be fully
    usable. A route that cannot be represented comparably on both maps is
    `PAIR_ROUTE_INVALID`, never silently adjusted on one side.
    """
    errors: List[str] = []
    if str(route_sha256) != str(manual_validation.get("manifest_sha256")):
        errors.append(f"manual_arm_route_sha_mismatch:{manual_validation.get('manifest_sha256')}")
    if str(route_sha256) != str(auto_validation.get("manifest_sha256")):
        errors.append(f"auto_arm_route_sha_mismatch:{auto_validation.get('manifest_sha256')}")
    if not manual_validation.get("valid"):
        errors.append(f"manual_arm_route_invalid:{manual_validation.get('closure')}")
    if not auto_validation.get("valid"):
        errors.append(f"auto_arm_route_invalid:{auto_validation.get('closure')}")
    valid = not errors
    return {
        "valid": bool(valid),
        "route_sha256": str(route_sha256),
        "closure": "PAIR_ROUTE_VALID" if valid else PAIR_ROUTE_INVALID,
        "errors": errors,
        "manual": manual_validation,
        "auto": auto_validation,
    }