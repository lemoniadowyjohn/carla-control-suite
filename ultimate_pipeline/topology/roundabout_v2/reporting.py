from __future__ import annotations

import xml.etree.ElementTree as ET

def lane_provenance_report(roads: list[ET.Element], *, fallback: str = "explicit_fallback") -> dict:
    """Return deterministic road/lane provenance for generated or source lanes."""
    result=[]
    for road in sorted(roads, key=lambda item: item.get("id", "")):
        lanes=[]
        for lane in road.findall("./lanes/laneSection/*/lane"):
            if lane.get("type") != "driving":
                continue
            lane_id=int(lane.get("id", "0"))
            lanes.append({"lane_id":lane_id, "source":"existing_xodr", "confidence":1.0})
        if not lanes:
            lanes=[{"lane_id":-1, "source":fallback, "confidence":0.0}]
        result.append({"road_id":road.get("id"), "lanes":sorted(lanes, key=lambda item:(abs(item["lane_id"]), item["lane_id"]))})
    return {"schema_version":1, "roads":result}
