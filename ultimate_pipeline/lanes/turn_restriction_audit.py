"""Advisory validation of OSM turn lanes against existing junction lane links.

This module deliberately does not create, remove, or reroute laneLink
elements. Position-specific OSM turn metadata is only consumed when a caller
supplies a road-resolved, high-confidence correspondence with the OSM way
orientation relative to the OpenDRIVE reference line.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping
import xml.etree.ElementTree as ET

from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint, pose_at_s


_DIRECT_MATCH_CLASSES = frozenset({"EXACT", "HIGH"})
_TURN_ALIASES = {
    "left": "left",
    "slight_left": "left",
    "merge_to_left": "left",
    "right": "right",
    "slight_right": "right",
    "merge_to_right": "right",
    "through": "through",
    "straight": "through",
    "reverse": "uturn",
    "uturn": "uturn",
}


@dataclass(frozen=True)
class TurnMetadataAssociation:
    """Road-resolved OSM turn metadata accepted by the audit.

    osm_direction is "forward" when the OSM way direction follows increasing
    XODR s and "reverse" otherwise. Without it, directional OSM tags cannot
    be assigned to an XODR lane direction safely.
    """

    match_class: str
    osm_way_id: str
    osm_direction: str
    metadata: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TurnMetadataAssociation | None":
        metadata = value.get("metadata")
        match_class = str(value.get("class", value.get("match_class", ""))).upper()
        direction = str(
            value.get("osm_direction", value.get("xodr_direction", ""))
        ).lower()
        if not isinstance(metadata, Mapping):
            return None
        if match_class not in _DIRECT_MATCH_CLASSES or direction not in {"forward", "reverse"}:
            return None
        return cls(
            match_class=match_class,
            osm_way_id=str(value.get("osm_way_id", "")),
            osm_direction=direction,
            metadata=metadata,
        )


def _normalise_angle(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi


def _edge_heading(road: ET.Element, at_start: bool) -> float | None:
    geometries = sorted(
        road.findall("./planView/geometry"),
        key=lambda geometry: float(geometry.get("s", 0.0)),
    )
    if not geometries:
        return None
    try:
        pose = pose_at_s(geometries[0], 0.0) if at_start else endpoint(geometries[-1])
        return float(pose.heading)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _connector_turn_category(
    connection: ET.Element, incoming: ET.Element, connecting: ET.Element
) -> tuple[str | None, float | None]:
    """Classify travel through a connector from the incoming-road attachment."""

    incoming_heading = _edge_heading(incoming, at_start=False)
    contact_point = connection.get("contactPoint", "start")
    if contact_point == "start":
        departure_heading = _edge_heading(connecting, at_start=False)
    elif contact_point == "end":
        heading = _edge_heading(connecting, at_start=True)
        departure_heading = None if heading is None else heading + math.pi
    else:
        return None, None
    if incoming_heading is None or departure_heading is None:
        return None, None
    delta = _normalise_angle(departure_heading - incoming_heading)
    degrees = math.degrees(delta)
    absolute = abs(degrees)
    if absolute <= 35.0:
        return "through", degrees
    if absolute >= 145.0:
        return "uturn", degrees
    return ("left" if degrees > 0.0 else "right"), degrees


def _lane_ids_at_incoming_end(road: ET.Element, lane_id: int) -> list[int]:
    sections = sorted(
        road.findall("./lanes/laneSection"),
        key=lambda section: float(section.get("s", 0.0)),
    )
    if not sections:
        return []
    side = "right" if lane_id < 0 else "left"
    lane_ids: list[int] = []
    for lane in sections[-1].findall(f"./{side}/lane"):
        if lane.get("type", "driving") != "driving":
            continue
        try:
            candidate = int(lane.get("id", "0"))
        except ValueError:
            continue
        if candidate and (candidate < 0) == (lane_id < 0):
            lane_ids.append(candidate)
    # OSM describes lanes left-to-right in the direction of travel. Negative
    # lanes travel with XODR s; positive lanes travel against it.
    return sorted(lane_ids, key=abs, reverse=lane_id > 0)


def _turn_tokens(pattern: str) -> list[frozenset[str]]:
    result: list[frozenset[str]] = []
    for lane_spec in pattern.split("|"):
        tokens = {
            _TURN_ALIASES[token.strip().lower()]
            for token in lane_spec.split(";")
            if token.strip().lower() in _TURN_ALIASES
        }
        result.append(frozenset(tokens))
    return result


def _pattern_for_lane(
    association: TurnMetadataAssociation,
    lane_id: int,
    lane_ids: list[int],
) -> tuple[frozenset[str] | None, str, str | None]:
    """Return expected movements, provenance, and an incomplete reason."""

    xodr_direction = "forward" if lane_id < 0 else "backward"
    osm_direction = (
        xodr_direction
        if association.osm_direction == "forward"
        else ("backward" if xodr_direction == "forward" else "forward")
    )
    directional_key = f"turn:lanes:{osm_direction}"
    pattern = association.metadata.get(directional_key)
    source = directional_key
    if not pattern:
        pattern = association.metadata.get("turn_lanes") or association.metadata.get("turn:lanes")
        source = "turn:lanes"
    if not isinstance(pattern, str) or not pattern.strip():
        return None, source, "missing_turn_pattern"
    tokens = _turn_tokens(pattern)
    if len(tokens) != len(lane_ids):
        return None, source, "lane_pattern_count_mismatch"
    try:
        index = lane_ids.index(lane_id)
    except ValueError:
        return None, source, "lane_not_at_incoming_end"
    if not tokens[index]:
        return None, source, "unsupported_turn_token"
    return tokens[index], source, None


def _as_association(value: Any) -> TurnMetadataAssociation | None:
    return TurnMetadataAssociation.from_mapping(value) if isinstance(value, Mapping) else None


def audit_lane_link_turn_classification(
    root: ET.Element,
    correspondence_by_road_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return advisory OSM/geometry agreement for lane links in multi-exit junctions.

    correspondence_by_road_id must be populated by a spatial correspondence
    producer. Name-only metadata is intentionally rejected because it is unsafe
    for a position-specific junction approach.
    """

    roads = {
        str(road.get("id")): road
        for road in root.findall("./road")
        if road.get("id")
    }
    correspondence = correspondence_by_road_id or {}
    connection_groups: dict[tuple[str, str], list[tuple[str, ET.Element]]] = {}
    for junction in root.findall("./junction"):
        junction_id = str(junction.get("id", ""))
        for connection in junction.findall("./connection"):
            incoming_id = str(connection.get("incomingRoad", ""))
            connecting_id = str(connection.get("connectingRoad", ""))
            if incoming_id and connecting_id:
                connection_groups.setdefault((junction_id, incoming_id), []).append(
                    (connecting_id, connection)
                )

    records: list[dict[str, Any]] = []
    summary = {
        "multi_exit_connections": 0,
        "lane_links_checked": 0,
        "agree": 0,
        "disagree": 0,
        "no_osm_turn_data": 0,
        "incomplete": 0,
    }
    for (junction_id, incoming_id), connections in sorted(connection_groups.items()):
        if len({connecting_id for connecting_id, _ in connections}) < 2:
            continue
        incoming = roads.get(incoming_id)
        association = _as_association(correspondence.get(incoming_id))
        for connecting_id, connection in sorted(connections, key=lambda item: item[0]):
            summary["multi_exit_connections"] += 1
            connecting = roads.get(connecting_id)
            category, angle_deg = (
                _connector_turn_category(connection, incoming, connecting)
                if incoming is not None and connecting is not None
                else (None, None)
            )
            for lane_link in connection.findall("./laneLink"):
                summary["lane_links_checked"] += 1
                record = {
                    "junction_id": junction_id,
                    "connection_id": str(connection.get("id", "")),
                    "incoming_road_id": incoming_id,
                    "connecting_road_id": connecting_id,
                    "from_lane_id": lane_link.get("from"),
                    "to_lane_id": lane_link.get("to"),
                    "geometry_turn": category,
                    "geometry_turn_angle_deg": angle_deg,
                    "lane_link_turn_classification_agreement": "NO_OSM_DATA",
                }
                try:
                    lane_id = int(lane_link.get("from", ""))
                except (TypeError, ValueError):
                    lane_id = 0
                if association is None:
                    summary["no_osm_turn_data"] += 1
                    record["reason"] = "missing_high_confidence_oriented_correspondence"
                elif incoming is None or category is None or not lane_id:
                    summary["incomplete"] += 1
                    record["lane_link_turn_classification_agreement"] = "INCOMPLETE"
                    record["reason"] = "missing_lane_or_connector_geometry"
                else:
                    lane_ids = _lane_ids_at_incoming_end(incoming, lane_id)
                    expected, pattern_source, reason = _pattern_for_lane(
                        association, lane_id, lane_ids
                    )
                    record["osm_way_id"] = association.osm_way_id
                    record["osm_match_class"] = association.match_class
                    record["osm_pattern_source"] = pattern_source
                    record["osm_expected_turns"] = sorted(expected) if expected else []
                    if reason:
                        summary["incomplete"] += 1
                        record["lane_link_turn_classification_agreement"] = "INCOMPLETE"
                        record["reason"] = reason
                    elif category in expected:
                        summary["agree"] += 1
                        record["lane_link_turn_classification_agreement"] = "AGREE"
                    else:
                        summary["disagree"] += 1
                        record["lane_link_turn_classification_agreement"] = "DISAGREE"
                        record["reason"] = "osm_turn_category_conflicts_with_connector_geometry"
                records.append(record)

    if summary["disagree"]:
        status = "FAIL"
    elif summary["incomplete"] or summary["no_osm_turn_data"]:
        status = "INCOMPLETE"
    else:
        status = "PASS"
    return {
        "status": status,
        "summary_metrics": summary,
        "connections": records,
        "claim_boundary": (
            "Advisory validation only. No laneLink mutation occurs; name-only "
            "OSM metadata is not consumed for position-specific turn semantics."
        ),
    }
