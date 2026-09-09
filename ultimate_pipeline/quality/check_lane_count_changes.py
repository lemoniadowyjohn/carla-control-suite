"""Advisory detection of driving-lane count changes across road links."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


def _float(value: str | None) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _edge_lanes(road: ET.Element, at_start: bool) -> list[ET.Element]:
    sections = sorted(
        road.findall("./lanes/laneSection"), key=lambda section: _float(section.get("s"))
    )
    if not sections:
        return []
    return [
        lane
        for lane in (sections[0] if at_start else sections[-1]).findall(".//lane")
        if lane.get("type") == "driving"
    ]


def _lane_count_sources(lanes: list[ET.Element]) -> list[str]:
    sources: set[str] = set()
    for lane in lanes:
        for vector in lane.findall("./userData/vector"):
            if vector.get("key") == "lane_count_source" and vector.get("value"):
                sources.add(str(vector.get("value")))
    return sorted(sources)


def _edge_record(road: ET.Element, at_start: bool) -> dict[str, Any]:
    lanes = _edge_lanes(road, at_start)
    return {
        "road_id": str(road.get("id", "")),
        "contact_point": "start" if at_start else "end",
        "driving_lane_count": len(lanes),
        "lane_count_sources": _lane_count_sources(lanes),
    }


def _osm_provenance(record: dict[str, Any]) -> bool:
    sources = record["lane_count_sources"]
    return bool(sources) and all(source.startswith("osm:") for source in sources)


def _boundary_key(left: dict[str, Any], right: dict[str, Any]) -> tuple[tuple[str, str], tuple[str, str]]:
    return tuple(
        sorted(
            (
                (left["road_id"], left["contact_point"]),
                (right["road_id"], right["contact_point"]),
            )
        )
    )


def check_lane_count_changes(xodr_path: str | Path) -> dict[str, Any]:
    """Inspect linked road endpoints without changing the input map.

    A changed count is OSM-explained only if each linked endpoint has explicit
    lane-count provenance from OSM. Existing XODR lanes and fallback-generated
    lanes remain visible as unexplained rather than being assumed correct.
    """

    root = ET.parse(xodr_path).getroot()
    roads = {
        str(road.get("id")): road
        for road in root.findall("./road")
        if road.get("id")
    }
    seen: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    findings: list[dict[str, Any]] = []
    unresolved_links: list[dict[str, str]] = []

    for road_id, road in sorted(roads.items()):
        for link_name, source_at_start in (("predecessor", True), ("successor", False)):
            link = road.find(f"./link/{link_name}")
            if link is None or link.get("elementType") != "road":
                continue
            target_id = str(link.get("elementId", ""))
            target = roads.get(target_id)
            if target is None:
                unresolved_links.append(
                    {
                        "road_id": road_id,
                        "link": link_name,
                        "target_road_id": target_id,
                    }
                )
                continue
            target_at_start = link.get("contactPoint", "start") != "end"
            source_record = _edge_record(road, source_at_start)
            target_record = _edge_record(target, target_at_start)
            key = _boundary_key(source_record, target_record)
            if key in seen:
                continue
            seen.add(key)

            before = source_record["driving_lane_count"]
            after = target_record["driving_lane_count"]
            if before == after:
                category = "NO_CHANGE"
            elif _osm_provenance(source_record) and _osm_provenance(target_record):
                category = "OSM_EXPLAINED_CHANGE"
            else:
                category = "UNEXPLAINED_CHANGE"
            findings.append(
                {
                    "category": category,
                    "source": source_record,
                    "target": target_record,
                }
            )

    findings.sort(
        key=lambda item: (
            item["source"]["road_id"],
            item["source"]["contact_point"],
            item["target"]["road_id"],
            item["target"]["contact_point"],
        )
    )
    categories = Counter(item["category"] for item in findings)
    return {
        "ok": True,
        "advisory": True,
        "input": str(xodr_path),
        "summary_metrics": {
            "road_link_boundaries": len(findings),
            "no_change": categories["NO_CHANGE"],
            "osm_explained_change": categories["OSM_EXPLAINED_CHANGE"],
            "unexplained_change": categories["UNEXPLAINED_CHANGE"],
            "unresolved_road_links": len(unresolved_links),
        },
        "findings": findings,
        "unresolved_road_links": unresolved_links,
        "claim_boundary": (
            "Advisory only. This checker does not repair lane links or infer "
            "that an unproven count change is a generation defect."
        ),
    }
