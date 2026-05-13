#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Shared logic for runtime enrichment spawning and QA capture in CARLA.
Used by run_perception_pair.py and run_perception_safe.py.
"""

from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ultimate_pipeline.carla_tools import spawn_enrichments as enrich_mod
from ultimate_pipeline.optional.carla_api import get_carla

def parse_type_filter(filter_str: str) -> Optional[set[str]]:
    """Parse and canonicalize a comma-separated type filter string."""
    normalized = _normalize_type_set(
        token for token in str(filter_str or "").split(",") if str(token).strip()
    )
    return normalized or None


# Canonical runtime classes required by thesis orchestration.
CANONICAL_REQUIRED_TYPES = frozenset(
    {"building", "tree", "vegetation_proxy", "pole", "barrier"}
)

_TYPE_ALIASES: Dict[str, str] = {
    # Building-like
    "building": "building",
    "buildings": "building",
    "building_proxy": "building",
    "structure": "building",
    "house": "building",
    "facade": "building",
    # Pole-like
    "pole": "pole",
    "post": "pole",
    "light_pole": "pole",
    "street_light": "pole",
    "streetlight": "pole",
    "lamp_post": "pole",
    "signpost": "pole",
    "utility_pole": "pole",
    # Vegetation
    "tree": "tree",
    "trees": "tree",
    "street_tree": "tree",
    "vegetation": "vegetation_proxy",
    "vegetation_proxy": "vegetation_proxy",
    "bush": "vegetation_proxy",
    "hedge": "vegetation_proxy",
    "grass": "vegetation_proxy",
    # Signal/signage
    "traffic_light": "traffic_light",
    "traffic_signal": "traffic_light",
    "signal_light": "traffic_light",
    "sign": "sign",
    "traffic_sign": "sign",
    "streetsign": "sign",
    # Street furniture
    "bench": "bench",
    "seat": "bench",
    "bin": "bin",
    "trash_bin": "bin",
    "trashcan": "bin",
    "waste_bin": "bin",
    # Vehicle proxy
    "parked_vehicle": "parked_vehicle",
    "parked_car": "parked_vehicle",
    "car": "parked_vehicle",
    "vehicle": "parked_vehicle",
    # Barrier-like
    "barrier": "barrier",
    "street_barrier": "barrier",
    "streetbarrier": "barrier",
    "fence": "barrier",
    "fence_proxy": "barrier",
    "guardrail": "guardrail",
    "railing": "guardrail",
    "bollard": "barrier",
}


def normalize_enrichment_type(raw_type: Any) -> str:
    token = str(raw_type or "").strip().lower()
    if not token:
        return "building"
    token = token.replace("-", "_").replace(" ", "_")
    token = token.strip("_")
    if not token:
        return "building"
    return _TYPE_ALIASES.get(token, token)


def _normalize_type_set(raw_types: Iterable[Any]) -> set[str]:
    return {
        normalize_enrichment_type(raw_type)
        for raw_type in raw_types
        if str(raw_type or "").strip()
    }


def normalize_enrichment_object(obj: Dict[str, Any]) -> Dict[str, Any]:
    normalized_obj = dict(obj or {})
    raw_type = normalized_obj.get(
        "normalized_type",
        normalized_obj.get("type", normalized_obj.get("object_type", "building")),
    )
    canonical_type = normalize_enrichment_type(raw_type)
    # Keep backward compatibility with both key names while exposing canonical type.
    normalized_obj["normalized_type"] = canonical_type
    normalized_obj["type"] = canonical_type
    normalized_obj["object_type"] = canonical_type
    return normalized_obj


def _normalize_enrichment_list(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized.append(normalize_enrichment_object(item))
    return normalized


def compute_missing_required_types(
    enrichments: List[Dict[str, Any]],
    required_types: Optional[set[str]],
) -> List[str]:
    if not required_types:
        return []
    normalized_required = _normalize_type_set(required_types)
    found_types = {
        normalize_enrichment_type(
            obj.get("normalized_type", obj.get("type", obj.get("object_type", "building")))
        )
        for obj in enrichments
        if isinstance(obj, dict)
    }
    return sorted(list(normalized_required - found_types))

def load_and_sample_enrichments(
    enrichments_path: str,
    *,
    limit: int = 500,
    seed: int = 1337,
    type_filter: Optional[set[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Load enrichments from JSON, filter by type, and sample deterministically.
    """
    normalized_filter = _normalize_type_set(type_filter or [])
    enrichments = _normalize_enrichment_list(enrich_mod.load_enrichments(enrichments_path))
    summary: Dict[str, Any] = {
        "path": str(enrichments_path),
        "total_loaded": len(enrichments),
        "filtered_count": 0,
        "sampled_count": 0,
        "limit": int(limit),
        "seed": int(seed),
        "filter": sorted(list(normalized_filter)) if normalized_filter else None,
        "canonical_required_types": sorted(list(CANONICAL_REQUIRED_TYPES)),
    }

    if normalized_filter:
        filtered = []
        for obj in enrichments:
            obj_type = str(obj.get("normalized_type", "building"))
            if obj_type in normalized_filter:
                filtered.append(obj)
        summary["filtered_count"] = len(filtered)
        enrichments = filtered
    else:
        summary["filtered_count"] = len(enrichments)

    if 0 < limit < len(enrichments):
        rng = random.Random(int(seed))
        sampled_indices = sorted(rng.sample(range(len(enrichments)), k=int(limit)))
        enrichments = [enrichments[i] for i in sampled_indices]
        summary["sampled_count"] = len(enrichments)
    else:
        summary["sampled_count"] = len(enrichments)

    summary["filtered_types_present"] = sorted(
        {
            str(obj.get("normalized_type", "building"))
            for obj in enrichments
            if isinstance(obj, dict)
        }
    )
    per_type_counts: Dict[str, int] = {}
    for obj in enrichments:
        if not isinstance(obj, dict):
            continue
        t = str(obj.get("normalized_type", "building"))
        per_type_counts[t] = int(per_type_counts.get(t, 0)) + 1
    summary["per_type_counts"] = per_type_counts

    return enrichments, summary

