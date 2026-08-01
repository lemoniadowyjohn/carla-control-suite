# ultimate_pipeline/carla_tools/spawn_enrichments.py
# -*- coding: utf-8 -*-

"""
Runtime spawner for enrichment objects in CARLA.

IMPORTANT CONTEXT:
-----------------
OpenDRIVE <object> elements (buildings, fences, poles, etc.) do NOT automatically
appear as 3D meshes when loading an XODR into CARLA. The CARLA OpenDRIVE importer
only uses road geometries to generate drivable surfaces.

To visualize buildings/enrichments, you must either:
1. Use a custom UE4/UE5 project that imports the XODR and generates meshes
2. Run this script at runtime to spawn proxy actors (cubes, static meshes)

This script:
- Reads an enrichments.json file (produced by the pipeline's building_extruder)
- Spawns simple proxy actors (static props/vehicles) at enrichment locations
- Is optional - the pipeline does NOT require this for success

Usage:
------
    python spawn_enrichments.py enrichments.json --host localhost --port 2000

Or programmatically:
    from ultimate_pipeline.carla_tools.spawn_enrichments import spawn_enrichments
    spawn_report = spawn_enrichments(client, "enrichments.json")
    actor_ids = spawn_report["actor_ids"]
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional, Set, Tuple

# CARLA import is optional (script can be imported for documentation)
try:
    import carla

    CARLA_AVAILABLE = True
except ImportError:
    carla = None
    CARLA_AVAILABLE = False


def load_enrichments(json_path: str) -> List[Dict[str, Any]]:
    """
    Load enrichment objects from a JSON file.

    Expected format (one of these):
    1. List of objects:
       [{"x": ..., "y": ..., "z": ..., "type": "building", ...}, ...]

    2. Dict with "objects" or "buildings" key:
       {"buildings": [...], "metadata": {...}}
    """
    if not os.path.exists(json_path):
        print(f"[spawn_enrichments] File not found: {json_path}")
        return []

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("objects", "buildings", "enrichments", "items"):
            if key in data and isinstance(data[key], list):
                return data[key]
        if "x" in data and "y" in data:
            return [data]

    print(f"[spawn_enrichments] Unrecognized format in {json_path}")
    return []


_TYPE_ALIASES: Dict[str, str] = {
    "building": "building",
    "buildings": "building",
    "structure": "building",
    "house": "building",
    "tree": "tree",
    "trees": "tree",
    "vegetation_proxy": "vegetation_proxy",
    "vegetation": "vegetation_proxy",
    "bush": "vegetation_proxy",
    "hedge": "vegetation_proxy",
    "pole": "pole",
    "post": "pole",
    "light_pole": "pole",
    "traffic_light": "traffic_light",
    "traffic_signal": "traffic_light",
    "sign": "sign",
    "traffic_sign": "sign",
    "guardrail": "guardrail",
    "railing": "guardrail",
    "fence": "fence",
    "barrier": "barrier",
    "streetbarrier": "barrier",
    "street_barrier": "barrier",
    "bench": "bench",
    "bin": "bin",
    "trash_bin": "bin",
    "parked_vehicle": "parked_vehicle",
    "car": "parked_vehicle",
    "vehicle": "parked_vehicle",
}


_SEMANTIC_BLUEPRINT_CANDIDATES: Dict[str, List[str]] = {
    "building": ["static.prop.box01"],
    "tree": ["static.prop.tree01"],
    "vegetation_proxy": ["static.prop.tree01", "static.prop.box01"],
    "pole": ["static.prop.streetsign"],
    "traffic_light": ["static.prop.streetsign", "static.prop.trafficwarning"],
    "sign": ["static.prop.streetsign"],
    "guardrail": ["static.prop.streetbarrier", "static.prop.fence01"],
    "fence": ["static.prop.fence01"],
    "barrier": ["static.prop.streetbarrier"],
    "bench": ["static.prop.bench01"],
    "bin": ["static.prop.trashcan", "static.prop.garbage01", "static.prop.box01"],
    "parked_vehicle": [
        "vehicle.tesla.model3",
        "vehicle.audi.a2",
        "vehicle.mini.cooper_s",
    ],
}


def _canonical_type(raw_type: Any) -> str:
    token = str(raw_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    token = token.strip("_")
    if not token:
        return "building"
    return _TYPE_ALIASES.get(token, token)


def get_proxy_blueprint(
    world: "carla.World",
    obj_type: str,
) -> Tuple[Optional["carla.ActorBlueprint"], Dict[str, Any]]:
    """
    Resolve semantic blueprint candidates for the requested type.

    Returns:
      (blueprint or None, resolution metadata)
    """
    bp_lib = world.get_blueprint_library()
    canonical_type = _canonical_type(obj_type)
    requested_type = str(obj_type or "").strip().lower()
    unmapped_type = canonical_type not in _SEMANTIC_BLUEPRINT_CANDIDATES
    candidates = list(
        _SEMANTIC_BLUEPRINT_CANDIDATES.get(
            canonical_type, _SEMANTIC_BLUEPRINT_CANDIDATES["building"]
        )
    )
    unsupported: List[str] = []

    for candidate in candidates:
        try:
            bp = bp_lib.find(candidate)
            return bp, {
                "requested_type": requested_type,
                "canonical_type": canonical_type,
                "selected_blueprint_id": str(getattr(bp, "id", candidate)),
                "used_generic_fallback": False,
                "unmapped_type": bool(unmapped_type),
                "unsupported_blueprints": unsupported,
            }
        except Exception:
            unsupported.append(str(candidate))

    # Deterministic generic fallback in low-resource/missing-blueprint cases.
    generic_props: List["carla.ActorBlueprint"] = sorted(
        [bp for bp in bp_lib if str(getattr(bp, "id", "")).startswith("static.prop.")],
        key=lambda bp: str(getattr(bp, "id", "")),
    )
    if generic_props:
        bp = generic_props[0]
        return bp, {
            "requested_type": requested_type,
            "canonical_type": canonical_type,
            "selected_blueprint_id": str(getattr(bp, "id", "")),
            "used_generic_fallback": True,
            "unmapped_type": bool(unmapped_type),
            "unsupported_blueprints": unsupported,
        }

    return None, {
        "requested_type": requested_type,
        "canonical_type": canonical_type,
        "selected_blueprint_id": None,
        "used_generic_fallback": False,
        "unmapped_type": bool(unmapped_type),
        "unsupported_blueprints": unsupported,
    }


def spawn_enrichments(
    client: "carla.Client",
    json_path: str,
    max_objects: int = 500,
    z_offset: float = 0.5,
) -> Dict[str, Any]:
    """
    Spawn proxy actors for enrichment objects in CARLA.

    Returns:
      Structured spawn report:
      {
        requested_count, spawned_count, failed_count,
        per_type_requested, per_type_spawned, per_type_failed,
        generic_fallback_count, unmapped_types, unsupported_blueprints,
        actor_ids
      }
    """
    if not CARLA_AVAILABLE:
        raise RuntimeError("CARLA Python API not available. Install carla package.")

    world = client.get_world()
    enrichments = load_enrichments(json_path)
    report: Dict[str, Any] = {
        "json_path": str(json_path),
        "requested_count": 0,
        "spawned_count": 0,
        "failed_count": 0,
        "per_type_requested": {},
        "per_type_spawned": {},
        "per_type_failed": {},
        "generic_fallback_count": 0,
        "unmapped_types": [],
        "unsupported_blueprints": [],
        "actor_ids": [],
        "spawned_ids": [],
        "error": None,
    }

    if not enrichments:
        print("[spawn_enrichments] No enrichments to spawn.")
        report["error"] = "no_enrichments_to_spawn"
        return report

    if len(enrichments) > max_objects:
        print(f"[spawn_enrichments] Limiting to {max_objects} objects (had {len(enrichments)})")
        enrichments = enrichments[:max_objects]

    spawned_ids: List[int] = []
    failed_count = 0
    per_type_requested: Dict[str, int] = {}
    per_type_spawned: Dict[str, int] = {}
    per_type_failed: Dict[str, int] = {}
    unmapped_types: Set[str] = set()
    unsupported_blueprints: Set[str] = set()
    generic_fallback_count = 0

    for obj in enrichments:
        canonical_type = _canonical_type(
            obj.get("normalized_type", obj.get("type", obj.get("object_type", "building")))
        )
        per_type_requested[canonical_type] = per_type_requested.get(canonical_type, 0) + 1
        try:
            x = float(obj.get("x", 0))
            y = float(obj.get("y", 0))
            z = float(obj.get("z", 0)) + z_offset
            yaw = float(obj.get("yaw", obj.get("hdg", 0)))

            bp, bp_report = get_proxy_blueprint(world, canonical_type)
            if bool(bp_report.get("unmapped_type", False)):
                unmapped_types.add(canonical_type)
            for unsupported in bp_report.get("unsupported_blueprints", []) or []:
                unsupported_blueprints.add(str(unsupported))
            if bp is None:
                failed_count += 1
                per_type_failed[canonical_type] = per_type_failed.get(canonical_type, 0) + 1
                continue

            # CARLA uses left-handed coordinates; invert Y from OpenDRIVE-style inputs.
            transform = carla.Transform(
                carla.Location(x=x, y=-y, z=z),
                carla.Rotation(yaw=math.degrees(yaw)),
            )

            actor = world.try_spawn_actor(bp, transform)
            if actor is not None:
                spawned_ids.append(actor.id)
                per_type_spawned[canonical_type] = per_type_spawned.get(canonical_type, 0) + 1
                if bool(bp_report.get("used_generic_fallback", False)):
                    generic_fallback_count += 1
            else:
                failed_count += 1
                per_type_failed[canonical_type] = per_type_failed.get(canonical_type, 0) + 1
        except Exception as exc:
            failed_count += 1
            per_type_failed[canonical_type] = per_type_failed.get(canonical_type, 0) + 1
            if failed_count <= 5:
                print(f"[spawn_enrichments] Failed to spawn object: {exc}")

    print(f"[spawn_enrichments] Spawned {len(spawned_ids)} actors, {failed_count} failed")
    report["requested_count"] = int(len(enrichments))
    report["spawned_count"] = int(len(spawned_ids))
    report["failed_count"] = int(failed_count)
    report["per_type_requested"] = per_type_requested
    report["per_type_spawned"] = per_type_spawned
    report["per_type_failed"] = per_type_failed
    report["generic_fallback_count"] = int(generic_fallback_count)
    report["unmapped_types"] = sorted(unmapped_types)
    report["unsupported_blueprints"] = sorted(unsupported_blueprints)
    report["actor_ids"] = [int(aid) for aid in spawned_ids]
    report["spawned_ids"] = [int(aid) for aid in spawned_ids]
    return report


def destroy_spawned_actors(
    client: "carla.Client",
    actor_ids: List[int],
) -> int:
    """Destroy previously spawned enrichment actors."""
    if not CARLA_AVAILABLE:
        raise RuntimeError("CARLA Python API not available.")

    world = client.get_world()
    destroyed = 0

    for aid in actor_ids:
        try:
            actor = world.get_actor(aid)
            if actor is not None:
                actor.destroy()
                destroyed += 1
        except Exception as exc:
            print(f"[spawn_enrichments] Failed to destroy actor {aid}: {exc}")

    print(f"[spawn_enrichments] Destroyed {destroyed} actors")
    return destroyed


def main() -> int:
    """Command-line interface for spawning enrichments."""
    import argparse
    import time

    parser = argparse.ArgumentParser(
        description="Spawn enrichment proxy actors in CARLA",
        epilog="""
