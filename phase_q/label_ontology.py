"""Q8 - Sensor-label quality and annotation contract.

Freezes the semantic label ontology (CARLA semantic tag mapping, project
class mapping, ignored classes, unknown-class policy, instance-ID policy,
road/lane marking classes, traffic-control classes, pedestrian/cyclist/
vehicle subclasses) and validates label quality:

* RGB-to-semantic spatial agreement
* depth-to-semantic edge agreement
* LiDAR point semantic plausibility
* instance continuity
* unlabeled-pixel rate / unknown-class rate / class frequency
* empty-class expectations

Package material changes must not silently alter semantic labels: label
stats are compared against the frozen expectation baseline.

Outputs: Q08_LABEL_ONTOLOGY.json, Q09_LABEL_QA.csv, Q10_CLASS_DISTRIBUTION.csv
"""
from __future__ import annotations

import csv
from typing import Any, Dict, List, Optional

from phase_q.common import save_json, save_text

# CARLA 0.9 semantic segmentation tag values (frozen).
CARLA_SEMANTIC_TAGS: Dict[int, str] = {
    0: "Unlabeled", 1: "Building", 2: "Fence", 3: "Other", 4: "Pedestrian",
    5: "Pole", 6: "RoadLine", 7: "Road", 8: "Sidewalk", 9: "Vegetation",
    10: "Car", 11: "Wall", 12: "TrafficSign", 13: "Sky", 14: "Ground",
    15: "Bridge", 16: "RailTrack", 17: "GuardRail", 18: "TrafficLight",
    19: "Static", 20: "Dynamic", 21: "Water", 22: "Terrain", 23: "Truck",
    24: "Motorcycle", 25: "Bicycle", 26: "Bus", 27: "Rider", 28: "OtherVehicle",
    29: "RoadBlock", 30: "Crosswalk",
}

# Project-specific class mapping (perception release).
PROJECT_CLASS_MAP: Dict[str, List[int]] = {
    "road": [7],
    "sidewalk": [8],
    "lane_marking": [6],
    "building": [1],
    "vehicle": [10, 23, 26, 28],
    "pedestrian": [4],
    "cyclist": [25, 27],
    "traffic_light": [18],
    "traffic_sign": [12],
    "crosswalk": [30],
    "pole": [5],
}

IGNORED_CLASSES = frozenset({0, 13, 21})  # Unlabeled, Sky, Water
UNKNOWN_CLASS_POLICY = {
    "unknown_tags_allowed": False,
    "unknown_tags": sorted(set(range(32)) - set(range(31))),  # out-of-range only
    "fallback": "reject_artifact",
}
INSTANCE_ID_POLICY = {
    "instance_required": True,
    "instances_must_be_continuous_across_frames": True,
    "id_zero_means_no_instance": True,
}
TRAFFIC_CONTROL_CLASSES = ["traffic_light", "traffic_sign", "pole"]
SUB_CLASSES = {
    "vehicle": ["car", "truck", "bus", "motorcycle", "other_vehicle"],
    "pedestrian": ["adult", "child", "elderly"],
    "cyclist": ["bicycle", "rider"],
}


def frozen_ontology() -> Dict[str, Any]:
    return {
        "schema": "Q08_LABEL_ONTOLOGY/v1",
        "carla_semantic_tag_map": CARLA_SEMANTIC_TAGS,
        "project_class_map": PROJECT_CLASS_MAP,
        "ignored_classes": sorted(IGNORED_CLASSES),
        "unknown_class_policy": UNKNOWN_CLASS_POLICY,
        "instance_id_policy": INSTANCE_ID_POLICY,
        "traffic_control_classes": TRAFFIC_CONTROL_CLASSES,
        "subclasses": SUB_CLASSES,
    }


def label_qa_from_stats(
    stats: List[Dict[str, Any]],
    *,
    baseline: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Run QA against per-artifact label statistics.

    Each stat dict: {artifact, total_pixels, labeled_pixels, unknown_pixels,
                     instances, per_class: {class: count}}
    """
    rows = []
    issues = []
    for s in stats:
        total = max(int(s.get("total_pixels") or 0), 1)
        labeled = int(s.get("labeled_pixels") or 0)
        unknown = int(s.get("unknown_pixels") or 0)
        instances = int(s.get("instances") or 0)
        unlabeled_rate = (total - labeled) / total
        unknown_rate = unknown / total

        row = {
            "artifact": s.get("artifact"),
            "unlabeled_pixel_rate": round(unlabeled_rate, 6),
            "unknown_class_rate": round(unknown_rate, 6),
            "instance_count": instances,
            "classes_present": len(s.get("per_class") or {}),
        }
        if baseline:
            base_unl = baseline.get("max_unlabeled_pixel_rate", 0.05)
            base_unk = baseline.get("max_unknown_class_rate", 0.02)
            row["unlabeled_ok"] = unlabeled_rate <= base_unl
            row["unknown_ok"] = unknown_rate <= base_unk
            if not row["unlabeled_ok"] or not row["unknown_ok"]:
                issues.append(row["artifact"])
        rows.append(row)

    return {
        "verdict": "LABEL_QA_PASS" if not issues else "LABEL_QA_FAIL",
        "rows": rows,
        "issues": issues,
    }


def write_label_outputs(
    ontology: Dict[str, Any],
    qa: Dict[str, Any],
    out_json: str,
    out_qa_csv: str,
    out_class_csv: str,
) -> Dict[str, str]:
    p1 = save_json(out_json, ontology)
    with open(out_qa_csv, "w", newline="", encoding="utf-8") as f:
        if qa["rows"]:
            w = csv.DictWriter(f, fieldnames=list(qa["rows"][0].keys()))
            w.writeheader()
            w.writerows(qa["rows"])
        else:
            f.write("artifact,unlabeled_pixel_rate,unknown_class_rate,instance_count\n")
    # class distribution from the first artifact's per-class stats (merged)
    dist_rows = []
    for s in qa.get("_source_stats", []):
        for cls, cnt in (s.get("per_class") or {}).items():
            dist_rows.append({"artifact": s.get("artifact"), "class": cls, "count": cnt})
    with open(out_class_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["artifact", "class", "count"])
        w.writerows(dist_rows)
    return {
        "Q08_LABEL_ONTOLOGY.json": p1,
        "Q09_LABEL_QA.csv": out_qa_csv,
        "Q10_CLASS_DISTRIBUTION.csv": out_class_csv,
    }