def spawn_runtime_enrichments(
    host: str,
    port: int,
    enrichments_path: str,
    *,
    out_dir: Path,
    limit: int = 500,
    seed: int = 1337,
    type_filter: Optional[set[str]] = None,
    required_types: Optional[set[str]] = None,
    label: str = "runtime",
) -> Dict[str, Any]:
    """
    Generalized enrichment spawner for perception runners.
    """
    normalized_filter = _normalize_type_set(type_filter or [])
    normalized_required_types = _normalize_type_set(required_types or [])

    report: Dict[str, Any] = {
        "enabled": True,
        "path": str(enrichments_path),
        "spawned_ids": [],
        "actor_ids": [],
        "spawned_count": 0,
        "failed_count": 0,
        "requested_count": 0,
        "per_type_requested": {},
        "per_type_spawned": {},
        "per_type_failed": {},
        "generic_fallback_count": 0,
        "unmapped_types": [],
        "unsupported_blueprints": [],
        "missing_required_types": [],
        "required_types": sorted(list(normalized_required_types)),
        "type_filter": sorted(list(normalized_filter)) if normalized_filter else None,
        "error": None,
    }

    if not os.path.isfile(enrichments_path):
        report["error"] = "enrichments_file_missing"
        return report

    try:
        enrichments, selection = load_and_sample_enrichments(
            enrichments_path, limit=limit, seed=seed, type_filter=normalized_filter
        )
        report["selection"] = selection
        report["missing_required_types"] = compute_missing_required_types(
            enrichments,
            normalized_required_types,
        )
        report["requested_count"] = len(enrichments)
        report["per_type_requested"] = dict(selection.get("per_type_counts", {}))
    except Exception as exc:
        report["error"] = f"load_failed: {exc}"
        return report

    if not enrichments:
        report["error"] = "no_enrichments_after_filter"
        return report

    try:
        carla = get_carla()
        client = carla.Client(host, int(port))
        client.set_timeout(10.0)

        # Write temp filtered list for spawn_enrichments compatibility
        tmp_path = out_dir / f"enrichments_spawn_{label}.json"
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(enrichments, f, indent=2, ensure_ascii=True)

        spawned = enrich_mod.spawn_enrichments(
            client, str(tmp_path), max_objects=max(1, limit) if limit > 0 else 500
        )
        if isinstance(spawned, dict):
            actor_ids = [int(aid) for aid in (spawned.get("actor_ids") or [])]
            report["actor_ids"] = actor_ids
            report["spawned_ids"] = list(actor_ids)
            report["spawned_count"] = int(spawned.get("spawned_count", len(actor_ids)))
            report["failed_count"] = int(
                spawned.get("failed_count", max(0, len(enrichments) - len(actor_ids)))
            )
            report["requested_count"] = int(
                spawned.get("requested_count", report.get("requested_count", len(enrichments)))
            )
            report["per_type_requested"] = dict(
                spawned.get("per_type_requested", report.get("per_type_requested", {}))
            )
            report["per_type_spawned"] = dict(spawned.get("per_type_spawned", {}))
            report["per_type_failed"] = dict(spawned.get("per_type_failed", {}))
            report["generic_fallback_count"] = int(
                spawned.get("generic_fallback_count", 0)
            )
            report["unmapped_types"] = sorted(
                {
                    str(t)
                    for t in (spawned.get("unmapped_types") or [])
                    if str(t or "").strip()
                }
            )
            report["unsupported_blueprints"] = sorted(
                {
                    str(t)
                    for t in (spawned.get("unsupported_blueprints") or [])
                    if str(t or "").strip()
                }
            )
            if spawned.get("error"):
                report["error"] = str(spawned.get("error"))
        else:
            actor_ids = [int(aid) for aid in (spawned or [])]
            report["actor_ids"] = actor_ids
            report["spawned_ids"] = list(actor_ids)
            report["spawned_count"] = len(actor_ids)
            report["failed_count"] = len(enrichments) - len(actor_ids)
            report["per_type_spawned"] = {}
            report["per_type_failed"] = {}
    except Exception as exc:
        report["error"] = f"spawn_failed: {exc}"

    return report

