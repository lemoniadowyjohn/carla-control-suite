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

#: V104 review 4551845520: the oneway state is three-valued.  A
#: bidirectional way is NOT the same thing as a reverse one-way way.
ONEWAY_FORWARD = "forward"
ONEWAY_REVERSE = "reverse"
ONEWAY_BIDIRECTIONAL = "bidirectional"
ONEWAY_UNKNOWN = "unknown"
_ENDPOINTS = ("start", "end")


def _id_key(value: str) -> tuple[int, int | str]:
    try:
        return 0, int(value)
    except (TypeError, ValueError):
        return 1, value


#: Tags that decide whether two ways that share an OSM node are actually
#: traversable from one to the other.  V103-O3 (registry T09/T03): a shared
#: node is *necessary* evidence of adjacency, but it is not *sufficient* --
#: a bridge and the road it crosses share no node, and two ways meeting at a
#: grade-separated node are not connected for a vehicle.
_RESTRICTION_TAGS = (
    "oneway",
    "junction",
    "bridge",
    "tunnel",
    "layer",
    "access",
    # V104 review 4551845558: without the inherited ``vehicle`` tag the
    # access hierarchy cannot be evaluated.
    "vehicle",
    "motor_vehicle",
    "motorcar",
    "motor_vehicle:forward",
    "motor_vehicle:backward",
    "psv",
    "bus",
    "bicycle",
    "service",
    "hgv",
    "destination",
    "living_street",
)


def _extract_osm_highway_ways(osm_path: str | Path) -> list[dict[str, Any]]:
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
        way_metadata = {
            key: tags[key] for key in _RESTRICTION_TAGS if key in tags
        }
        ways.append(
            {
                "id": str(way_id),
                "name": tags.get("name", ""),
                "highway": tags["highway"],
                "geometry": points,
                "node_refs": node_refs,
                # The matcher accepts metadata-free ways.  The topology audit
                # uses its correspondence and orientation, not tag enrichment.
                "metadata": way_metadata,
                # Restriction facts are carried separately so the *tag
                # enrichment* index (street-name keyed) is never polluted with
                # them.
                "restrictions": way_metadata,
            }
        )
    return sorted(ways, key=lambda way: _id_key(str(way["id"])))


def extract_osm_highway_ways(osm_path: str | Path) -> list[dict[str, Any]]:
    """Public wrapper for :func:`_extract_osm_highway_ways`."""
    return _extract_osm_highway_ways(osm_path)


def _way_restrictions(way: Mapping[str, Any]) -> dict[str, str]:
    """Restriction tags for one way, from either ``restrictions`` or ``metadata``."""
    out: dict[str, str] = {}
    for source in ("restrictions", "metadata"):
        raw = way.get(source)
        if isinstance(raw, Mapping):
            for key, value in raw.items():
                text = str(value).strip().lower()
                if text:
                    out[str(key).strip().lower()] = text
    return out


def _way_is_oneway_forward(restrictions: Mapping[str, str]) -> bool | None:
    """Return True/False for oneway, or None when it cannot be decided.

    ``junction=roundabout`` implies a one-way along the way's node order
    (the OSM default).  ``oneway=reversible`` and ``oneway:conditional``
    are explicitly undecidable without a time context.
    """
    oneway = str(restrictions.get("oneway", "")).strip().lower()
    if oneway in {"yes", "true", "1"}:
        return ONEWAY_FORWARD
    if oneway in {"-1", "reverse"}:
        return ONEWAY_REVERSE
    if oneway in {"no", "false", "0"}:
        # V104 review 4551845520: a bidirectional way is NOT a reverse one-way
        # way.  Both used to return False, so a ``oneway=no`` way was treated
        # as reverse-only traffic and could not be entered at its start.
        return ONEWAY_BIDIRECTIONAL
    if oneway in {"reversible"}:
        return ONEWAY_UNKNOWN
    if oneway:
        return ONEWAY_UNKNOWN
    if str(restrictions.get("junction", "")).strip().lower() == "roundabout":
        return ONEWAY_FORWARD
    return ONEWAY_UNKNOWN


