"""C16 step 1-2 — semantic tag-per-mesh scaffold for the UE cook (dry-run, no UE).

Assigns a CARLA `carla.CityObjectLabel` to every mesh produced by the
OSM2World -> Blender -> FBX cook, so the packaged map carries correct
per-mesh semantics for the perception rig's semantic camera (reused by C8's
raw-id reader).

Ground truth for CITY_OBJECT_LABELS is the *actual* `carla.CityObjectLabel`
enum from the installed CARLA Python API (extracted and hardcoded here so
this module works without importing `carla` at runtime -- see
tests/unit/test_semantic_tagging.py::test_city_object_labels_match_real_carla_enum,
which cross-checks it against the real enum whenever CARLA is importable).

**Honesty note:** the KEYWORD_RULES below are a best-effort classifier
based on OSM tag vocabulary and OSM2World's public material-naming
convention -- this project has not yet run a real OSM2World cook to verify
the *exact* mesh/material name strings it emits for this map. The
mechanism (fail-closed on anything unmatched, via validate_semantic_tags)
is what makes this safe to ship ahead of that verification: an unmapped
mesh is a reported gate FAILURE, never a silent default/guess. Extend
KEYWORD_RULES once a real cook's mesh names are available to check against.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

# Ground truth: carla.CityObjectLabel (CARLA 0.9.16), extracted from the
# installed package. NONE=0 and Any=255 are intentionally excluded from
# CITY_OBJECT_LABELS -- neither is a valid *assigned* tag (Any is CARLA's
# sentinel for "no filter", NONE means "not classified").
CITY_OBJECT_LABELS: Dict[str, int] = {
    "Roads": 1, "Sidewalks": 2, "Buildings": 3, "Walls": 4, "Fences": 5,
    "Poles": 6, "TrafficLight": 7, "TrafficSigns": 8, "Vegetation": 9,
    "Terrain": 10, "Sky": 11, "Pedestrians": 12, "Rider": 13, "Car": 14,
    "Truck": 15, "Bus": 16, "Train": 17, "Motorcycle": 18, "Bicycle": 19,
    "Static": 20, "Dynamic": 21, "Other": 22, "Water": 23, "RoadLines": 24,
    "Ground": 25, "Bridge": 26, "RailTrack": 27, "GuardRail": 28,
}
NONE_LABEL_ID = 0
ANY_LABEL_ID = 255

# Static-scenery labels only: a map cook bakes static geometry, not the
# dynamic actors (Pedestrians/Rider/Car/Truck/Bus/Train/Motorcycle/Bicycle)
# CARLA spawns at runtime -- those are out of scope for this classifier.
STATIC_SCENERY_LABELS = {
    name for name in CITY_OBJECT_LABELS
    if name not in {"Pedestrians", "Rider", "Car", "Truck", "Bus", "Train", "Motorcycle", "Bicycle"}
}

# Ordered (substring, label_name) rules -- checked top to bottom, first
# match wins, so more specific keywords must precede their generic
# supersets (e.g. "guardrail" before "rail", "roadline" before "road").
KEYWORD_RULES: List[Tuple[str, str]] = [
    ("roadline", "RoadLines"),
    ("road_marking", "RoadLines"),
    ("laneline", "RoadLines"),
    ("guardrail", "GuardRail"),
    ("guard_rail", "GuardRail"),
    ("sidewalk", "Sidewalks"),
    ("footway", "Sidewalks"),
    ("pavement", "Sidewalks"),
    ("trafficlight", "TrafficLight"),
    ("traffic_light", "TrafficLight"),
    ("signal_head", "TrafficLight"),
    ("trafficsign", "TrafficSigns"),
    ("traffic_sign", "TrafficSigns"),
    ("stop_sign", "TrafficSigns"),
    ("speed_limit", "TrafficSigns"),
    ("streetlight", "Poles"),
    ("lamp_post", "Poles"),
    ("pole", "Poles"),
    ("mast", "Poles"),
    ("bridge", "Bridge"),
    ("railway", "RailTrack"),
    ("rail_track", "RailTrack"),
    ("rail", "RailTrack"),
    ("building", "Buildings"),
    ("roof", "Buildings"),
    ("wall", "Walls"),
    ("fence", "Fences"),
    ("barrier", "Fences"),
    ("forest", "Vegetation"),
    ("woodland", "Vegetation"),
    ("tree", "Vegetation"),
    ("vegetation", "Vegetation"),
    ("hedge", "Vegetation"),
    ("scrub", "Vegetation"),
    ("grass", "Vegetation"),
    ("water", "Water"),
    ("river", "Water"),
    ("lake", "Water"),
    ("pond", "Water"),
    ("terrain", "Terrain"),
    ("meadow", "Terrain"),
    ("field", "Terrain"),
    ("earth", "Ground"),
    ("dirt", "Ground"),
    ("sand", "Ground"),
    ("gravel", "Ground"),
    ("ground", "Ground"),
    ("asphalt", "Roads"),
    ("carriageway", "Roads"),
    ("highway", "Roads"),
    ("street", "Roads"),
    ("road", "Roads"),
]


def classify_mesh_or_material_name(name: str) -> Optional[str]:
    """Return the matched CityObjectLabel name, or None if nothing matched."""
    lowered = str(name or "").lower()
    for keyword, label in KEYWORD_RULES:
        if keyword in lowered:
            return label
    return None


def classify_mesh(mesh: Dict[str, Any]) -> Dict[str, Any]:
    """Classify a single mesh-inventory entry (the same shape fbx_roundtrip.py
    already produces: name/type/vertices/faces/materials/bounds).

    Tries the object name first, then each material name, in order --
    whichever matches first wins. Reports which source matched, for
    auditability.
    """
    name = str(mesh.get("name") or "")
    label = classify_mesh_or_material_name(name)
    if label:
        return {"mesh": name, "label": label, "label_id": CITY_OBJECT_LABELS[label], "matched_via": "name"}
    for material in mesh.get("materials") or []:
        label = classify_mesh_or_material_name(material)
        if label:
            return {"mesh": name, "label": label, "label_id": CITY_OBJECT_LABELS[label],
                     "matched_via": f"material:{material}"}
    return {"mesh": name, "label": None, "label_id": None, "matched_via": None}


def tag_mesh_inventory(objects: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Classify every mesh in an inventory (e.g. an fbx_roundtrip.py manifest's
    'objects' list, or an osm2world_runner.py output manifest)."""
    tags = [classify_mesh(o) for o in objects]
    unmatched = [t["mesh"] for t in tags if t["label"] is None]
    return {
        "mesh_count": len(tags),
        "tags": tags,
        "unmatched_count": len(unmatched),
        "unmatched_meshes": unmatched,
    }


def validate_semantic_tags(tag_report: Dict[str, Any]) -> Dict[str, Any]:
    """The fail-closed gate (C16 step 2): every mesh must have a valid,
    non-None, non-Any CityObjectLabel. A mesh with no match is a gate
    FAILURE, never silently accepted."""
    unmatched = tag_report.get("unmatched_meshes") or []
    invalid_ids = [
        t["mesh"] for t in tag_report.get("tags", [])
        if t["label_id"] is not None
        and (t["label_id"] not in CITY_OBJECT_LABELS.values() or t["label_id"] in (NONE_LABEL_ID, ANY_LABEL_ID))
    ]
    ok = not unmatched and not invalid_ids and tag_report.get("mesh_count", 0) > 0
    return {
        "ok": ok,
        "mesh_count": tag_report.get("mesh_count", 0),
        "unmatched_meshes": unmatched,
        "invalid_label_meshes": invalid_ids,
        "verdict": "SEMANTIC_TAGS_OK" if ok else "SEMANTIC_TAGS_INCOMPLETE",
    }