NOTE: OpenDRIVE <object> elements do NOT automatically appear in CARLA.
This script spawns simple proxy actors (props) at enrichment locations.
For real building meshes, use a custom UE4/UE5 project.
        """,
    )
    parser.add_argument("enrichments_json", help="Path to enrichments.json file")
    parser.add_argument("--host", default="localhost", help="CARLA server host")
    parser.add_argument("--port", type=int, default=2000, help="CARLA server port")
    parser.add_argument("--max-objects", type=int, default=500, help="Max objects to spawn")
    parser.add_argument("--z-offset", type=float, default=0.5, help="Vertical offset (m)")
    parser.add_argument("--timeout", type=float, default=10.0, help="Connection timeout")

    args = parser.parse_args()

    if not CARLA_AVAILABLE:
        print("ERROR: CARLA Python API not installed. Run: pip install carla")
        return 1

    try:
        client = carla.Client(args.host, args.port)
        client.set_timeout(args.timeout)
        print(f"Connected to CARLA at {args.host}:{args.port}")

        spawn_report = spawn_enrichments(
            client,
            args.enrichments_json,
            max_objects=args.max_objects,
            z_offset=args.z_offset,
        )
        actor_ids = [int(aid) for aid in (spawn_report.get("actor_ids") or [])]
        print(
            f"Spawned {int(spawn_report.get('spawned_count', 0))} enrichment proxies "
            f"({int(spawn_report.get('failed_count', 0))} failed)"
        )
        print("Press Ctrl+C to destroy actors and exit...")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nCleaning up...")
            destroy_spawned_actors(client, actor_ids)

    except Exception as e:
        print(f"ERROR: {e}")
        return 1

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