def _can_leave(oneway_state: str, role: str) -> bool:
    """May traffic leave this way at a node with the given role?

    * ``forward``  -- traffic runs start -> end, so it leaves at the end.
    * ``reverse``  -- traffic runs end -> start, so it leaves at the start.
    * bidirectional / unknown -- it may leave anywhere.
    """
    if oneway_state == ONEWAY_FORWARD:
        return role == "end"
    if oneway_state == ONEWAY_REVERSE:
        return role == "start"
    return True


def _can_enter(oneway_state: str, role: str) -> bool:
    """May traffic enter this way at a node with the given role?

    * ``forward``  -- traffic runs start -> end, so it enters at the start.
    * ``reverse``  -- traffic runs end -> start, so it enters at the end.
    * bidirectional / unknown -- it may be entered anywhere.
    """
    if oneway_state == ONEWAY_FORWARD:
        return role == "start"
    if oneway_state == ONEWAY_REVERSE:
        return role == "end"
    return True


def _way_layer(restrictions: Mapping[str, str]) -> tuple[int, bool, bool]:
    """``(layer, is_bridge, is_tunnel)`` for one way."""
    raw_layer = str(restrictions.get("layer", "")).strip()
    try:
        layer = int(raw_layer)
    except (TypeError, ValueError):
        layer = 0
    is_bridge = str(restrictions.get("bridge", "")).strip().lower() in {
        "yes",
        "true",
        "1",
        "viaduct",
    }
    is_tunnel = str(restrictions.get("tunnel", "")).strip().lower() in {
        "yes",
        "true",
        "1",
        "building_passage",
    }
    return layer, is_bridge, is_tunnel


def _vehicle_eligible(restrictions: Mapping[str, str], vehicle_class: str) -> bool | None:
    """Eligibility of one way for one vehicle class.

    Returns True/False, or None when the source does not decide (the way is
    then *eligible-unknown*, not *ineligible*).
    """
    key = {
        "motorcar": "motorcar",
        "motor_vehicle": "motor_vehicle",
        "bus": "psv",
        "psv": "psv",
        "bicycle": "bicycle",
        "hgv": "hgv",
        "service": "service",
    }.get(vehicle_class, vehicle_class)
    # V104 review 4551845558: the access hierarchy runs from the specific
    # vehicle class through ``vehicle`` to ``access``.  A way tagged
    # ``vehicle=no`` (with no class-specific override) forbids motor traffic
    # unless a more specific tag says otherwise.
    for tag in (key, "vehicle", "access"):
        raw = str(restrictions.get(tag, "")).strip().lower()
        if not raw:
            continue
        if raw in {"no", "private", "delivery", "destination", "customers"}:
            return False
        if raw in {"yes", "permissive", "designated", "official", "destination"}:
            return True
        if raw in {"destination"}:
            return True
    return None


