from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from .core import RoundaboutModel, validate_lane_mapping
from .core import sample_road

def validate_model(model: RoundaboutModel) -> dict:
    failures=[]
    if model.candidate.detection_method in {"AMBIGUOUS","REJECTED"}: failures.append("ambiguous_detection")
    if not model.samples: failures.append("samples_missing")
    if model.circle_fit:
        required=("center_x","center_y","radius","rmse","max_residual")
        if not all(k in model.circle_fit and math.isfinite(float(model.circle_fit[k])) for k in required): failures.append("invalid_circle_fit")
        if float(model.circle_fit.get("radius",0)) <= 0: failures.append("non_positive_radius")
    if model.action.startswith("RECONSTRUCT") and not model.anchors: failures.append("anchors_missing")
    return {"status":"PASS" if not failures else "FAIL","failures":failures}

def validate_elevation_records(records: list[dict]) -> dict:
    failures=[]; previous=None
    for index,record in enumerate(records):
        try: s=float(record["s"]); values=[float(record[k]) for k in "abcd"]
        except (KeyError,TypeError,ValueError): failures.append(f"record_{index}_invalid"); continue
        if not math.isfinite(s) or not all(math.isfinite(x) for x in values): failures.append(f"record_{index}_nonfinite")
        if previous is not None and s <= previous: failures.append(f"record_{index}_nonmonotonic")
        previous=s
    return {"status":"PASS" if not failures else "FAIL","failures":failures}

def validate_segmented_ring(roads: list[ET.Element]) -> dict:
    """Validate the closed-road portion of a V2 candidate without CARLA."""
    failures=[]
    ids=[r.get("id") for r in roads]
    if len(ids) != len(set(ids)) or any(not x for x in ids): failures.append("road_ids_invalid")
    known=set(ids)
    for road in roads:
        try:
            declared=float(road.get("length","nan"))
            samples=sample_road(road, max(declared/32.0, .25))
            if not math.isfinite(declared) or declared <= 0: failures.append(f"{road.get('id')}:length_invalid")
            if not road.findall("./planView/geometry"): failures.append(f"{road.get('id')}:planview_missing")
            driving=[lane for lane in road.findall("./lanes/laneSection/*/lane") if lane.get("type")=="driving"]
            if not driving or any(int(lane.get("id","0")) == 0 for lane in driving): failures.append(f"{road.get('id')}:lanes_invalid")
            link=road.find("link")
            if link is None: failures.append(f"{road.get('id')}:links_missing")
            else:
                for tag in ("predecessor","successor"):
                    node=link.find(tag)
                    if node is None or node.get("elementType") != "road" or node.get("elementId") not in known:
                        failures.append(f"{road.get('id')}:{tag}_invalid")
            if abs(samples[-1].s - samples[0].s - declared) > 1e-6: failures.append(f"{road.get('id')}:s_not_monotonic")
        except (TypeError, ValueError, OverflowError):
            failures.append(f"{road.get('id')}:geometry_invalid")
    return {"status":"PASS" if not failures else "FAIL", "failures":failures}
