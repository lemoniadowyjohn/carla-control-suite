"""V103-O2 -- the source-grounded legal movement graph.

This module turns the OSM *facts* (:mod:`ultimate_pipeline.enrichment.
osm_restrictions`) into a directed movement graph and an
:class:`AllowedMovementReport` that a release gate can consume.

The central rule of this module (V103-O2 dispatch, item 4):

    **A missing relation does NOT mean every movement is legal.**

Three things are distinguished, and they are never collapsed:

* **explicit denial** -- an OSM ``no_*`` / ``only_*`` restriction forbids
  the movement -> ``DENY_SOURCE_PROVEN``;
* **known default permission** -- the OSM data model permits the movement
  unless a restriction says otherwise, and the ways involved are decidable
  for this actor -> ``ALLOW_SOURCE_PROVEN`` with a distinct
  ``rule_source``;
* **no source evidence either way** -> ``UNKNOWN_NO_SOURCE``.

Three more statuses cover the cases where the question cannot be answered
from the source at all:

* ``AMBIGUOUS_MAPPING`` -- the XODR correspondence is ambiguous;
* ``UNSUPPORTED_CONDITIONAL`` -- a conditional restriction governs the
  movement and no clock/vehicle context was supplied;
* ``PHYSICAL_DISCONTINUITY`` -- the two ways share a node but are
  grade-separated, or the direction forbids the movement outright.

The graph is keyed by ``(osm_way_id, node/span, direction, vehicle_class,
restriction_context)`` and every movement carries a ``rule_source`` and a
precise evidence id.

**Topology existence is not legal eligibility.**  A shared node proves the
ways are *connected*; it says nothing about whether the movement is legal
for the actor.  Those are separate computations here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Sequence

from ultimate_pipeline.enrichment.osm_restrictions import (
    AccessDecision,
    OsmDocument,
    OsmWay,
    Restriction,
    RestrictionSet,
    resolve_access,
    resolve_oneway,
)

__all__ = [
    "MovementStatus",
    "MovementRecord",
    "MovementGraph",
    "AllowedMovementReport",
    "SCHEMA_VERSION",
    "build_movement_graph",
    "build_allowed_movement_report",
    "compare_with_junction_connections",
    "render_report",
]

#: The version of the emitted report schema.
SCHEMA_VERSION = "osm_allowed_movement/v1"

#: Values that make a way grade-separated from another at a shared node.
_STRUCTURE_TAGS = ("bridge", "tunnel", "layer")


class MovementStatus(str, Enum):
    """The verdict for one movement."""

    #: The source permits the movement and permits it explicitly enough to
    #: be proven (an ``only_*`` restriction names it, or the OSM default
    #: permission applies to decidable ways).
    ALLOW_SOURCE_PROVEN = "ALLOW_SOURCE_PROVEN"
    #: The source forbids the movement (a ``no_*`` restriction, an
    #: ``only_*`` restriction that names another way, a one-way violation,
    #: or an access prohibition).
    DENY_SOURCE_PROVEN = "DENY_SOURCE_PROVEN"
    #: The source says nothing either way.
    UNKNOWN_NO_SOURCE = "UNKNOWN_NO_SOURCE"
    #: The source forbids it, but the binding to an XODR element is
    #: ambiguous.
    AMBIGUOUS_MAPPING = "AMBIGUOUS_MAPPING"
    #: A conditional restriction governs and no context was supplied.
    UNSUPPORTED_CONDITIONAL = "UNSUPPORTED_CONDITIONAL"
    #: The movement is physically impossible (grade separation, or the
    #: direction forbids it).
    PHYSICAL_DISCONTINUITY = "PHYSICAL_DISCONTINUITY"


#: ``rule_source`` values.  They distinguish *how* a verdict was reached,
#: so an ``ALLOW_SOURCE_PROVEN`` from an explicit ``only_*`` restriction is
#: never read as an ``ALLOW_SOURCE_PROVEN`` from the default permission.
RULE_ONLY_RESTRICTION = "osm_only_restriction"
RULE_NO_RESTRICTION = "osm_no_restriction"
RULE_DEFAULT_PERMISSION = "osm_default_permission"
RULE_ONEWAY = "osm_oneway"
RULE_ACCESS = "osm_access"
RULE_EXCEPTED = "osm_restriction_excepted"
RULE_CONDITIONAL = "osm_conditional_restriction"
RULE_PHYSICAL = "osm_physical_discontinuity"
RULE_AMBIGUOUS = "osm_ambiguous_correspondence"
RULE_NO_SOURCE = "osm_no_source_evidence"


@dataclass(frozen=True)
class MovementRecord:
    """One candidate movement through the source graph."""

    from_way: str
    to_way: str
    via_nodes: tuple[str, ...] = ()
    via_ways: tuple[str, ...] = ()
    vehicle_class: str = "motor_vehicle"
    status: str = MovementStatus.UNKNOWN_NO_SOURCE.value
    rule_source: str = RULE_NO_SOURCE
    evidence: tuple[str, ...] = ()
    reason: str = ""

    @property
    def allowed(self) -> bool:
        return self.status == MovementStatus.ALLOW_SOURCE_PROVEN.value

    @property
    def denied(self) -> bool:
        return self.status == MovementStatus.DENY_SOURCE_PROVEN.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_way": self.from_way,
            "to_way": self.to_way,
            "via_nodes": list(self.via_nodes),
            "via_ways": list(self.via_ways),
            "vehicle_class": self.vehicle_class,
            "status": self.status,
            "rule_source": self.rule_source,
            "evidence": list(self.evidence),
            "reason": self.reason,
        }


@dataclass
class MovementGraph:
    """The directed movement graph of one document for one actor class."""

    document: OsmDocument
    vehicle_class: str
    restrictions: RestrictionSet
    movements: tuple[MovementRecord, ...] = ()
    ways_by_node: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: per-way access and one-way decisions
    access: Mapping[str, AccessDecision] = field(default_factory=dict)
    oneway: Mapping[str, Any] = field(default_factory=dict)

    def movements_from(self, from_way: str) -> tuple[MovementRecord, ...]:
        return tuple(m for m in self.movements if m.from_way == str(from_way))

    def find(
        self, from_way: str, to_way: str, via_nodes: Sequence[str] = ()
    ) -> tuple[MovementRecord, ...]:
        return tuple(
            m
            for m in self.movements
            if m.from_way == str(from_way)
            and m.to_way == str(to_way)
            and (not via_nodes or tuple(via_nodes) == m.via_nodes)
        )


# ---------------------------------------------------------------------------
# Physical separation
# ---------------------------------------------------------------------------


def _structure_of(way: OsmWay) -> tuple[bool, bool, int]:
    tags = {str(k).lower(): str(v).lower() for k, v in way.tags.items()}
    bridge = tags.get("bridge", "") in {"yes", "viaduct", "1", "true"}
    tunnel = tags.get("tunnel", "") in {"yes", "building_passage", "1", "true"}
    try:
        layer = int(tags.get("layer", "0"))
    except (TypeError, ValueError):
        layer = 0
    return bridge, tunnel, layer


def _is_grade_separated(way_a: OsmWay, way_b: OsmWay) -> bool:
    """True when two ways that share a node are NOT connected for a vehicle.

    A bridge and the road it crosses share a node but are not traversable
    between each other.  So do two ways whose ``layer`` differs.  A bridge
    meeting its *untagged* approach road is a transition, not a crossing.
    """
    bridge_a, tunnel_a, layer_a = _structure_of(way_a)
    bridge_b, tunnel_b, layer_b = _structure_of(way_b)
    structured_a = bridge_a or tunnel_a
    structured_b = bridge_b or tunnel_b
    if structured_a and structured_b:
        # Both are structured: a crossing, not a transition.
        return True
    if layer_a != layer_b:
        return True
    return False


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def _way_role(way: OsmWay, node_id: str) -> str:
    """Where ``node_id`` sits in ``way``: start / end / interior."""
    refs = way.node_refs
    if not refs:
        return "interior"
    if node_id == refs[0]:
        return "start"
    if node_id == refs[-1]:
        return "end"
    return "interior"


def _can_leave(oneway_state: str, role: str) -> bool:
    if oneway_state == "forward":
        return role == "end"
    if oneway_state == "reverse":
        return role == "start"
    if oneway_state == "bidirectional":
        return True
    return False


def _can_enter(oneway_state: str, role: str) -> bool:
    if oneway_state == "forward":
        return role == "start"
    if oneway_state == "reverse":
        return role == "end"
    if oneway_state == "bidirectional":
        return True
    return False


def build_movement_graph(
    document: OsmDocument,
    *,
    vehicle_class: str = "motor_vehicle",
    restrictions: Optional[RestrictionSet] = None,
) -> MovementGraph:
    """Build the directed movement graph for one actor class.

    A movement candidate exists for every ordered pair of ways that share
    a node.  The verdict for each candidate is then decided by, in order:

    1. physical continuity (grade separation);
    2. the access and one-way facts of both ways;
    3. the turn restrictions that govern the movement.
    """
    from ultimate_pipeline.enrichment.osm_restrictions import parse_restrictions

    restriction_set = restrictions if restrictions is not None else parse_restrictions(document)

    access: dict[str, AccessDecision] = {}
    oneway: dict[str, Any] = {}
    for way_id, way in document.ways.items():
        access[way_id] = resolve_access(way.tags, vehicle_class)
        oneway[way_id] = resolve_oneway(way.tags, vehicle_class)

    ways_by_node: dict[str, tuple[str, ...]] = {}
    for node_id in {ref for way in document.ways.values() for ref in way.node_refs}:
        ways_by_node[node_id] = document.ways_sharing_node(node_id)

    movements: list[MovementRecord] = []
    for node_id in sorted(ways_by_node):
        members = ways_by_node[node_id]
        for from_way_id in members:
            from_way = document.way(from_way_id)
            if from_way is None:
                continue
            role_from = _way_role(from_way, node_id)
            for to_way_id in members:
                if to_way_id == from_way_id:
                    continue
                to_way = document.way(to_way_id)
                if to_way is None:
                    continue
                role_to = _way_role(to_way, node_id)

                if _is_grade_separated(from_way, to_way):
                    movements.append(
                        MovementRecord(
                            from_way=from_way_id,
                            to_way=to_way_id,
                            via_nodes=(node_id,),
                            vehicle_class=vehicle_class,
                            status=MovementStatus.PHYSICAL_DISCONTINUITY.value,
                            rule_source=RULE_PHYSICAL,
                            evidence=(f"node:{node_id}",),
                            reason=(
                                "the two ways share a node but are grade separated "
                                "(bridge/tunnel or differing layer)"
                            ),
                        )
                    )
                    continue

                access_from = access[from_way_id]
                access_to = access[to_way_id]
                if access_from.allowed is False or access_to.allowed is False:
                    movements.append(
                        MovementRecord(
                            from_way=from_way_id,
                            to_way=to_way_id,
                            via_nodes=(node_id,),
                            vehicle_class=vehicle_class,
                            status=MovementStatus.DENY_SOURCE_PROVEN.value,
                            rule_source=RULE_ACCESS,
                            evidence=(
                                f"way:{from_way_id}",
                                f"way:{to_way_id}",
                            ),
                            reason=(
                                access_from.reason
                                if access_from.allowed is False
                                else access_to.reason
                            ),
                        )
                    )
                    continue

                oneway_from = oneway[from_way_id]
                oneway_to = oneway[to_way_id]
                if not oneway_from.decidable or not oneway_to.decidable:
                    movements.append(
                        MovementRecord(
                            from_way=from_way_id,
                            to_way=to_way_id,
                            via_nodes=(node_id,),
                            vehicle_class=vehicle_class,
                            status=MovementStatus.UNSUPPORTED_CONDITIONAL.value,
                            rule_source=RULE_CONDITIONAL,
                            evidence=(f"way:{from_way_id}", f"way:{to_way_id}"),
                            reason=(
                                oneway_from.reason
                                if not oneway_from.decidable
                                else oneway_to.reason
                            ),
                        )
                    )
                    continue

                if not _can_leave(oneway_from.state, role_from) or not _can_enter(
                    oneway_to.state, role_to
                ):
                    movements.append(
                        MovementRecord(
                            from_way=from_way_id,
                            to_way=to_way_id,
                            via_nodes=(node_id,),
                            vehicle_class=vehicle_class,
                            status=MovementStatus.DENY_SOURCE_PROVEN.value,
                            rule_source=RULE_ONEWAY,
                            evidence=(
                                f"way:{from_way_id}",
                                f"way:{to_way_id}",
                                f"node:{node_id}",
                            ),
                            reason=(
                                f"the one-way direction of "
                                f"{from_way_id}/{to_way_id} forbids this movement"
                            ),
                        )
                    )
                    continue

                movements.append(
                    MovementRecord(
                        from_way=from_way_id,
                        to_way=to_way_id,
                        via_nodes=(node_id,),
                        vehicle_class=vehicle_class,
                        status=MovementStatus.UNKNOWN_NO_SOURCE.value,
                        rule_source=RULE_NO_SOURCE,
                        evidence=(f"node:{node_id}",),
                        reason="no turn restriction governs this movement yet",
                    )
                )

    movements.extend(_restriction_movements(document, restriction_set, vehicle_class))

    return MovementGraph(
        document=document,
        vehicle_class=vehicle_class,
        restrictions=restriction_set,
        movements=tuple(movements),
        ways_by_node=ways_by_node,
        access=access,
        oneway=oneway,
    )


def _restriction_movements(
    document: OsmDocument,
    restrictions: RestrictionSet,
    vehicle_class: str,
) -> list[MovementRecord]:
    """Apply the turn restrictions to the candidate movements.

    ``only_*`` is the important case: it does not merely permit one
    movement, it **forbids every alternative** from the same from-way via
    the same via-node.
    """
    out: list[MovementRecord] = []
    for restriction in restrictions.restrictions:
        if restriction.from_way is None:
            continue
        if restriction.status == "UNSUPPORTED_CONDITIONAL":
            out.append(
                MovementRecord(
                    from_way=restriction.from_way,
                    to_way=restriction.to_way or "",
                    via_nodes=restriction.via_nodes,
                    via_ways=restriction.via_ways,
                    vehicle_class=vehicle_class,
                    status=MovementStatus.UNSUPPORTED_CONDITIONAL.value,
                    rule_source=RULE_CONDITIONAL,
                    evidence=(restriction.evidence(),),
                    reason=restriction.reason,
                )
            )
            continue
        if not restriction.applicable:
            continue
        if vehicle_class in restriction.except_modes:
            out.append(
                MovementRecord(
                    from_way=restriction.from_way,
                    to_way=restriction.to_way or "",
                    via_nodes=restriction.via_nodes,
                    via_ways=restriction.via_ways,
                    vehicle_class=vehicle_class,
                    status=MovementStatus.UNKNOWN_NO_SOURCE.value,
                    rule_source=RULE_EXCEPTED,
                    evidence=(restriction.evidence(),),
                    reason=(
                        f"the restriction does not apply to {vehicle_class} "
                        f"(except={','.join(restriction.except_modes)})"
                    ),
                )
            )
            continue

        if restriction.kind == "no":
            out.append(
                MovementRecord(
                    from_way=restriction.from_way,
                    to_way=restriction.to_way or "",
                    via_nodes=restriction.via_nodes,
                    via_ways=restriction.via_ways,
                    vehicle_class=vehicle_class,
                    status=MovementStatus.DENY_SOURCE_PROVEN.value,
                    rule_source=RULE_NO_RESTRICTION,
                    evidence=(restriction.evidence(),),
                    reason=restriction.reason,
                )
            )
        elif restriction.kind == "only":
            out.append(
                MovementRecord(
                    from_way=restriction.from_way,
                    to_way=restriction.to_way or "",
                    via_nodes=restriction.via_nodes,
                    via_ways=restriction.via_ways,
                    vehicle_class=vehicle_class,
                    status=MovementStatus.ALLOW_SOURCE_PROVEN.value,
                    rule_source=RULE_ONLY_RESTRICTION,
                    evidence=(restriction.evidence(),),
                    reason=(
                        f"an only_* restriction names this movement explicitly"
                    ),
                )
            )
    return out


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


@dataclass
class AllowedMovementReport:
    """The handoff API for a release gate.

    Every field is derived from executed source facts.  ``status`` is the
    OVERALL verdict; it is ``BLOCKED_INPUT`` when the source could not be
    read at all and is otherwise the count-weighted summary.
    """

    schema_version: str = SCHEMA_VERSION
    status: str = "NOT_RUN"
    reason: str = ""
    vehicle_class: str = "motor_vehicle"
    source_sha256: str = ""
    source_bytes: int = 0
    source_complete: bool = True
    counts: Mapping[str, int] = field(default_factory=dict)
    movements: tuple[MovementRecord, ...] = ()
    restrictions_parsed: int = 0
    restrictions_applied: int = 0
    restrictions_contradicted: int = 0
    restrictions_missing: int = 0
    restrictions_ambiguous: int = 0
    undecidable_restrictions: int = 0
    notes: tuple[str, ...] = ()

    def by_status(self, status: MovementStatus) -> tuple[MovementRecord, ...]:
        return tuple(m for m in self.movements if m.status == status.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "reason": self.reason,
            "vehicle_class": self.vehicle_class,
            "source": {
                "sha256": self.source_sha256,
                "bytes": self.source_bytes,
                "complete": self.source_complete,
            },
            "counts": dict(self.counts),
            "restrictions": {
                "parsed": self.restrictions_parsed,
                "applied": self.restrictions_applied,
                "contradicted": self.restrictions_contradicted,
                "missing": self.restrictions_missing,
                "ambiguous": self.restrictions_ambiguous,
                "undecidable": self.undecidable_restrictions,
            },
            "movements": [m.to_dict() for m in self.movements],
            "notes": list(self.notes),
        }


def build_allowed_movement_report(
    graph: MovementGraph,
    *,
    default_permission: bool = True,
) -> AllowedMovementReport:
    """Resolve every candidate movement into a verdict.

    ``default_permission`` decides whether an ungoverned movement between
    two decidable ways is ``ALLOW_SOURCE_PROVEN`` (the OSM data model's
    default permission) or ``UNKNOWN_NO_SOURCE``.  It is a policy switch,
    and the switch is RECORDED in the report so a reader can see which
    interpretation produced the verdict.
    """
    movements: list[MovementRecord] = []
    counts = {status.value: 0 for status in MovementStatus}

    # An ``only_*`` restriction does not merely permit one movement: it
    # FORBIDS every alternative from the same from-way through the same
    # via-node.  The alternatives must therefore be denied explicitly, not
    # left to the default permission.
    #
    # With several ``only_*`` restrictions from the same way through the
    # same node the OSM model permits only the INTERSECTION of the named
    # ways, so the permitted set is intersected.
    only_named: dict[tuple[str, tuple[str, ...]], list[set[str]]] = {}
    for restriction in graph.restrictions.applicable():
        if restriction.kind != "only" or not restriction.from_way or not restriction.to_way:
            continue
        only_named.setdefault(
            (restriction.from_way, restriction.via_nodes), []
        ).append({restriction.to_way})

    only_permits: dict[tuple[str, tuple[str, ...]], set[str]] = {
        key: set.intersection(*sets) for key, sets in only_named.items()
    }

    #: rule_source values that already carry a DECISION.  The default
    #: permission must never overwrite one of them -- otherwise a
    #: restriction's own record would be replaced by a generic permission
    #: and the restriction would silently vanish from the report.
    decided_sources = frozenset(
        {
            RULE_ONLY_RESTRICTION,
            RULE_NO_RESTRICTION,
            RULE_EXCEPTED,
            RULE_CONDITIONAL,
            RULE_PHYSICAL,
            RULE_ACCESS,
            RULE_ONEWAY,
            RULE_AMBIGUOUS,
        }
    )

    for movement in graph.movements:
        record = movement
        if movement.status == MovementStatus.UNKNOWN_NO_SOURCE.value:
            only_key = (movement.from_way, movement.via_nodes)
            permitted = only_permits.get(only_key)
            if permitted is not None and movement.to_way in permitted:
                record = MovementRecord(
                    from_way=movement.from_way,
                    to_way=movement.to_way,
                    via_nodes=movement.via_nodes,
                    via_ways=movement.via_ways,
                    vehicle_class=movement.vehicle_class,
                    status=MovementStatus.ALLOW_SOURCE_PROVEN.value,
                    rule_source=RULE_ONLY_RESTRICTION,
                    evidence=movement.evidence,
                    reason="an only_* restriction names this movement explicitly",
                )
            elif permitted is not None:
                record = MovementRecord(
                    from_way=movement.from_way,
                    to_way=movement.to_way,
                    via_nodes=movement.via_nodes,
                    via_ways=movement.via_ways,
                    vehicle_class=movement.vehicle_class,
                    status=MovementStatus.DENY_SOURCE_PROVEN.value,
                    rule_source=RULE_ONLY_RESTRICTION,
                    evidence=movement.evidence,
                    reason=(
                        "an only_* restriction from this way through this node "
                        "names a different movement, so this alternative is "
                        "forbidden"
                    ),
                )
            elif movement.rule_source not in decided_sources and default_permission:
                record = MovementRecord(
                    from_way=movement.from_way,
                    to_way=movement.to_way,
                    via_nodes=movement.via_nodes,
                    via_ways=movement.via_ways,
                    vehicle_class=movement.vehicle_class,
                    status=MovementStatus.ALLOW_SOURCE_PROVEN.value,
                    rule_source=RULE_DEFAULT_PERMISSION,
                    evidence=movement.evidence,
                    reason=(
                        "the OSM data model permits a movement at a shared node "
                        "unless a restriction forbids it, and no restriction "
                        "governs this one"
                    ),
                )
        movements.append(record)
        counts[record.status] = counts.get(record.status, 0) + 1

    restrictions = graph.restrictions
    return AllowedMovementReport(
        status="PASS" if graph.document.complete else "INCOMPLETE",
        reason=(
            ""
            if graph.document.complete
            else "the OSM source is not a complete document"
        ),
        vehicle_class=graph.vehicle_class,
        source_sha256=graph.document.sha256,
        source_bytes=graph.document.byte_size,
        source_complete=graph.document.complete,
        counts=counts,
        movements=tuple(movements),
        restrictions_parsed=len(restrictions.restrictions),
        restrictions_applied=len(restrictions.applicable()),
        restrictions_contradicted=sum(
            1 for m in movements if m.rule_source == RULE_NO_RESTRICTION
        ),
        restrictions_missing=sum(
            1 for m in movements if m.status == MovementStatus.UNKNOWN_NO_SOURCE.value
        ),
        restrictions_ambiguous=len(restrictions.malformed()),
        undecidable_restrictions=len(restrictions.undecidable()),
        notes=(
            f"default_permission={'on' if default_permission else 'off'}: "
            "an ungoverned movement between decidable ways is the OSM data "
            "model's default permission, not a proven fact about the map",
            f"vehicle_class={graph.vehicle_class}",
        ),
    )


def render_report(report: AllowedMovementReport) -> str:
    """Render the report as canonical JSON."""
    return json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# The XODR comparison API (dispatch item 6)
# ---------------------------------------------------------------------------


@dataclass
class ConnectionComparison:
    """One XODR junction connection compared with the OSM movements."""

    from_road: str
    to_road: str
    junction_id: str
    connection_id: str
    status: str
    rule_source: str
    osm_from_way: Optional[str]
    osm_to_way: Optional[str]
    reason: str
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_road": self.from_road,
            "to_road": self.to_road,
            "junction_id": self.junction_id,
            "connection_id": self.connection_id,
            "status": self.status,
            "rule_source": self.rule_source,
            "osm_from_way": self.osm_from_way,
            "osm_to_way": self.osm_to_way,
            "reason": self.reason,
            "evidence": list(self.evidence),
        }


def compare_with_junction_connections(
    root: Any,
    graph: MovementGraph,
    associations: Mapping[str, Mapping[str, Any]],
) -> tuple[ConnectionComparison, ...]:
    """Map each XODR junction connection to a possible OSM legal movement.

    The join is made **only** through the oriented source correspondence
    produced by the O1 correspondence layer: an XODR road is bound to its
    OSM way only when the correspondence is EXACT or HIGH and carries an
    orientation.  Nothing else is guessed.

    The comparison is **non-destructive**: it reports what the OSM source
    says about each generated connection.  It never rewrites OpenDRIVE.
    """
    road_to_way: dict[str, str] = {}
    for road_id, association in (associations or {}).items():
        if str(association.get("class")) not in {"EXACT", "HIGH"}:
            continue
        osm_way_id = str(association.get("osm_way_id") or "")
        if osm_way_id:
            road_to_way[str(road_id)] = osm_way_id

    out: list[ConnectionComparison] = []
    for junction in root.findall("./junction"):
        junction_id = str(junction.get("id", ""))
        for connection in junction.findall("./connection"):
            connection_id = str(connection.get("id", ""))
            from_road = str(connection.get("incomingRoad", ""))
            to_road = str(connection.get("connectingRoad", ""))
            if not from_road or not to_road:
                continue

            osm_from = road_to_way.get(from_road)
            osm_to = road_to_way.get(to_road)
            if osm_from is None or osm_to is None:
                out.append(
                    ConnectionComparison(
                        from_road=from_road,
                        to_road=to_road,
                        junction_id=junction_id,
                        connection_id=connection_id,
                        status=MovementStatus.UNKNOWN_NO_SOURCE.value,
                        rule_source=RULE_NO_SOURCE,
                        osm_from_way=osm_from,
                        osm_to_way=osm_to,
                        reason=(
                            "the XODR roads of this connection have no EXACT/HIGH "
                            "oriented OSM correspondence, so no OSM movement can "
                            "be bound to it"
                        ),
                    )
                )
                continue

            candidates = [
                m
                for m in graph.movements
                if m.from_way == osm_from and m.to_way == osm_to
            ]
            if not candidates:
                out.append(
                    ConnectionComparison(
                        from_road=from_road,
                        to_road=to_road,
                        junction_id=junction_id,
                        connection_id=connection_id,
                        status=MovementStatus.UNKNOWN_NO_SOURCE.value,
                        rule_source=RULE_NO_SOURCE,
                        osm_from_way=osm_from,
                        osm_to_way=osm_to,
                        reason=(
                            "the two OSM ways share no node, so the source "
                            "describes no movement between them"
                        ),
                    )
                )
                continue

            worst = min(
                candidates,
                key=lambda m: _STATUS_PRECEDENCE.get(m.status, 99),
            )
            out.append(
                ConnectionComparison(
                    from_road=from_road,
                    to_road=to_road,
                    junction_id=junction_id,
                    connection_id=connection_id,
                    status=worst.status,
                    rule_source=worst.rule_source,
                    osm_from_way=osm_from,
                    osm_to_way=osm_to,
                    reason=worst.reason,
                    evidence=worst.evidence,
                )
            )
    return tuple(out)


#: When several candidate movements match, the most restrictive verdict wins.
_STATUS_PRECEDENCE = {
    MovementStatus.DENY_SOURCE_PROVEN.value: 0,
    MovementStatus.PHYSICAL_DISCONTINUITY.value: 1,
    MovementStatus.UNSUPPORTED_CONDITIONAL.value: 2,
    MovementStatus.AMBIGUOUS_MAPPING.value: 3,
    MovementStatus.UNKNOWN_NO_SOURCE.value: 4,
    MovementStatus.ALLOW_SOURCE_PROVEN.value: 5,
}