def build_osm_source_adjacency(
    osm_ways: Iterable[Mapping[str, Any]],
    *,
    vehicle_class: str = "motor_vehicle",
) -> dict[str, Any]:
    """Build **source-grounded** OSM way adjacency over every shared node.

    ``build_osm_way_adjacency`` is deliberately endpoint-only: it answers
    "which ways meet at this way's *end* node?", which is the right question
    for an XODR road *endpoint* boundary check.  It cannot answer "which ways
    are traversable from one another along the source?", which is what the
    orphan-road repair and the road-graph audit need -- registry issues
    **T09** (endpoint-only adjacency misses interior-node cases) and **T03**
    (a geometry-only orphan repair lacks OSM node proof).

    This function answers that second question from the OSM source alone:

    * adjacency is established **only** by a shared ``nd`` reference.  Two
      ways that merely cross in XY, or that share a street *name*, are never
      connected -- no edge is ever fabricated from geometry.
    * the shared node's role in each way is recorded (``start`` / ``end`` /
      ``interior``), so a split way and its continuation are distinguishable
      from a genuine through-junction.
    * **existence** (the ways share a node) is kept separate from
      **eligibility** (a vehicle may legally traverse).  A way whose access
      tag forbids the vehicle class is still topologically adjacent; it is
      simply not eligible.
    * grade separation is honoured: a ``bridge=yes`` / ``tunnel=yes`` way and
      a way at a different ``layer`` are not traversable to each other.
    * oneway is respected for the *directed* adjacency.

    Anything the source cannot decide is reported as ``UNRESOLVED`` rather
    than guessed.
    """
    ways = sorted(
        (dict(way) for way in osm_ways),
        key=lambda way: _id_key(str(way.get("id", ""))),
    )

    node_members: dict[str, list[tuple[str, str]]] = defaultdict(list)
    node_role_by_way: dict[tuple[str, str], str] = {}
    restrictions_by_way: dict[str, dict[str, str]] = {}
    oneway_by_way: dict[str, str] = {}
    geometry_by_way: dict[str, list[tuple[float, float]]] = {}

    for way in ways:
        way_id = str(way.get("id", ""))
        refs = [str(ref) for ref in way.get("node_refs", ()) if ref]
        if not way_id or len(refs) < 2:
            continue
        restrictions = _way_restrictions(way)
        restrictions_by_way[way_id] = restrictions
        oneway_by_way[way_id] = _way_is_oneway_forward(restrictions)
        geometry_by_way[way_id] = [
            (float(x), float(y)) for x, y in (way.get("geometry") or [])
        ]
        last_index = len(refs) - 1
        for index, node_id in enumerate(refs):
            if index == 0:
                role = "start"
            elif index == last_index:
                role = "end"
            else:
                role = "interior"
            node_role_by_way[(way_id, node_id)] = role
            node_members[node_id].append((way_id, role))

    def _traversable(
        way_a: str,
        way_b: str,
        node_id: str,
        role_a: str,
        role_b: str,
    ) -> tuple[bool, str]:
        """Is there a traversable connection between two ways at a node?"""
        restr_a = restrictions_by_way.get(way_a, {})
        restr_b = restrictions_by_way.get(way_b, {})
        layer_a, bridge_a, tunnel_a = _way_layer(restr_a)
        layer_b, bridge_b, tunnel_b = _way_layer(restr_b)

        # V104 review 4551845530: a bridge or tunnel way meets its approach
        # road at a shared endpoint, and their layer / structure tags differ
        # even though the roads are connected there.  Only a crossing in which
        # both ways continue *through* the node is a grade separation.
        has_structure_a = bool(bridge_a or tunnel_a)
        has_structure_b = bool(bridge_b or tunnel_b)
        endpoint_handoff = (role_a == "end" and role_b == "start") or (
            role_a == "start" and role_b == "end"
        )
        # A structure transition is a bridge/tunnel way meeting its UNTAGGED
        # approach road.  When both ways carry a structure tag the shared node
        # is a crossing, not a transition.
        structure_transition = endpoint_handoff and has_structure_a != has_structure_b
        if not structure_transition:
            if layer_a != layer_b:
                return False, "layer_mismatch"
            if bridge_a != bridge_b:
                return False, "bridge_tunnel_mismatch"
            if tunnel_a != tunnel_b:
                return False, "bridge_tunnel_mismatch"

        eligible_a = _vehicle_eligible(restr_a, vehicle_class)
        eligible_b = _vehicle_eligible(restr_b, vehicle_class)
        if eligible_a is False or eligible_b is False:
            return False, "access_restricted"

        # V104 review 4551845512: departure and arrival are DIFFERENT
        # questions.  Travelling a -> b needs to be able to LEAVE a at this
        # node and to ENTER b at this node.  Applying the entry rule to both
        # ways rejected two consecutive forward one-way ways (a ends at the
        # shared node, b starts there), which is a legal continuation.
        oneway_a = oneway_by_way.get(way_a, ONEWAY_UNKNOWN)
        oneway_b = oneway_by_way.get(way_b, ONEWAY_UNKNOWN)
        if not _can_leave(oneway_a, role_a):
            return False, "oneway_departure_against"
        if not _can_enter(oneway_b, role_b):
            return False, "oneway_arrival_against"

        return True, "shared_node"

    adjacent_by_way_node: dict[tuple[str, str], tuple[str, ...]] = {}
    blocked_by_way_node: dict[tuple[str, str], list[dict[str, str]]] = {}
    unresolved: list[dict[str, str]] = []
    undirected_edges: set[tuple[str, str]] = set()

    for node_id in sorted(node_members, key=_id_key):
        members = sorted(
            node_members[node_id], key=lambda item: (_id_key(item[0]), item[1])
        )
        # V104 review 4551845512: a pair of ways is adjacent when a legal
        # traversal exists in EITHER direction.  Each ordered pair is still
        # evaluated separately, so the blocked record can explain the
        # direction that is NOT allowed.
        directed: dict[tuple[str, str], tuple[bool, str]] = {}
        for way_id, role in members:
            for other_id, other_role in members:
                if other_id == way_id:
                    continue
                directed[(way_id, other_id)] = _traversable(
                    way_id, other_id, node_id, role, other_role
                )

        for way_id, role in members:
            neighbours: list[str] = []
            blocked: list[dict[str, str]] = []
            for other_id, other_role in members:
                if other_id == way_id:
                    continue
                forward_ok, forward_reason = directed[(way_id, other_id)]
                reverse_ok, reverse_reason = directed[(other_id, way_id)]
                if forward_ok or reverse_ok:
                    neighbours.append(other_id)
                    undirected_edges.add(tuple(sorted((way_id, other_id), key=_id_key)))
                    if not forward_ok:
                        blocked.append(
                            {
                                "neighbour_way_id": other_id,
                                "reason": forward_reason,
                                "direction": "blocked_but_reverse_allowed",
                            }
                        )
                    elif not reverse_ok:
                        blocked.append(
                            {
                                "neighbour_way_id": other_id,
                                "reason": reverse_reason,
                                "direction": "blocked_but_forward_allowed",
                            }
                        )
                else:
                    blocked.append(
                        {
                            "neighbour_way_id": other_id,
                            "reason": forward_reason,
                            "direction": "blocked_both_ways",
                        }
                    )
                    if (
                        forward_reason in {"oneway_arrival_against", "oneway_departure_against"}
                        and oneway_by_way.get(way_id) == ONEWAY_UNKNOWN
                    ):
                        unresolved.append(
                            {
                                "node_id": node_id,
                                "way_id": way_id,
                                "other_way_id": other_id,
                                "reason": "oneway_undetermined",
                            }
                        )
            adjacent_by_way_node[(way_id, node_id)] = tuple(
                sorted(set(neighbours), key=_id_key)
            )
            if blocked:
                blocked_by_way_node[(way_id, node_id)] = blocked

    return {
        "schema": "osm_source_adjacency/v1",
        "vehicle_class": vehicle_class,
        "node_members": {
            node_id: tuple(members)
            for node_id, members in sorted(node_members.items(), key=lambda i: _id_key(i[0]))
        },
        "node_role_by_way": {
            f"{way_id}@{node_id}": role
            for (way_id, node_id), role in sorted(
                node_role_by_way.items(), key=lambda i: (_id_key(i[0]), _id_key(i[1]))
            )
        },
        "adjacent_by_way_node": {
            f"{way_id}@{node_id}": neighbours
            for (way_id, node_id), neighbours in sorted(
                adjacent_by_way_node.items(), key=lambda i: (_id_key(i[0]), _id_key(i[1]))
            )
        },
        "blocked_by_way_node": {
            f"{way_id}@{node_id}": blocked
            for (way_id, node_id), blocked in sorted(
                blocked_by_way_node.items(), key=lambda i: (_id_key(i[0]), _id_key(i[1]))
            )
        },
        "oneway_by_way": {
            way_id: value
            for way_id, value in sorted(oneway_by_way.items(), key=lambda i: _id_key(i[0]))
        },
        "restrictions_by_way": {
            way_id: dict(sorted(restr.items()))
            for way_id, restr in sorted(restrictions_by_way.items(), key=lambda i: _id_key(i[0]))
        },
        "unresolved": sorted(
            unresolved, key=lambda i: (_id_key(i["way_id"]), _id_key(i["node_id"]))
        ),
        "summary": {
            "way_count": len(restrictions_by_way),
            "shared_node_count": len(node_members),
            "adjacency_edge_count": len(undirected_edges),
            "blocked_pair_count": len(blocked_by_way_node),
            "unresolved_count": len(unresolved),
        },
    }


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