def destroy_runtime_enrichments(host: str, port: int, actor_ids: List[int]) -> int:
    """Destroy actors by ID."""
    if not actor_ids:
        return 0
    try:
        carla = get_carla()
        client = carla.Client(host, int(port))
        client.set_timeout(10.0)
        return int(enrich_mod.destroy_spawned_actors(client, actor_ids))
    except Exception:
        return 0

def capture_qa_bundle(
    host: str,
    port: int,
    calib_path: str,
    out_dir: Path,
    rig_type: str = "thesis",
) -> Dict[str, Any]:
    """
    Capture a single-frame QA bundle using ThesisSensorRig if requested.
    """
    report: Dict[str, Any] = {
        "enabled": True,
        "qa_bundle_written": False,
        "error": None,
    }
    try:
        from ultimate_pipeline.sensors.attach_sensors_safe import attach_sensors_safe
        from ultimate_pipeline.sensors.recorder import SensorRecorder, RecorderConfig
        carla = get_carla()
        client = carla.Client(host, int(port))
        client.set_timeout(15.0)
        world = client.get_world()
        
        # Find ego vehicle
        ego = None
        for actor in world.get_actors().filter("vehicle.*"):
            if actor.attributes.get("role_name") in ("hero", "ego"):
                ego = actor
                break
        
        if not ego:
            # Fallback: check if any vehicle exists
            all_vehicles = list(world.get_actors().filter("vehicle.*"))
            if all_vehicles:
                ego = all_vehicles[0]
        
        spawned_temp_ego = False
        if not ego:
            print("[capture_qa_bundle] No ego vehicle found, spawning temporary vehicle for QA...")
            bp_lib = world.get_blueprint_library()
            veh_bp = bp_lib.filter("vehicle.tesla.model3")[0]
            spawns = world.get_map().get_spawn_points()
            spawn_tf = spawns[0] if spawns else carla.Transform(carla.Location(z=2.0))
            ego = world.try_spawn_actor(veh_bp, spawn_tf)
            if ego:
                spawned_temp_ego = True
        
        if not ego:
            report["error"] = "ego_vehicle_not_found"
            return report

        qa_dir = out_dir / "qa_bundle"
        qa_dir.mkdir(parents=True, exist_ok=True)

        # Attach sensors
        sensors, attach_report = attach_sensors_safe(world, ego, calib_path, str(qa_dir))
        if not sensors:
            if spawned_temp_ego:
                ego.destroy()
            report["error"] = f"sensor_attach_failed: {attach_report.get('errors')}"
            return report

        # Record ONE tick
        config = RecorderConfig(fps=10)
        recorder = SensorRecorder(world, ego, sensors, out_dir=str(qa_dir), cfg=config)
        
        # Tick until we get frames or timeout
        recorder.start()
        world.tick()
        time.sleep(0.5) # Wait for callbacks
        recorder.stop()
        
        # Manually destroy QA sensors
        for s in sensors.values():
            try:
                s.destroy()
            except Exception:
                pass
        
        if spawned_temp_ego:
            ego.destroy()

        report["qa_bundle_written"] = True
    except Exception as exc:
        report["error"] = f"qa_capture_failed: {exc}"
    
    return report
