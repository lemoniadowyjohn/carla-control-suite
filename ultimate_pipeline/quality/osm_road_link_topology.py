"""Advisory OSM-to-OpenDRIVE road-boundary topology cross-check.

This module answers a deliberately narrow question: when a high-confidence
OSM-way/XODR-road correspondence exists at both sides of an OSM way endpoint,
does the generated road's declared predecessor/successor reach the expected
XODR neighbour?  It never modifies OpenDRIVE, OSM, or lane topology.

The conversion chain may split an OSM intersection into junction connector
roads.  A junction link is therefore resolved through the incoming junction
connection and one connector-to-road hop before it is compared with the OSM
neighbour.  This is bounded deliberately; broad graph reachability would make
almost every road in a city appear to agree.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.osm_meta_index import (
    project_positioned_osm_metadata_ways,
)
from ultimate_pipeline.enrichment.osm_xodr_correspondence import (
    build_metadata_associations,
)


_ELIGIBLE_MATCH_CLASSES = frozenset({"EXACT", "HIGH"})
_ENDPOINTS = ("start", "end")


def _id_key(value: str) -> tuple[int, int | str]:
    try:
        return 0, int(value)
    except (TypeError, ValueError):
        return 1, value


def extract_osm_highway_ways(osm_path: str | Path) -> list[dict[str, Any]]:
    """Return geometry-bearing OSM ``highway=*`` ways with endpoint node IDs.

    The correspondence engine needs projected geometry while the topology
    cross-check additionally needs the original first/last ``nd`` references.
    Both are retained in one deterministic record.  Ways without two resolvable
    nodes are excluded rather than guessed.
    """

    try:
        osm_root = ET.parse(osm_path).getroot()
    except (FileNotFoundError, ET.ParseError):
        return []

    node_coordinates: dict[str, tuple[float, float]] = {}
    for node in osm_root.findall("node"):
        node_id = node.get("id")
        try:
            longitude = float(node.get("lon", ""))
            latitude = float(node.get("lat", ""))
        except (TypeError, ValueError):
            continue
        if node_id:
            node_coordinates[str(node_id)] = (longitude, latitude)

    ways: list[dict[str, Any]] = []
    for way in osm_root.findall("way"):
        way_id = way.get("id")
        if not way_id:
            continue
        tags = {
            str(tag.get("k", "")): str(tag.get("v", ""))
            for tag in way.findall("tag")
        }
        if not tags.get("highway"):
            continue
        node_refs = [str(nd.get("ref")) for nd in way.findall("nd") if nd.get("ref")]
        points = [node_coordinates[ref] for ref in node_refs if ref in node_coordinates]
        if len(node_refs) < 2 or len(points) < 2:
            continue
        ways.append(
            {
                "id": str(way_id),
                "name": tags.get("name", ""),
                "highway": tags["highway"],
                "geometry": points,
                "node_refs": node_refs,
                # The matcher accepts metadata-free ways.  The topology audit
                # uses its correspondence and orientation, not tag enrichment.
                "metadata": {},
            }
        )
    return sorted(ways, key=lambda way: _id_key(str(way["id"])))


def build_osm_way_adjacency(
    osm_ways: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build endpoint-only OSM way adjacency without inferring interior joins."""

    endpoint_members: dict[str, list[tuple[str, str]]] = defaultdict(list)
    endpoint_by_way: dict[str, dict[str, str]] = {}
    for way in sorted(osm_ways, key=lambda item: _id_key(str(item.get("id", "")))):
        way_id = str(way.get("id", ""))
        refs = [str(ref) for ref in way.get("node_refs", ()) if ref]
        if not way_id or len(refs) < 2:
            continue
        endpoints = {"start": refs[0], "end": refs[-1]}
        endpoint_by_way[way_id] = endpoints
        for role, node_id in endpoints.items():
            endpoint_members[node_id].append((way_id, role))

    adjacent_by_way_end: dict[tuple[str, str], tuple[str, ...]] = {}
    adjacent_by_way: dict[str, set[str]] = defaultdict(set)
    undirected_edges: set[tuple[str, str]] = set()
    for node_id in sorted(endpoint_members, key=_id_key):
        members = sorted(endpoint_members[node_id], key=lambda item: (_id_key(item[0]), item[1]))
        for way_id, role in members:
            neighbours = sorted(
                {other_way_id for other_way_id, _ in members if other_way_id != way_id},
                key=_id_key,
            )
            adjacent_by_way_end[(way_id, role)] = tuple(neighbours)
            adjacent_by_way[way_id].update(neighbours)
            for other_way_id in neighbours:
                undirected_edges.add(tuple(sorted((way_id, other_way_id), key=_id_key)))

    degree_distribution = Counter(len(adjacent_by_way[way_id]) for way_id in endpoint_by_way)
    return {
        "endpoint_by_way": endpoint_by_way,
        "adjacent_by_way_end": adjacent_by_way_end,
        "adjacent_by_way": {
            way_id: tuple(sorted(neighbours, key=_id_key))
            for way_id, neighbours in sorted(adjacent_by_way.items(), key=lambda item: _id_key(item[0]))
        },
        "summary": {
            "way_count": len(endpoint_by_way),
            "endpoint_count": len(endpoint_by_way) * 2,
            "endpoint_node_count": len(endpoint_members),
            "adjacency_edge_count": len(undirected_edges),
            "degree_distribution": {
                str(degree): count for degree, count in sorted(degree_distribution.items())
            },
        },
    }


