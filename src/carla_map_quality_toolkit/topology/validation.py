from __future__ import annotations

from dataclasses import dataclass

from carla_map_quality_toolkit.io.opendrive import OpenDriveMap, Road, RoadLink


@dataclass(frozen=True)
class TopologyIssue:
    code: str
    message: str
    road_id: str | None = None
    junction_id: str | None = None


def _road_target_exists(map_data: OpenDriveMap, link: RoadLink | None) -> bool:
    if link is None:
        return True
    if link.element_type == "road":
        return link.element_id in map_data.roads
    if link.element_type == "junction":
        return link.element_id in map_data.junctions
    return False


def _endpoint_link(road: Road, contact_point: str | None) -> RoadLink | None:
    if contact_point == "start":
        return road.predecessor
    if contact_point == "end":
        return road.successor
    return None


def _check_reciprocal_road_link(
    map_data: OpenDriveMap,
    source: Road,
    relation: str,
    link: RoadLink,
) -> TopologyIssue | None:
    if link.element_type != "road" or link.element_id not in map_data.roads:
        return None
    target = map_data.roads[link.element_id]
    reciprocal = _endpoint_link(target, link.contact_point)
    if reciprocal is None:
        return TopologyIssue(
            code="MISSING_RECIPROCAL_ROAD_LINK",
            message=(
                f"Road {source.road_id} {relation} connects to road {target.road_id} "
                f"at {link.contact_point!r}, but the target endpoint has no reciprocal link"
            ),
            road_id=source.road_id,
        )
    if reciprocal.element_type != "road" or reciprocal.element_id != source.road_id:
        return TopologyIssue(
            code="MISMATCHED_RECIPROCAL_ROAD_LINK",
            message=(
                f"Road {source.road_id} {relation} points to road {target.road_id}, "
                f"but target endpoint points to {reciprocal.element_type}:{reciprocal.element_id}"
            ),
            road_id=source.road_id,
        )
    return None


def validate_topology(map_data: OpenDriveMap) -> list[TopologyIssue]:
    """Validate road references, reciprocal road links and junction lane links."""
    issues: list[TopologyIssue] = []

    for road in map_data.roads.values():
        for relation, link in (("predecessor", road.predecessor), ("successor", road.successor)):
            if not _road_target_exists(map_data, link):
                issues.append(
                    TopologyIssue(
                        code="MISSING_ROAD_LINK_TARGET",
                        message=f"Road {road.road_id} {relation} points to missing {link}",
                        road_id=road.road_id,
                    )
                )
                continue
            if link is not None:
                reciprocal_issue = _check_reciprocal_road_link(map_data, road, relation, link)
                if reciprocal_issue is not None:
                    issues.append(reciprocal_issue)

    for junction in map_data.junctions.values():
        for connection in junction.connections:
            incoming = map_data.roads.get(connection.incoming_road)
            connecting = map_data.roads.get(connection.connecting_road)
            if incoming is None:
                issues.append(
                    TopologyIssue(
                        code="MISSING_INCOMING_ROAD",
                        message=(
                            f"Connection {connection.connection_id} references "
                            "missing incoming road"
                        ),
                        junction_id=junction.junction_id,
                    )
                )
            if connecting is None:
                issues.append(
                    TopologyIssue(
                        code="MISSING_CONNECTING_ROAD",
                        message=(
                            f"Connection {connection.connection_id} references "
                            "missing connecting road"
                        ),
                        junction_id=junction.junction_id,
                    )
                )
            if incoming is None or connecting is None:
                continue
            for lane_link in connection.lane_links:
                if lane_link.from_lane not in incoming.lane_ids:
                    issues.append(
                        TopologyIssue(
                            code="INVALID_FROM_LANE",
                            message=(
                                f"Junction {junction.junction_id} laneLink "
                                f"from={lane_link.from_lane} "
                                f"does not exist on incoming road {incoming.road_id}"
                            ),
                            junction_id=junction.junction_id,
                        )
                    )
                if lane_link.to_lane not in connecting.lane_ids:
                    issues.append(
                        TopologyIssue(
                            code="INVALID_TO_LANE",
                            message=(
                                f"Junction {junction.junction_id} laneLink to={lane_link.to_lane} "
                                f"does not exist on connecting road {connecting.road_id}"
                            ),
                            junction_id=junction.junction_id,
                        )
                    )
    return issues
