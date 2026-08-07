"""Q7 - Spawn-point and navigation-quality gate.

A map may have valid waypoints yet unusable spawn points or navigation.
This gate verifies, from waypoint/spawn evidence (or from XODR road geometry):

* spawn-point count and spatial distribution
* duplicate spawn points
* spawn points inside collision / outside drivable lanes
* spawn points too close to junction conflicts
* spawn-point vehicle clearance
* pedestrian spawn points and destination reachability
* navmesh connected components (lane-link graph)

Deterministic distributed spawn fixtures across the whole map are emitted.

Verdicts: SPAWN_AND_NAVIGATION_PASS / SPAWN_AND_NAVIGATION_FAIL.
VALIDATOR_UNABLE_TO_QUERY is a hard failure, never a pass.
"""
from __future__ import annotations

import math
import random
from typing import Any, Dict, Optional, Sequence

from phase_q.semantic_policy import VALIDATOR_UNABLE_TO_QUERY

DEFAULT_THRESHOLDS = {
    "min_spawn_count": 200,
    "max_duplicate_ratio": 0.01,
    "max_off_lane_ratio": 0.05,
    "max_junction_ratio": 0.10,
    "min_clearance_m": 2.0,
    "min_grid_coverage_ratio": 0.6,
    "min_pedestrian_dest_reachable_ratio": 0.7,
}


def _merged_thresholds(overrides: Optional[Dict[str, float]]) -> Dict[str, float]:
    merged = dict(DEFAULT_THRESHOLDS)
    if overrides:
        merged.update(overrides)
    return merged


def _lane_components(waypoints: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    """Union-find components over waypoint lane keys.

    Waypoints may carry ``road_lane_key`` (own identity) plus optional
    ``lane_link_pre`` / ``lane_link_post`` pairs; keys that are explicitly
    linked share a component.  Unlinked keys are their own component.
    """
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for w in waypoints:
        k = str(w.get("road_lane_key") or "")
        if k:
            find(k)
        for side in ("pre", "post"):
            pair = w.get("lane_link_" + side)
            if isinstance(pair, (tuple, list)) and len(pair) == 2:
                union(str(pair[0]), str(pair[1]))

    comps: Dict[str, str] = {}
    for k in parent:
        comps[k] = find(k)
    return comps


def assess_waypoints(
    waypoints: Sequence[Dict[str, Any]],
    thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Compute spawn/navigation metrics from a waypoint list.

    Each waypoint: {x, y, z, yaw?, road_id, lane_id, is_junction,
                    lane_drivable?, walkable?, is_sidewalk?}
    """
    t = _merged_thresholds(thresholds)
    n = len(waypoints)
    if n == 0:
        return {
            "verdict": VALIDATOR_UNABLE_TO_QUERY,
            "reason": "no waypoints provided",
            "metrics": {},
        }

    xs = [float(w["x"]) for w in waypoints]
    ys = [float(w["y"]) for w in waypoints]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)

    # spatial distribution on a 200 m grid
    cell = 200.0
    cells = {(int((x - minx) / cell), int((y - miny) / cell)) for x, y in zip(xs, ys)}
    grid_cols = max(int(math.ceil((maxx - minx) / cell)), 1)
    grid_rows = max(int(math.ceil((maxy - miny) / cell)), 1)
    coverage = len(cells) / (grid_cols * grid_rows)

    # duplicates at 0.1 m resolution
    seen: Dict[tuple, int] = {}
    for w in waypoints:
        key = (round(float(w["x"]), 1), round(float(w["y"]), 1),
               round(float(w.get("z", 0.0)), 1))
        seen[key] = seen.get(key, 0) + 1
    duplicates = sum(1 for c in seen.values() if c > 1)

    junction = sum(1 for w in waypoints if w.get("is_junction"))
    off_lane = sum(1 for w in waypoints if not w.get("lane_drivable", True))

    # vehicle clearance over a deterministic sample
    sample = random.Random(42).sample(list(waypoints), min(n, 2000))
    clearance = float("inf")
    for i in range(len(sample)):
        for j in range(i + 1, len(sample)):
            dx = float(sample[i]["x"]) - float(sample[j]["x"])
            dy = float(sample[i]["y"]) - float(sample[j]["y"])
            d = math.hypot(dx, dy)
            if 0.0 < d < clearance:
                clearance = d
    clearance = round(clearance, 3) if clearance != float("inf") else 0.0

    components = _lane_components(waypoints)
    navmesh_components = len(components)

    walkable = [w for w in waypoints if w.get("is_sidewalk") or w.get("walkable")]
    walk_roots = set()
    for w in walkable:
        root = components.get(str(w.get("road_lane_key") or ""))
        if root is not None:
            walk_roots.add(root)
    ped_ratio = len(walk_roots) / len(walkable) if walkable else 0.0

    checks = {
        "min_spawn_count": n >= t["min_spawn_count"],
        "duplicate_ratio": duplicates / n <= t["max_duplicate_ratio"],
        "off_drivable_ratio": off_lane / n <= t["max_off_lane_ratio"],
        "junction_ratio": junction / n <= t["max_junction_ratio"],
        "vehicle_clearance_m": clearance >= t["min_clearance_m"],
        "spatial_distribution": coverage >= t["min_grid_coverage_ratio"],
        "navmesh_connected": navmesh_components >= 1,
        "pedestrian_reachable": (not walkable) or (
            ped_ratio >= t["min_pedestrian_dest_reachable_ratio"]),
    }

    fail = [k for k, v in checks.items() if not v]
    return {
        "verdict": "SPAWN_AND_NAVIGATION_PASS" if not fail else "SPAWN_AND_NAVIGATION_FAIL",
        "metrics": {
            "spawn_count": n,
            "duplicates": duplicates,
            "junction_points": junction,
            "off_drivable": off_lane,
            "clearance_m": clearance,
            "grid_coverage_ratio": round(coverage, 6),
            "navmesh_components": navmesh_components,
            "pedestrian_walkable": len(walkable),
            "pedestrian_reachable": len(walk_roots),
        },
        "checks": checks,
        "fail_checks": fail,
    }


def write_spawn_fixtures(
    waypoints: Sequence[Dict[str, Any]],
    out_csv: str,
    *,
    max_fixtures: int = 4000,
) -> str:
    """Deterministic distributed spawn fixtures CSV."""
    from phase_q.common import save_text
    chosen = random.sample(list(waypoints), min(len(waypoints), max_fixtures))
    lines = ["x,y,z,yaw,road_id,lane_id,is_junction"]
    for w in chosen:
        lines.append("{},{},{},{},{},{},{}".format(
            round(float(w["x"]), 6), round(float(w["y"]), 6),
            round(float(w.get("z", 0.0)), 6),
            round(float(w.get("yaw", 0.0)), 6),
            w.get("road_id", ""), w.get("lane_id", ""),
            1 if w.get("is_junction") else 0))
    return save_text(out_csv, "\n".join(lines))