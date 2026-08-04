#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Semantic partition of OSM2World OBJ objects (Phase J4).

Classifies each ``o``/``g`` object group into semantic classes using
OSM2World naming conventions (Buildings, Trees, Water, SurfaceArea/GroundArea,
Elevator, Bridge, Footway, ...), then reports per-class statistics and the
stable object-name list (deterministic for a given OSM input).

The partition is pure-python over the OBJ text: no Blender required.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

# OSM2World group/object name conventions (observed in 0.5.0-SNAPSHOT output:
# "g Buildings", "o Building0", "g Trees", "o Tree0", "g Water", "g Elevator",
# "g SurfaceArea", ...). Patterns are lower-cased, substring matching.
_SEMANTIC_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("building", ("building", "house", "block", "warehouse", "shed", "ruin")),
    ("tree", ("tree", "wood", "forest", "hedge")),
    ("water", ("water", "sea", "river", "canal", "lake", "pond")),
    ("ground", ("ground", "surface", "terrain", "area")),
    ("elevator", ("elevator", "lift")),
    ("bridge", ("bridge", "tunnel")),
    ("footway", ("footway", "path", "sidewalk", "track", "steps")),
    ("road", ("road", "highway", "street", "parking", "roundabout")),
    ("rail", ("rail", "track", "train", "station")),
    ("vegetation_other", ("meadow", "scrub", "grass")),
]


def classify_name(name: str) -> str:
    low = name.lower()
    for cls, patterns in _SEMANTIC_RULES:
        for pat in patterns:
            if pat in low:
                return cls
    return "other"


def parse_obj_objects(path: Path) -> List[Dict[str, Any]]:
    """
    Parse an OBJ into per-object records.

    Each record: {name, group, class, vertices, faces, materials, bounds}.
    """
    objects: List[Dict[str, Any]] = []
    current_group = ""
    current = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "g":
                current_group = " ".join(parts[1:])
            elif parts[0] == "o":
                current = {
                    "name": " ".join(parts[1:]) or "(unnamed)",
                    "group": current_group,
                    "class": "",
                    "vertices": 0,
                    "faces": 0,
                    "materials": [],
                    "bounds": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    "_xs": [], "_ys": [], "_zs": [],
                }
                objects.append(current)
            elif current is not None:
                if parts[0] == "v":
                    try:
                        current["_xs"].append(float(parts[1]))
                        current["_ys"].append(float(parts[2]))
                        current["_zs"].append(float(parts[3]))
                    except (ValueError, IndexError):
                        pass
                elif parts[0] == "f":
                    current["faces"] += 1
                elif parts[0] == "usemtl":
                    mat = " ".join(parts[1:])
                    if mat and mat not in current["materials"]:
                        current["materials"].append(mat)
    for obj in objects:
        obj["vertices"] = len(obj["_xs"])
        if obj["_xs"]:
            obj["bounds"] = [min(obj["_xs"]), min(obj["_ys"]), min(obj["_zs"]),
                             max(obj["_xs"]), max(obj["_ys"]), max(obj["_zs"])]
        del obj["_xs"], obj["_ys"], obj["_zs"]
        obj["class"] = classify_name(obj["group"]) if obj["group"] \
            else classify_name(obj["name"])
    return objects


def semantic_partition(path: Path) -> Dict[str, Any]:
    """J4: full semantic partition of an OBJ artifact."""
    objects = parse_obj_objects(path)
    classes: Dict[str, Dict[str, Any]] = {}
    object_names: List[str] = []
    for obj in objects:
        cls = obj["class"]
        bucket = classes.setdefault(cls, {
            "objects": 0, "faces": 0, "vertices": 0,
            "materials": set(), "example_names": [],
        })
        bucket["objects"] += 1
        bucket["faces"] += obj["faces"]
        bucket["vertices"] += obj["vertices"]
        bucket["materials"].update(obj["materials"])
        if len(bucket["example_names"]) < 10:
            bucket["example_names"].append(obj["name"])
        object_names.append(obj["name"])

    per_class = {}
    for cls, bucket in classes.items():
        per_class[cls] = {
            "objects": bucket["objects"],
            "faces": bucket["faces"],
            "vertices": bucket["vertices"],
            "materials": sorted(bucket["materials"]),
            "example_names": bucket["example_names"],
        }

    duplicate_names = sorted({
        name for name in object_names if object_names.count(name) > 1
    })
    return {
        "objects_total": len(objects),
        "classes": per_class,
        "object_name_count": len(object_names),
        "duplicate_object_names": duplicate_names,
        "deterministic_names": sorted(object_names),
        "classification_rule": "OSM2World group/object naming conventions "
                               "(case-insensitive substring, see _SEMANTIC_RULES)",
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("usage: semantic_partition.py <scene.obj>")
        sys.exit(2)
    result = semantic_partition(Path(sys.argv[1]))
    print(json.dumps(result, indent=2, sort_keys=True))