def _roads_by_id(root: ET.Element) -> dict[str, ET.Element]:
    return {
        str(road.get("id")): road
        for road in root.findall("./road")
        if road.get("id")
    }


def _road_link(road: ET.Element, role: str) -> ET.Element | None:
    return road.find(f"./link/{role}")


def _direct_road_link_targets(road: ET.Element) -> set[str]:
    targets: set[str] = set()
    for role in ("predecessor", "successor"):
        link = _road_link(road, role)
        if link is not None and link.get("elementType") == "road" and link.get("elementId"):
            targets.add(str(link.get("elementId")))
    return targets


def _junction_reachable_targets(
    road: ET.Element,
    road_id: str,
    endpoint_role: str,
    junctions: Mapping[str, ET.Element],
    roads: Mapping[str, ET.Element],
) -> tuple[set[str], str, str | None]:
    """As ``_reachable_at_road_end`` plus connector-to-road resolution."""

    link_role = "predecessor" if endpoint_role == "start" else "successor"
    link = _road_link(road, link_role)
    if link is None:
        return set(), "NO_DECLARED_LINK", "missing_predecessor_or_successor"
    element_type = str(link.get("elementType", ""))
    element_id = str(link.get("elementId", ""))
    if element_type == "road" and element_id:
        return {element_id}, "DIRECT_ROAD", None
    if element_type != "junction" or not element_id:
        return set(), "UNRESOLVED_LINK", "unsupported_or_missing_link_target"
    junction = junctions.get(element_id)
    if junction is None:
        return set(), "UNRESOLVED_JUNCTION", "referenced_junction_missing"

    connector_ids = sorted(
        {
            str(connection.get("connectingRoad"))
            for connection in junction.findall("./connection")
            if str(connection.get("incomingRoad", "")) == road_id
            and connection.get("connectingRoad")
        },
        key=_id_key,
    )
    if not connector_ids:
        return set(), "UNRESOLVED_JUNCTION", "no_connection_for_incoming_road"

    reached: set[str] = set(connector_ids)
    for connector_id in connector_ids:
        connector = roads.get(connector_id)
        if connector is not None:
            reached.update(_direct_road_link_targets(connector))
    return reached, "JUNCTION_CONNECTOR", None


def _associated_roads_by_osm_way(
    associations: Mapping[str, Mapping[str, Any]],
) -> dict[str, tuple[str, ...]]:
    by_way: dict[str, list[str]] = defaultdict(list)
    for road_id, association in associations.items():
        match_class = str(association.get("class", association.get("match_class", ""))).upper()
        way_id = str(association.get("osm_way_id", ""))
        if match_class in _ELIGIBLE_MATCH_CLASSES and way_id:
            by_way[way_id].append(str(road_id))
    return {
        way_id: tuple(sorted(set(road_ids), key=_id_key))
        for way_id, road_ids in sorted(by_way.items(), key=lambda item: _id_key(item[0]))
    }


