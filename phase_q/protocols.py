"""Q9/Q10 - Evaluation protocol, hold-out regions, and threshold freeze.

* Q11_EVALUATION_PROTOCOL.json - development/regression/hold-out regions,
  route seeds, weather seeds, camera poses, sensor configuration, thresholds.
* Q12_HOLDOUT_REGION_REGISTRY.geojson - hold-out regions only.
* Q13_THRESHOLD_REGISTRY.json - approval-frozen acceptance thresholds.

Map must not be modified after hold-out results are viewed without
invalidating the final evaluation.  Hold-out regions must be disjoint from
development and regression regions.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import json

from phase_q.common import make_run_id, save_json, save_text, utcnow_iso

# Thresholds frozen BEFORE final execution (Q10). No post-hoc tuning.
FROZEN_THRESHOLDS: Dict[str, Dict[str, Any]] = {
    "connector_endpoint_residual_m": {"value": 0.05, "distribution": "p95"},
    "heading_residual_deg": {"value": 1.0, "distribution": "p95"},
    "visual_collision_residual_m": {"value": 0.10, "distribution": "p95"},
    "lidar_camera_projection_residual_m": {"value": 0.20, "distribution": "p95"},
    "sensor_frame_loss_ratio": {"value": 0.01, "distribution": "max"},
    "route_completion_ratio": {"value": 0.98, "distribution": "min"},
    "collision_rate_per_km": {"value": 0.0, "distribution": "max"},
    "lane_invasion_rate_per_km": {"value": 12.0, "distribution": "max"},
    "elevation_seam_m": {"value": 0.05, "distribution": "p95"},
    "fps_min": {"value": 15.0, "distribution": "min"},
    "frame_time_p95_ms": {"value": 66.7, "distribution": "p95"},
    "frame_time_p99_ms": {"value": 100.0, "distribution": "p99"},
    "memory_growth_mb_per_hour": {"value": 500.0, "distribution": "max"},
    "gnss_residual_m": {"value": 2.0, "distribution": "p95"},
    "semantic_unknown_rate": {"value": 0.02, "distribution": "max"},
}


def default_protocol() -> Dict[str, Any]:
    return {
        "schema": "Q11_EVALUATION_PROTOCOL/v1",
        "protocol_version": "1.0",
        "frozen_at": utcnow_iso(),
        "development_regions": [{"name": "city_center_dev", "bounds": [None]}],
        "regression_regions": [{"name": "r1_ring", "bounds": [None]}],
        "holdout_regions": [{"name": "holdout_east", "bounds": [None]}],
        "route_seeds": [1, 2, 3, 4, 5],
        "weather_seeds": [100, 200, 300],
        "camera_poses": [{"x": None, "y": None, "z": None, "yaw": 0}],
        "sensor_config": {
            "rgb": {"res": [1280, 720], "fov": 90},
            "depth": {"res": [1280, 720]},
            "semantic": {"res": [1280, 720]},
            "lidar": {"channels": 32, "range": 50},
            "gnss": {"rate": 10},
        },
        "thresholds_reference": "Q13_THRESHOLD_REGISTRY.json",
        "map_freeze_rule": (
            "map must NOT be modified after hold-out results are viewed "
            "without invalidating the final evaluation"),
    }


def validate_protocol(protocol: Dict[str, Any]) -> Dict[str, bool]:
    dr = set(r.get("name") for r in protocol.get("development_regions", []))
    rr = set(r.get("name") for r in protocol.get("regression_regions", []))
    hr = set(r.get("name") for r in protocol.get("holdout_regions", []))
    return {
        "holdout_disjoint_from_dev": not (hr & dr),
        "holdout_disjoint_from_regression": not (hr & rr),
        "has_frozen_thresholds": bool(protocol.get("thresholds_reference")),
        "all_holdout_named": all(r.get("name") for r in hr),
    }


def holdout_geojson(protocol: Dict[str, Any]) -> Dict[str, Any]:
    features = []
    for region in protocol.get("holdout_regions", []):
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": region.get("bounds") or [],
            },
            "properties": {"name": region.get("name")},
        })
    return {"type": "FeatureCollection", "features": features}


def write_protocol_outputs(out_dir: str) -> Dict[str, str]:
    proto = default_protocol()
    p = save_json(f"{out_dir}/Q11_EVALUATION_PROTOCOL.json", proto)
    h = save_json(f"{out_dir}/Q12_HOLDOUT_REGION_REGISTRY.geojson",
                  holdout_geojson(proto))
    t = save_json(f"{out_dir}/Q13_THRESHOLD_REGISTRY.json", {
        "schema": "Q13_THRESHOLD_REGISTRY/v1",
        "frozen_before_run": True,
        "selected_after_results": False,
        "thresholds": FROZEN_THRESHOLDS,
    })
    return {
        "Q11_EVALUATION_PROTOCOL.json": p,
        "Q12_HOLDOUT_REGION_REGISTRY.geojson": h,
        "Q13_THRESHOLD_REGISTRY.json": t,
    }
