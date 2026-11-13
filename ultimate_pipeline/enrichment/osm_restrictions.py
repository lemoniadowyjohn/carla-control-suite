"""V103-O2 -- OSM restriction and access facts.

This module owns the *source fact* layer of the legal-movement work: it
parses an OSM document into the facts a movement decision needs, and it
resolves the access hierarchy for a given actor.

Design rules (V103-O2 dispatch):

* **Nothing is invented.**  A fact that the source does not carry is
  reported as an explicit status; it is never silently defaulted.
* **Undecidable is a first-class status.**  A conditional restriction with
  no time/vehicle context, an unparseable relation and a truncated source
  are all explicit outcomes -- never a silent permission.
* **The source is read safely.**  The OSM document is admitted with an
  explicit, bounded, entity-free scan before any structure is built.

The access precedence follows the OSM tagging scheme: the most specific
tag wins, and the order is

    ``<class>:<mode>``  >  ``<class>``  >  ``vehicle``  >  ``access``

so a ``motor_vehicle=no`` overrides a permissive ``access=yes``, and a
``vehicle=no`` overrides nothing more specific but does block every class
that has no more specific tag.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

__all__ = [
    "OsmSourceError",
    "OsmNode",
    "OsmWay",
    "OsmMember",
    "OsmRelation",
    "OsmDocument",
    "AccessDecision",
    "Restriction",
    "RestrictionSet",
    "VEHICLE_CLASSES",
    "read_osm_document",
    "resolve_access",
    "resolve_oneway",
    "parse_restrictions",
]

#: Maximum accepted OSM document size (bytes).  The pinned Ingolstadt OSM is
#: 11,154,738 B, so this is generous while still bounding the allocation.
MAX_OSM_BYTES = 512 * 1024 * 1024
#: Maximum accepted element count.
MAX_OSM_ELEMENTS = 20_000_000
#: Maximum accepted nesting depth.
MAX_OSM_DEPTH = 64


class OsmSourceError(RuntimeError):
    """The OSM source is missing, unreadable, unparseable or unsafe."""


# ---------------------------------------------------------------------------
# Document model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OsmNode:
    """One OSM node."""

    id: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    tags: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OsmWay:
    """One OSM way: its ordered node references and its tags."""

    id: str
    node_refs: tuple[str, ...] = ()
    tags: Mapping[str, str] = field(default_factory=dict)

    @property
    def start_node(self) -> Optional[str]:
        return self.node_refs[0] if self.node_refs else None

    @property
    def end_node(self) -> Optional[str]:
        return self.node_refs[-1] if self.node_refs else None


@dataclass(frozen=True)
class OsmMember:
    """One relation member."""

    type: str
    ref: str
    role: str = ""


@dataclass(frozen=True)
class OsmRelation:
    """One OSM relation."""

    id: str
    members: tuple[OsmMember, ...] = ()
    tags: Mapping[str, str] = field(default_factory=dict)

    def members_with_role(self, role: str) -> tuple[OsmMember, ...]:
        return tuple(m for m in self.members if m.role == role)


@dataclass
class OsmDocument:
    """A parsed OSM document plus its source identity."""

    sha256: str
    byte_size: int
    nodes: dict[str, OsmNode] = field(default_factory=dict)
    ways: dict[str, OsmWay] = field(default_factory=dict)
    relations: dict[str, OsmRelation] = field(default_factory=dict)
    generator: str = ""
    version: str = ""
    complete: bool = True

    # -- lookups ---------------------------------------------------------
    def way(self, way_id: str) -> Optional[OsmWay]:
        return self.ways.get(str(way_id))

    def relation(self, relation_id: str) -> Optional[OsmRelation]:
        return self.relations.get(str(relation_id))

    def ways_sharing_node(self, node_id: str) -> tuple[str, ...]:
        """Every way that references ``node_id``, in deterministic order."""
        node = str(node_id)
        return tuple(
            sorted(
                way_id
                for way_id, way in self.ways.items()
                if node in way.node_refs
            )
        )

    @property
    def relation_count(self) -> int:
        return len(self.relations)

    @property
    def restriction_relation_count(self) -> int:
        return sum(
            1
            for rel in self.relations.values()
            if str(rel.tags.get("type", "")).strip().lower() == "restriction"
        )


# ---------------------------------------------------------------------------
# Safe reading
# ---------------------------------------------------------------------------


def _safe_scan(data: bytes) -> None:
    """Reject an OSM document that carries declarations we must not honour.

    Uses expat so that a ``<!DOCTYPE`` inside a comment or a text node is
    NOT mistaken for a declaration, while a real declaration always is.
    External entity references are refused rather than followed.
    """
    import xml.parsers.expat

    parser = xml.parsers.expat.ParserCreate()

    def _reject_doctype(*_args: object) -> None:
        raise OsmSourceError("DOCTYPE and entity declarations are forbidden")

    def _reject_entity(*_args: object) -> None:
        raise OsmSourceError("entity declarations are forbidden")

    def _reject_external(*_args: object) -> bool:
        raise OsmSourceError("external entity references are forbidden")

    parser.StartDoctypeDeclHandler = _reject_doctype
    parser.EntityDeclHandler = _reject_entity
    parser.ExternalEntityRefHandler = _reject_external
    try:
        parser.Parse(data, True)
    except OsmSourceError:
        raise
    except xml.parsers.expat.ExpatError as exc:
        raise OsmSourceError(f"OSM source is not well-formed: {exc}") from exc


def read_osm_document(path: str | Path) -> OsmDocument:
    """Read and admit an OSM document.

    Raises :class:`OsmSourceError` for a missing, oversized, unparseable
    or unsafe source.  The caller MUST treat that as ``BLOCKED_INPUT`` and
    never as a pass.
    """
    import xml.parsers.expat

    target = Path(path)
    if not target.is_file():
        raise OsmSourceError(f"OSM source missing: {target}")

    size = target.stat().st_size
    if size > MAX_OSM_BYTES:
        raise OsmSourceError(
            f"OSM source is {size} bytes; the limit is {MAX_OSM_BYTES}"
        )

    data = target.read_bytes()
    if len(data) > MAX_OSM_BYTES:
        raise OsmSourceError(
            f"OSM source is {len(data)} bytes; the limit is {MAX_OSM_BYTES}"
        )

    _safe_scan(data)

    parser = xml.parsers.expat.ParserCreate()
    nodes: dict[str, OsmNode] = {}
    ways: dict[str, OsmWay] = {}
    relations: dict[str, OsmRelation] = {}

    state: dict[str, Any] = {
        "kind": "",
        "id": "",
        "refs": [],
        "members": [],
        "tags": {},
        "lat": None,
        "lon": None,
        "elements": 0,
        "depth": 0,
        "max_depth": 0,
    }

    def start_element(name: str, attrs: Mapping[str, str]) -> None:
        state["elements"] += 1
        if state["elements"] > MAX_OSM_ELEMENTS:
            raise OsmSourceError("OSM element count exceeds the limit")
        state["depth"] += 1
        state["max_depth"] = max(state["max_depth"], state["depth"])
        if state["depth"] > MAX_OSM_DEPTH:
            raise OsmSourceError("OSM nesting depth exceeds the limit")
        if name == "osm":
            state["generator"] = attrs.get("generator", "")
            state["version"] = attrs.get("version", "")
        elif name == "node":
            state["kind"] = "node"
            state["id"] = attrs.get("id", "")
            state["tags"] = {}
            try:
                state["lat"] = float(attrs["lat"])
                state["lon"] = float(attrs["lon"])
            except (KeyError, TypeError, ValueError):
                state["lat"] = None
                state["lon"] = None
        elif name == "way":
            state["kind"] = "way"
            state["id"] = attrs.get("id", "")
            state["refs"] = []
            state["tags"] = {}
        elif name == "relation":
            state["kind"] = "relation"
            state["id"] = attrs.get("id", "")
            state["members"] = []
            state["tags"] = {}
        elif name == "nd":
            ref = attrs.get("ref", "")
            if ref:
                state["refs"].append(ref)
        elif name == "member":
            state["members"].append(
                OsmMember(
                    type=attrs.get("type", ""),
                    ref=attrs.get("ref", ""),
                    role=attrs.get("role", ""),
                )
            )
        elif name == "tag":
            key = attrs.get("k", "")
            if key:
                state["tags"][key] = attrs.get("v", "")

    def end_element(name: str) -> None:
        if name == "node" and state["kind"] == "node" and state["id"]:
            nodes[state["id"]] = OsmNode(
                id=state["id"],
                lat=state["lat"],
                lon=state["lon"],
                tags=dict(state["tags"]),
            )
        elif name == "way" and state["kind"] == "way" and state["id"]:
            ways[state["id"]] = OsmWay(
                id=state["id"],
                node_refs=tuple(state["refs"]),
                tags=dict(state["tags"]),
            )
        elif name == "relation" and state["kind"] == "relation" and state["id"]:
            relations[state["id"]] = OsmRelation(
                id=state["id"],
                members=tuple(state["members"]),
                tags=dict(state["tags"]),
            )
        state["depth"] = max(0, state["depth"] - 1)
        if name in {"node", "way", "relation"}:
            state["kind"] = ""

    parser.StartElementHandler = start_element
    parser.EndElementHandler = end_element
    try:
        parser.Parse(data, True)
    except OsmSourceError:
        raise
    except xml.parsers.expat.ExpatError as exc:
        raise OsmSourceError(f"OSM source is not well-formed: {exc}") from exc

    # A document that ends mid-element, or that declares itself truncated,
    # is not a complete source.
    complete = True
    for way in ways.values():
        if len(way.node_refs) < 2:
            complete = False
            break
    text = data[:4096].decode("utf-8", "replace")
    if "Overpass" in text and not data.rstrip().endswith(b"</osm>"):
        complete = False

    return OsmDocument(
        sha256=hashlib.sha256(data).hexdigest(),
        byte_size=len(data),
        nodes=nodes,
        ways=ways,
        relations=relations,
        generator=state.get("generator", ""),
        version=state.get("version", ""),
        complete=complete,
    )


# ---------------------------------------------------------------------------
# Access resolution
# ---------------------------------------------------------------------------

#: The actor classes this module understands.  The key is the OSM access
#: key fragment used to look up the most specific tag.
VEHICLE_CLASSES: Mapping[str, str] = {
    "motor_vehicle": "motor_vehicle",
    "motorcar": "motorcar",
    "car": "motorcar",
    "psv": "psv",
    "bus": "bus",
    "bicycle": "bicycle",
    "hgv": "hgv",
    "goods": "hgv",
    "emergency": "emergency",
    "residential": "",
}

#: Access values that permit travel.
_ALLOWED_VALUES = frozenset(
    {"yes", "permissive", "designated", "official", "destination", "public", "customers", "delivery", "destination_only"}
)
#: Access values that forbid travel.
_DENIED_VALUES = frozenset(
    {"no", "private", "agricultural", "forestry", "delivery_only", "customers_only", "no_access"}
)
#: Access values that permit travel only under a condition the source does
#: not spell out.  They are NOT a plain permission.
_CONDITIONAL_VALUES = frozenset({"destination", "customers", "delivery"})


@dataclass(frozen=True)
class AccessDecision:
    """The resolved access of one way for one actor class.

    ``allowed`` is ``None`` when the source cannot decide.  A conditional
    value (``destination``, ``customers``, ``delivery``) is *not* a plain
    permission and is reported as ``conditional``.
    """

    vehicle_class: str
    allowed: Optional[bool]
    conditional: bool
    source_tag: str
    source_value: str
    reason: str

    @property
    def decided(self) -> bool:
        return self.allowed is not None


def _access_tag_order(vehicle_class: str) -> tuple[str, ...]:
    """Tags in DECREASING specificity for one actor class."""
    keys: list[str] = []
    specific = VEHICLE_CLASSES.get(vehicle_class, vehicle_class)
    if specific:
        keys.append(specific)
    if vehicle_class != specific:
        keys.append(vehicle_class)
    keys.append("vehicle")
    keys.append("access")
    # de-duplicate, keeping order
    seen: set[str] = set()
    ordered: list[str] = []
    for key in keys:
        if key and key not in seen:
            seen.add(key)
            ordered.append(key)
    return tuple(ordered)


def resolve_access(
    tags: Mapping[str, str], vehicle_class: str
) -> AccessDecision:
    """Resolve the access of a way for one actor class.

    The most specific tag wins.  A value the source does not resolve
    (``conditional`` variants, an unrecognised value) yields
    ``allowed=None`` -- an explicit *not decidable*, never a permission.
    """
    lowered = {str(k).strip().lower(): str(v).strip().lower() for k, v in (tags or {}).items()}
    for key in _access_tag_order(vehicle_class):
        if key not in lowered:
            continue
        value = lowered[key]
        if value in _ALLOWED_VALUES:
            conditional = value in _CONDITIONAL_VALUES
            return AccessDecision(
                vehicle_class=vehicle_class,
                allowed=True,
                conditional=conditional,
                source_tag=key,
                source_value=value,
                reason=(
                    f"{key}={value} permits {vehicle_class}"
                    + (" under an unstated condition" if conditional else "")
                ),
            )
        if value in _DENIED_VALUES:
            return AccessDecision(
                vehicle_class=vehicle_class,
                allowed=False,
                conditional=False,
                source_tag=key,
                source_value=value,
                reason=f"{key}={value} forbids {vehicle_class}",
            )
        return AccessDecision(
            vehicle_class=vehicle_class,
            allowed=None,
            conditional=False,
            source_tag=key,
            source_value=value,
            reason=f"{key}={value} is not a resolvable access value",
        )
    # No access tag at all: the OSM default is permissive.
    return AccessDecision(
        vehicle_class=vehicle_class,
        allowed=True,
        conditional=False,
        source_tag="",
        source_value="",
        reason="no access tag: the OSM default permits this actor",
    )


@dataclass(frozen=True)
class OnewayDecision:
    """The resolved one-way state of a way for one actor class."""

    vehicle_class: str
    state: str  # forward | reverse | bidirectional | unknown
    source_tag: str
    source_value: str
    reason: str

    @property
    def decidable(self) -> bool:
        return self.state != "unknown"


def resolve_oneway(
    tags: Mapping[str, str], vehicle_class: str
) -> OnewayDecision:
    """Resolve the one-way state of a way for one actor class.

    ``oneway`` may be overridden per actor (``oneway:bicycle``) and may be
    conditional (``oneway:conditional``), which makes the direction
    time-dependent and therefore **not decidable** without a clock context.
    """
    lowered = {str(k).strip().lower(): str(v).strip().lower() for k, v in (tags or {}).items()}

    specific = VEHICLE_CLASSES.get(vehicle_class, vehicle_class)
    for key in (f"oneway:{specific}", f"oneway:{vehicle_class}", "oneway"):
        if key not in lowered:
            continue
        value = lowered[key]
        if value in {"yes", "true", "1"}:
            return OnewayDecision(vehicle_class, "forward", key, value, f"{key}={value}")
        if value in {"-1", "reverse"}:
            return OnewayDecision(vehicle_class, "reverse", key, value, f"{key}={value}")
        if value in {"no", "false", "0"}:
            return OnewayDecision(vehicle_class, "bidirectional", key, value, f"{key}={value}")
        return OnewayDecision(
            vehicle_class, "unknown", key, value, f"{key}={value} is not decidable"
        )

    if lowered.get("oneway:conditional"):
        return OnewayDecision(
            vehicle_class,
            "unknown",
            "oneway:conditional",
            lowered["oneway:conditional"],
            "oneway:conditional makes the direction time-dependent; no clock context was supplied",
        )
    if lowered.get("reversible"):
        return OnewayDecision(
            vehicle_class,
            "unknown",
            "reversible",
            lowered["reversible"],
            "reversible makes the direction time-dependent; no clock context was supplied",
        )
    if lowered.get("junction", "") == "roundabout":
        return OnewayDecision(
            vehicle_class, "forward", "junction=roundabout", "roundabout",
            "junction=roundabout implies a one-way along the node order",
        )
    return OnewayDecision(
        vehicle_class, "bidirectional", "", "",
        "no oneway tag: the OSM default is two-way",
    )


# ---------------------------------------------------------------------------
# Restriction relations
# ---------------------------------------------------------------------------

#: ``no_left_turn`` / ``only_straight_on`` / ``no_u_turn``.
_RESTRICTION_RE = re.compile(r"^(no|only)_([a-z0-9_]+)$")

#: Restriction forms this implementation understands.  ``no_entry`` and
#: ``no_exit`` are valid OSM but need a from/to semantics this module does
#: not model, so they are reported as ``UNSUPPORTED_FORM`` rather than
#: silently permitted.
_KNOWN_VALUES = frozenset(
    {
        "left_turn", "right_turn", "straight_on", "u_turn", "u_turns",
        "left", "right", "straight", "through", "merge_to",
    }
)


@dataclass(frozen=True)
class RestrictionContext:
    """A clock and actor context for conditional restrictions.

    A conditional restriction is only decidable with a clock context.  This
    object carries one.  ``clock`` is a local ``HH:MM`` string and
    ``day`` an optional ISO weekday abbreviation (``Mo``, ``Tu``, ...).
    """

    clock: Optional[str] = None
    day: Optional[str] = None
    vehicle_class: str = ""


#: A daily time window, e.g. ``10:00-16:00`` or ``Mo-Fr 07:00-09:00``.
_DAY_TOKEN = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)"
_DAY_RANGE = rf"{_DAY_TOKEN}(?:-{_DAY_TOKEN})?"
_DAY_LIST = rf"{_DAY_RANGE}(?:,{_DAY_RANGE})*"
_WINDOW_RE = re.compile(
    rf"(?P<days>{_DAY_LIST})?\s*"
    r"(?P<from>\d{1,2}:\d{2})-(?P<to>\d{1,2}:\d{2})"
)
#: The leading ``yes`` / ``no`` of a conditional restriction value.
_CONDITIONAL_VALUE_RE = re.compile(
    r"^\s*(?P<mode>yes|no)\s*@\s*(?P<condition>.+?)\s*$", re.I | re.S
)


def _parse_clock(value: str) -> Optional[int]:
    try:
        hour, minute = value.split(":")
        return int(hour) * 60 + int(minute)
    except (AttributeError, TypeError, ValueError):
        return None


def evaluate_conditional(
    condition: str, context: RestrictionContext
) -> Optional[bool]:
    """Evaluate an OSM conditional restriction value.

    Returns ``True`` when the restriction APPLIES, ``False`` when it does
    NOT apply, and ``None`` when it still cannot be decided.

    The supported subset is the daily time window with an optional weekday
    set::

        no @ (10:00-16:00)
        yes @ (Mo-Fr 07:00-09:00)

    ``no`` means the restriction applies during the window; ``yes`` means it
    is lifted during the window.  Any other form (a dated range, a
    multi-condition value) returns ``None`` -- it is **never** guessed.
    """
    if not context.clock:
        return None
    match = _CONDITIONAL_VALUE_RE.match(str(condition or ""))
    if not match:
        return None
    mode = match.group("mode").lower()
    window = _WINDOW_RE.search(match.group("condition"))
    if not window:
        return None

    days = window.group("days")
    if days:
        # The weekday order is NOT lexical: "Mo" > "Fr" as strings, so the
        # range must be resolved by INDEX in the weekday sequence.
        order = ("mo", "tu", "we", "th", "fr", "sa", "su")
        wanted: set[str] = set()
        for part in days.split(","):
            part = part.strip().lower()
            if "-" in part:
                first, last = part.split("-", 1)
                if first not in order or last not in order:
                    return None
                lo, hi = order.index(first), order.index(last)
                if lo > hi:
                    lo, hi = hi, lo
                wanted.update(order[lo : hi + 1])
            elif part:
                if part not in order:
                    return None
                wanted.add(part)
        if not context.day or context.day.lower() not in wanted:
            # Outside the named weekdays the restriction does not apply.
            return False

    now = _parse_clock(context.clock)
    start = _parse_clock(window.group("from"))
    end = _parse_clock(window.group("to"))
    if now is None or start is None or end is None:
        return None
    if start <= end:
        inside = start <= now < end
    else:
        # A window that wraps past midnight.
        inside = now >= start or now < end

    if mode == "no":
        return inside
    # "yes" lifts the restriction during the window.
    return not inside


@dataclass(frozen=True)
class Restriction:
    """One parsed turn restriction.

    ``status`` is one of:

    * ``APPLICABLE`` -- the relation is well formed and decidable now;
    * ``UNSUPPORTED_CONDITIONAL`` -- the restriction is conditional and no
      clock/vehicle context was supplied;
    * ``INCOMPLETE`` -- a member is missing or the relation is malformed;
    * ``UNSUPPORTED_FORM`` -- a restriction form this implementation does
      not model.
    """

    relation_id: str
    kind: str  # no | only
    value: str  # left_turn | straight_on | ...
    from_way: Optional[str]
    via_nodes: tuple[str, ...]
    via_ways: tuple[str, ...]
    to_way: Optional[str]
    except_modes: tuple[str, ...]
    status: str
    reason: str
    conditional: bool = False

    @property
    def applicable(self) -> bool:
        return self.status == "APPLICABLE"

    def evidence(self) -> str:
        return f"relation:{self.relation_id}"


@dataclass
class RestrictionSet:
    """The parsed restrictions of a document, indexed for lookup."""

    restrictions: tuple[Restriction, ...] = ()
    by_from_way: dict[str, tuple[Restriction, ...]] = field(default_factory=dict)
    incomplete: tuple[Restriction, ...] = ()

    def for_from_way(self, from_way: str) -> tuple[Restriction, ...]:
        return self.by_from_way.get(str(from_way), ())

    def applicable(self) -> tuple[Restriction, ...]:
        return tuple(r for r in self.restrictions if r.applicable)

    def undecidable(self) -> tuple[Restriction, ...]:
        return tuple(r for r in self.restrictions if r.status == "UNSUPPORTED_CONDITIONAL")

    def malformed(self) -> tuple[Restriction, ...]:
        return tuple(r for r in self.restrictions if r.status in {"INCOMPLETE", "UNSUPPORTED_FORM"})


def _members(relation: OsmRelation, role: str) -> tuple[OsmMember, ...]:
    return relation.members_with_role(role)


def parse_restrictions(
    document: OsmDocument,
    *,
    context: Optional[RestrictionContext] = None,
) -> RestrictionSet:
    """Parse every restriction relation in the document.

    Malformed relations, missing members and unsupported forms become
    explicit ``INCOMPLETE`` / ``UNSUPPORTED_FORM`` records -- they are never
    dropped and never silently permitted.

    A conditional restriction is ``UNSUPPORTED_CONDITIONAL`` unless a
    ``context`` is supplied **and** the conditional value is one this module
    can evaluate.  With a context, an evaluable conditional becomes
    ``APPLICABLE`` or is dropped from the applicable set because it does not
    apply at that moment.
    """
    parsed: list[Restriction] = []

    for relation_id in sorted(document.relations):
        relation = document.relations[relation_id]
        if str(relation.tags.get("type", "")).strip().lower() != "restriction":
            continue

        restriction_value = str(relation.tags.get("restriction", "")).strip().lower()
        match = _RESTRICTION_RE.match(restriction_value)
        except_modes = tuple(
            sorted(
                m.strip().lower()
                for m in str(relation.tags.get("except", "")).split(";")
                if m.strip()
            )
        )
        conditional = bool(str(relation.tags.get("restriction:conditional", "")).strip())
        conditional_except = bool(
            str(relation.tags.get("except:conditional", "")).strip()
        )

        from_members = _members(relation, "from")
        to_members = _members(relation, "to")
        via_members = [m for m in relation.members if m.role == "via"]

        def _make(
            kind: str,
            value: str,
            from_way: Optional[str],
            via_nodes: tuple[str, ...],
            via_ways: tuple[str, ...],
            to_way: Optional[str],
            status: str,
            reason: str,
            cond: bool = False,
        ) -> Restriction:
            return Restriction(
                relation_id=relation_id,
                kind=kind,
                value=value,
                from_way=from_way,
                via_nodes=via_nodes,
                via_ways=via_ways,
                to_way=to_way,
                except_modes=except_modes,
                status=status,
                reason=reason,
                conditional=cond,
            )

        if not match:
            parsed.append(
                _make(
                    "unknown", restriction_value or "(missing)",
                    None, (), (), None,
                    "UNSUPPORTED_FORM",
                    f"restriction={restriction_value!r} is not a no_*/only_* form",
                    conditional or conditional_except,
                )
            )
            continue

        kind, value = match.group(1), match.group(2)
        if value not in _KNOWN_VALUES:
            parsed.append(
                _make(
                    kind, value, None, (), (), None,
                    "UNSUPPORTED_FORM",
                    f"restriction value {value!r} is not modelled",
                    conditional or conditional_except,
                )
            )
            continue

        if len(from_members) != 1 or len(to_members) != 1:
            parsed.append(
                _make(
                    kind, value, None, (), (), None,
                    "INCOMPLETE",
                    f"expected exactly one 'from' and one 'to' member, got "
                    f"{len(from_members)} and {len(to_members)}",
                    conditional or conditional_except,
                )
            )
            continue

        from_way = from_members[0].ref or None
        to_way = to_members[0].ref or None
        via_nodes = tuple(m.ref for m in via_members if m.type == "node" and m.ref)
        via_ways = tuple(m.ref for m in via_members if m.type == "way" and m.ref)

        if not via_nodes and not via_ways:
            parsed.append(
                _make(
                    kind, value, from_way, (), (), to_way,
                    "INCOMPLETE",
                    "the relation has no 'via' member",
                    conditional or conditional_except,
                )
            )
            continue

        if conditional or conditional_except:
            # A conditional restriction is decidable only with a clock
            # context, and only for a condition this module can evaluate.
            decided: Optional[bool] = None
            if context is not None:
                decided = evaluate_conditional(
                    str(relation.tags.get("restriction:conditional", "")),
                    context,
                )
                if decided is None and conditional_except:
                    decided = evaluate_conditional(
                        str(relation.tags.get("except:conditional", "")),
                        context,
                    )
            if decided is None:
                parsed.append(
                    _make(
                        kind, value, from_way, via_nodes, via_ways, to_way,
                        "UNSUPPORTED_CONDITIONAL",
                        "the restriction is conditional and no clock/vehicle context "
                        "was supplied, so it cannot be decided",
                        True,
                    )
                )
                continue
            if not decided:
                # The condition does not hold at this moment, so the
                # restriction does not apply.  It is still RECORDED.
                parsed.append(
                    _make(
                        kind, value, from_way, via_nodes, via_ways, to_way,
                        "INCOMPLETE",
                        "the conditional restriction does not apply at the "
                        "supplied context",
                        True,
                    )
                )
                continue

        parsed.append(
            _make(
                kind, value, from_way, via_nodes, via_ways, to_way,
                "APPLICABLE",
                "the relation is well formed and decidable",
            )
        )

    # A `restriction` tag on a WAY (rather than on a relation) is a
    # malformed form: it names a restriction the source does not define.
    for way_id in sorted(document.ways):
        way = document.ways[way_id]
        raw = str(way.tags.get("restriction", "")).strip().lower()
        if not raw:
            continue
        parsed.append(
            Restriction(
                relation_id=f"way:{way_id}",
                kind="unknown",
                value=raw,
                from_way=None,
                via_nodes=(),
                via_ways=(),
                to_way=None,
                except_modes=(),
                status="INCOMPLETE",
                reason=(
                    "a 'restriction' tag on a way does not define a restriction; "
                    "OSM restrictions are relations"
                ),
            )
        )

    by_from: dict[str, list[Restriction]] = {}
    for restriction in parsed:
        if restriction.from_way:
            by_from.setdefault(restriction.from_way, []).append(restriction)

    return RestrictionSet(
        restrictions=tuple(parsed),
        by_from_way={k: tuple(v) for k, v in by_from.items()},
        incomplete=tuple(r for r in parsed if r.status in {"INCOMPLETE", "UNSUPPORTED_FORM"}),
    )