def audit_osm_road_link_topology(
    root: ET.Element,
    osm_ways: Iterable[Mapping[str, Any]],
    *,
    associations: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Cross-check one XODR root against projected OSM highway way records.

    If ``associations`` is omitted, the canonical spatial correspondence engine
    is invoked.  Passing associations is useful for deterministic unit tests
    and callers which already computed correspondence in the same stage.
    """

    ways = sorted((dict(way) for way in osm_ways), key=lambda way: _id_key(str(way.get("id", ""))))
    adjacency = build_osm_way_adjacency(ways)
    if associations is None:
        associations, correspondence_report = build_metadata_associations(ways, root)
    else:
        associations = {str(road_id): dict(value) for road_id, value in associations.items()}
        correspondence_report = {
            "source": "caller_supplied",
            "eligible_road_count": len(associations),
        }

    roads = _roads_by_id(root)
    junctions = {
        str(junction.get("id")): junction
        for junction in root.findall("./junction")
        if junction.get("id")
    }
    by_way = _associated_roads_by_osm_way(associations)
    summary = Counter()
    records: list[dict[str, Any]] = []

    for road_id in sorted(associations, key=_id_key):
        association = associations[road_id]
        match_class = str(association.get("class", association.get("match_class", ""))).upper()
        osm_way_id = str(association.get("osm_way_id", ""))
        direction = str(association.get("osm_direction", "")).lower()
        road = roads.get(road_id)
        if road is None or match_class not in _ELIGIBLE_MATCH_CLASSES:
            continue
        summary["eligible_associated_roads"] += 1
        if direction not in {"forward", "reverse"}:
            summary["unoriented_associated_roads"] += 1
            continue
        if osm_way_id not in adjacency["endpoint_by_way"]:
            summary["associated_way_missing_endpoint_data"] += 1
            continue
        summary["oriented_associated_roads"] += 1
        for osm_endpoint in _ENDPOINTS:
            endpoint_role = (
                osm_endpoint
                if direction == "forward"
                else ("end" if osm_endpoint == "start" else "start")
            )
            neighbour_way_ids = adjacency["adjacent_by_way_end"].get((osm_way_id, osm_endpoint), ())
            expected_road_ids = sorted(
                {
                    target_road_id
                    for neighbour_way_id in neighbour_way_ids
                    for target_road_id in by_way.get(neighbour_way_id, ())
                    if target_road_id != road_id
                },
                key=_id_key,
            )
            base_record = {
                "xodr_road_id": road_id,
                "osm_way_id": osm_way_id,
                "osm_direction": direction,
                "osm_endpoint": osm_endpoint,
                "xodr_endpoint": endpoint_role,
                "adjacent_osm_way_ids": list(neighbour_way_ids),
                "expected_xodr_road_ids": expected_road_ids,
            }
            if not neighbour_way_ids:
                summary["no_osm_endpoint_adjacency"] += 1
                records.append({**base_record, "classification": "NOT_APPLICABLE", "reason": "no_osm_highway_neighbour"})
                continue
            if not expected_road_ids:
                summary["incomplete_unassociated_osm_neighbours"] += 1
                records.append({**base_record, "classification": "INCOMPLETE", "reason": "no_high_confidence_xodr_match_for_osm_neighbour"})
                continue
            reached, resolution, reason = _junction_reachable_targets(
                road, road_id, endpoint_role, junctions, roads
            )
            base_record["declared_reachable_xodr_road_ids"] = sorted(reached, key=_id_key)
            base_record["resolution"] = resolution
            if reason:
                summary["incomplete_unresolved_declared_link"] += 1
                records.append({**base_record, "classification": "INCOMPLETE", "reason": reason})
            elif set(expected_road_ids).intersection(reached):
                summary["agree"] += 1
                records.append({**base_record, "classification": "AGREE"})
            else:
                summary["disagree"] += 1
                records.append({**base_record, "classification": "DISAGREE", "reason": "declared_link_does_not_reach_matched_osm_neighbour"})

    checkable = summary["agree"] + summary["disagree"]
    if checkable == 0:
        status = "INCOMPLETE"
    elif summary["disagree"]:
        status = "FAIL"
    elif summary["incomplete_unassociated_osm_neighbours"] or summary["incomplete_unresolved_declared_link"]:
        status = "INCOMPLETE"
    else:
        status = "PASS"
    return {
        "status": status,
        "summary_metrics": {
            **adjacency["summary"],
            "total_xodr_roads": len(roads),
            "total_junctions": len(junctions),
            "high_confidence_associated_roads": summary["eligible_associated_roads"],
            "oriented_associated_roads": summary["oriented_associated_roads"],
            "unoriented_associated_roads": summary["unoriented_associated_roads"],
            "associated_way_missing_endpoint_data": summary["associated_way_missing_endpoint_data"],
            "checkable_boundaries": checkable,
            "agree": summary["agree"],
            "disagree": summary["disagree"],
            "incomplete_unassociated_osm_neighbours": summary["incomplete_unassociated_osm_neighbours"],
            "incomplete_unresolved_declared_link": summary["incomplete_unresolved_declared_link"],
            "no_osm_endpoint_adjacency": summary["no_osm_endpoint_adjacency"],
        },
        "correspondence": correspondence_report,
        "boundaries": records,
        "claim_boundary": (
            "Advisory topology cross-check only. HIGH/EXACT spatial correspondence is required; "
            "an INCOMPLETE or DISAGREE record neither repairs nor certifies any OpenDRIVE link. "
            "Junction resolution is limited to the declared incoming connection and one connector-to-road hop."
        ),
    }


def run_osm_road_link_topology_audit(
    xodr_path: str | Path,
    osm_path: str | Path,
) -> dict[str, Any]:
    """Load and audit one immutable OSM/XODR pair without writing either input."""

    root = ET.parse(xodr_path).getroot()
    source_ways = extract_osm_highway_ways(osm_path)
    projected_ways = project_positioned_osm_metadata_ways(source_ways, root)
    report = audit_osm_road_link_topology(root, projected_ways)
    report["input"] = {
        "xodr_path": str(xodr_path),
        "osm_path": str(osm_path),
        "source_highway_way_count": len(source_ways),
        "projected_highway_way_count": len(projected_ways),
    }
    return report
