#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Safe ego spawn helper with road projection and retry logic.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple


def _write_report(path: Optional[str], report: Dict[str, Any]) -> None:
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
    except Exception:
        pass


def _project_to_road(world, location) -> Tuple[Optional[Any], str]:
    try:
        try:
            import carla  # type: ignore

            lane_type = carla.LaneType.Driving
            wpt = world.get_map().get_waypoint(location, project_to_road=True, lane_type=lane_type)
        except Exception:
            wpt = world.get_map().get_waypoint(location, project_to_road=True)
        if wpt is not None:
            return wpt, "waypoint_project"
    except Exception:
        pass
    return None, "no_project"


def safe_spawn_ego(
    world,
    *,
    blueprint_filter: str = "vehicle.tesla.model3",
    spawn_index: int = 0,
    z_offset: float = 0.5,
    retries: int = 10,
    report_path: Optional[str] = None,
) -> Tuple[Optional[Any], Dict[str, Any]]:
    report: Dict[str, Any] = {
        "ok": False,
        "blueprint_filter": blueprint_filter,
        "spawn_index": spawn_index,
        "z_offset": z_offset,
        "retries": retries,
        "spawn_points_total": 0,
        "attempts": [],
        "selected_spawn": None,
        "warnings": [],
    }

    try:
        bp_lib = world.get_blueprint_library()
        bps = bp_lib.filter(blueprint_filter)
        if not bps:
            report["warnings"].append(f"no blueprint matches: {blueprint_filter}")
            _write_report(report_path, report)
            return None, report
        blueprint = bps[0]
        blueprint.set_attribute("role_name", "ego")
    except Exception as exc:
        report["warnings"].append(f"blueprint error: {exc}")
        _write_report(report_path, report)
        return None, report

    try:
        spawn_points = list(world.get_map().get_spawn_points())
    except Exception as exc:
        report["warnings"].append(f"spawn points error: {exc}")
        _write_report(report_path, report)
        return None, report

    report["spawn_points_total"] = len(spawn_points)
    if not spawn_points:
        report["warnings"].append("no spawn points available")
        _write_report(report_path, report)
        return None, report

    indices: List[int] = []
    if 0 <= spawn_index < len(spawn_points):
        indices.append(spawn_index)
    indices.extend([i for i in range(len(spawn_points)) if i != spawn_index])

    for attempt_idx, sp_idx in enumerate(indices[: max(1, retries)]):
        sp = spawn_points[sp_idx]
        proj_wpt, proj_method = _project_to_road(world, sp.location)
        if proj_wpt is not None:
            tf = proj_wpt.transform
        else:
            tf = sp
        tf.location.z += float(z_offset)

        attempt = {
            "attempt": attempt_idx,
            "spawn_index": sp_idx,
            "project_method": proj_method,
            "location": {"x": tf.location.x, "y": tf.location.y, "z": tf.location.z},
            "rotation": {"pitch": tf.rotation.pitch, "yaw": tf.rotation.yaw, "roll": tf.rotation.roll},
            "ok": False,
        }

        try:
            actor = world.try_spawn_actor(blueprint, tf)
            if actor is not None:
                attempt["ok"] = True
                report["ok"] = True
                report["selected_spawn"] = attempt
                report["attempts"].append(attempt)
                _write_report(report_path, report)
                return actor, report
        except Exception as exc:
            attempt["error"] = str(exc)

        report["attempts"].append(attempt)

    report["warnings"].append("failed to spawn ego after retries")
    _write_report(report_path, report)
    return None, report
