#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V103-O1 — OSM way direction, oneway semantics and directional lane counts.

Why this module exists
----------------------
``driving_lane_counts`` (in :mod:`ultimate_pipeline.enrichment.lane_width_policy`)
used to derive the forward/backward driving-lane split **without ever looking
at the OSM ``oneway`` tag**.  A one-way road carrying ``lanes=2`` was split
``total // 2`` in each direction, which invented a counterflow driving lane
that does not exist on the map (registry issue **T01**).

Separately, :func:`ultimate_pipeline.pipeline_stages.stage_07_lanes.
_build_structural_osm_metadata` kept only the raw OSM *tag* sub-dictionary of
each correspondence association and dropped ``osm_direction``.  With the
orientation gone, OSM's ``turn:lanes:forward`` was applied to the XODR
*forward* carriageway even when the XODR reference line runs opposite to the
OSM way (registry issue **T02**).

This module is the single, versioned home for both facts:

* :func:`parse_oneway` — the OSM ``oneway`` grammar, including the implicit
  one-way default of ``junction=roundabout`` and the explicitly
  undecidable ``oneway:conditional`` / ``reversible`` cases.
* :func:`resolve_directional_lane_counts` — the authoritative directional
  lane-count resolution, mapped onto the XODR reference line.
* :class:`RoadOSMDirectionalAssociation` — the versioned, per-road
  correspondence record that carries the orientation from the association
  builder into the lane geometry stage.
* :func:`directional_coverage_report` — the coverage/summary contract
  (registry issue **T06**): missing OSM source is ``BLOCKED_INPUT`` and zero
  matched roads is never a release-eligible ``PASS``.

Design rules
------------
* **OSM way orientation is not driving legality.**  ``oneway`` describes the
  direction traffic may use; ``osm_direction`` describes how the OSM way's
  node order relates to the XODR reference line.  The two are combined
  explicitly, never conflated.
* **Never invent bidirectional lanes.**  When the source cannot decide
  (conditional/reversible oneway, unknown oneway, conflicting counts) the
  resolution is *flagged* (``state``) rather than silently presented as
  authoritative.  Geometry is not rewritten; the ambiguity is recorded.
* **A ``oneway`` fact only decides the split when it is decidable.**
  ``oneway=conditional`` and ``reversible`` are explicitly undecidable
  without a time/vehicle context.
* **Vehicle-specific oneway variants never change the *driving* lane
  count.**  ``oneway:bicycle=no`` describes bicycle contraflow; it must not
  be read as ``oneway=no`` for motor traffic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Optional

__all__ = [
    "OSM_DIRECTION_CONTRACT_VERSION",
    "DIRECTION_KEY",
    "OSM_WAY_ID_KEY",
    "MATCH_CLASS_KEY",
    "MATCH_CONFIDENCE_KEY",
    "OnewayState",
    "DirectionalState",
    "DirectionalLaneCounts",
    "RoadOSMDirectionalAssociation",
    "parse_oneway",
    "resolve_directional_lane_counts",
    "build_directional_association",
    "directional_coverage_report",
    "write_direction_contract",
]


#: Version of the OSM<->XODR directional correspondence contract.
OSM_DIRECTION_CONTRACT_VERSION = "osm_xodr_direction/v1"

#: Reserved metadata keys that carry the directional association through the
#: flat per-road metadata mapping used by the lane stage.  The leading
#: underscore keeps them outside the OSM tag namespace so no real OSM tag can
#: collide with them.
DIRECTION_KEY = "_osm_direction"
OSM_WAY_ID_KEY = "_osm_way_id"
MATCH_CLASS_KEY = "_osm_match_class"
MATCH_CONFIDENCE_KEY = "_osm_match_confidence"

#: Values of ``osm_direction`` produced by
#: :func:`ultimate_pipeline.enrichment.osm_xodr_correspondence._osm_direction`.
ORIENTATION_FORWARD = "forward"
ORIENTATION_REVERSE = "reverse"
ORIENTATION_UNKNOWN = "unknown"


class OnewayState(str, Enum):
    """Static interpretation of the OSM ``oneway`` tag."""

    #: Traffic may only use the OSM way's node order.
    FORWARD = "forward"
    #: Traffic may only use the reverse of the OSM way's node order.
    BACKWARD = "backward"
    #: Traffic may use both directions.
    BIDIRECTIONAL = "bidirectional"
    #: Direction depends on time — not statically decidable.
    REVERSIBLE = "reversible"
    #: No usable ``oneway`` fact.
    UNKNOWN = "unknown"


class DirectionalState(str, Enum):
    """Quality of a directional lane-count resolution."""

    OK = "ok"
    #: The source disagrees with itself (e.g. ``lanes`` vs directional tags).
    CONFLICTING = "conflicting"
    #: The source cannot decide statically (conditional/reversible oneway).
    UNSUPPORTED = "unsupported"
    #: No usable lane-count source at all.
    INCOMPLETE = "incomplete"


_ONEWAY_FORWARD = {"yes", "true", "1"}
_ONEWAY_BACKWARD = {"-1", "reverse"}
_ONEWAY_BIDIRECTIONAL = {"no", "false", "0"}


def _tag(tags: Mapping[str, Any] | None, key: str) -> Optional[str]:
    """Read a tag from a mapping, case-insensitively, stripped."""
    if not tags:
        return None
    if key in tags:
        raw = tags[key]
    else:
        raw = None
        wanted = key.strip().lower()
        for candidate, value in tags.items():
            if str(candidate).strip().lower() == wanted:
                raw = value
                break
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _parse_lane_count(raw: Any) -> Optional[int]:
    """Parse an OSM lane-count value.

    Delegates to the production parser so there is exactly one definition of
    "how many lanes does this tag mean".  The import is deferred to call time
    to keep this module free of a circular import.
    """
    from ultimate_pipeline.enrichment.lane_width_policy import parse_lane_count

    return parse_lane_count(raw)


def parse_oneway(tags: Mapping[str, Any] | None) -> OnewayState:
    """Interpret the OSM ``oneway`` tag.

    * ``yes`` / ``true`` / ``1`` -> :attr:`OnewayState.FORWARD`
    * ``-1`` / ``reverse`` -> :attr:`OnewayState.BACKWARD`
    * ``no`` / ``false`` / ``0`` -> :attr:`OnewayState.BIDIRECTIONAL`
    * ``reversible`` -> :attr:`OnewayState.REVERSIBLE` (time dependent)
    * absent, but ``junction=roundabout`` -> :attr:`OnewayState.FORWARD`
      (OSM's implicit one-way default for roundabouts)
    * anything else -> :attr:`OnewayState.UNKNOWN`

    A conditional oneway (``oneway:conditional``) never yields a decidable
    state on its own; if a plain ``oneway`` is also present it applies
    outside the conditional windows and is returned as-is.
    """
    raw = _tag(tags, "oneway")
    if raw is None:
        junction = (_tag(tags, "junction") or "").strip().lower()
        if junction == "roundabout":
            return OnewayState.FORWARD
        return OnewayState.UNKNOWN

    value = raw.strip().lower()
    if value in _ONEWAY_FORWARD:
        return OnewayState.FORWARD
    if value in _ONEWAY_BACKWARD:
        return OnewayState.BACKWARD
    if value in _ONEWAY_BIDIRECTIONAL:
        return OnewayState.BIDIRECTIONAL
    if value == "reversible":
        return OnewayState.REVERSIBLE
    return OnewayState.UNKNOWN


@dataclass(frozen=True)
class DirectionalLaneCounts:
    """Resolved directional driving-lane counts on the XODR reference line.

    ``forward`` counts lanes whose traffic runs along increasing XODR ``s``
    (the OpenDRIVE "right" carriageway, negative lane ids).  ``backward``
    counts lanes whose traffic runs against increasing ``s`` (the "left"
    carriageway, positive lane ids).
    """

    forward: int
    backward: int
    source: str
    confidence: float
    state: str = DirectionalState.OK.value
    oneway: str = OnewayState.UNKNOWN.value
    orientation: str = ORIENTATION_UNKNOWN
    notes: tuple[str, ...] = ()

    @property
    def total(self) -> int:
        return int(self.forward) + int(self.backward)

    @property
    def is_authoritative(self) -> bool:
        """True when the resolution is backed by a decidable OSM fact."""
        return self.state == DirectionalState.OK.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "forward": int(self.forward),
            "backward": int(self.backward),
            "total": self.total,
            "source": self.source,
            "confidence": float(self.confidence),
            "state": self.state,
            "oneway": self.oneway,
            "orientation": self.orientation,
            "notes": list(self.notes),
        }


def resolve_directional_lane_counts(
    tags: Mapping[str, Any] | None,
    *,
    osm_direction: Optional[str] = None,
) -> DirectionalLaneCounts:
    """Resolve the directional driving-lane counts for one road.

    Resolution order (first decisive rule wins):

    1. ``lanes:forward`` / ``lanes:backward`` present -> used directly.
       These are already directional and do not need ``oneway``.  A
       disagreeing ``lanes`` total is reported as
       :attr:`DirectionalState.CONFLICTING` but the directional tags win.
    2. Only ``lanes`` present, and ``oneway`` is decidable -> **all** lanes
       belong to the legal direction.  A one-way road therefore never gains
       a counterflow driving lane (the T01 fix).
    3. Only ``lanes`` present, and ``oneway`` is bidirectional -> the
       historical deterministic split.
    4. Only ``lanes`` present and ``oneway`` is undecidable -> the
       historical split is retained for geometry compatibility but the
       result is flagged ``unsupported`` / lower confidence so it is never
       presented as authoritative.
    5. No lane tags at all -> the historical one-lane-per-side fallback,
       flagged ``incomplete``.

    The counts are then mapped from *OSM-way-relative* to
    *XODR-relative* using ``osm_direction``.  A reversed XODR road swaps
    the two sides.
    """
    forward_tag = _parse_lane_count(_tag(tags, "lanes:forward"))
    backward_tag = _parse_lane_count(_tag(tags, "lanes:backward"))
    total_tag = _parse_lane_count(_tag(tags, "lanes"))
    oneway = parse_oneway(tags)
    conditional = _tag(tags, "oneway:conditional")
    reversible = _tag(tags, "reversible")

    notes: list[str] = []

    if forward_tag is not None or backward_tag is not None:
        forward = int(forward_tag or 0)
        backward = int(backward_tag or 0)
        source = "osm:lanes:forward+backward"
        confidence = 1.0
        state = DirectionalState.OK
        if total_tag is not None and int(total_tag) != forward + backward:
            state = DirectionalState.CONFLICTING
            notes.append(
                f"lanes_total_mismatch:{total_tag}!={forward + backward}"
            )
    elif total_tag is not None:
        total = int(total_tag)
        if oneway is OnewayState.FORWARD:
            forward, backward = total, 0
            source = "osm:oneway+lanes"
            confidence = 1.0
            state = DirectionalState.OK
        elif oneway is OnewayState.BACKWARD:
            forward, backward = 0, total
            source = "osm:oneway+lanes"
            confidence = 1.0
            state = DirectionalState.OK
        elif oneway is OnewayState.BIDIRECTIONAL:
            forward = total // 2
            backward = total - total // 2
            source = "osm:lanes"
            confidence = 0.9
            state = DirectionalState.OK
        else:
            # Undecidable direction: keep the historical split so valid
            # geometry is not destroyed, but never present it as proven.
            forward = total // 2
            backward = total - total // 2
            source = "osm:lanes"
            confidence = 0.5
            state = DirectionalState.UNSUPPORTED
            if reversible:
                notes.append("reversible_oneway")
            if conditional:
                notes.append("oneway_conditional")
            if oneway is OnewayState.UNKNOWN:
                notes.append("oneway_unknown")
    else:
        forward, backward = 1, 1
        source = "fallback"
        confidence = 0.0
        state = DirectionalState.INCOMPLETE
        notes.append("no_lane_tags")

    # ``lanes:both_ways`` is NOT part of ``lanes`` in OSM and must never be
    # added to either direction (it is a shared/turn lane, e.g. a central
    # turn pocket).
    both_ways = _parse_lane_count(_tag(tags, "lanes:both_ways"))
    if both_ways:
        notes.append(f"lanes:both_ways={both_ways}_excluded")

    # Map OSM-way-relative counts onto the XODR reference line.
    orientation = (osm_direction or "").strip().lower()
    if orientation == ORIENTATION_REVERSE:
        forward, backward = backward, forward
        orientation = ORIENTATION_REVERSE
    elif orientation == ORIENTATION_FORWARD:
        orientation = ORIENTATION_FORWARD
    else:
        orientation = ORIENTATION_UNKNOWN
        if source != "fallback":
            notes.append("orientation_unknown")

    return DirectionalLaneCounts(
        forward=forward,
        backward=backward,
        source=source,
        confidence=confidence,
        state=state.value if isinstance(state, DirectionalState) else str(state),
        oneway=oneway.value,
        orientation=orientation,
        notes=tuple(notes),
    )


@dataclass(frozen=True)
class RoadOSMDirectionalAssociation:
    """Versioned, per-road record of an OSM<->XODR directional correspondence.

    This is the contract handed from the correspondence builder to the lane
    geometry stage.  It carries everything a consumer needs to decide
    whether the directional facts may be trusted, and it represents the
    *unknown* and *ambiguous* states explicitly instead of defaulting them
    to "aligned".
    """

    schema: str = OSM_DIRECTION_CONTRACT_VERSION
    xodr_road_id: str = ""
    osm_way_id: str = ""
    osm_direction: str = ORIENTATION_UNKNOWN
    match_class: str = "UNMATCHED"
    confidence: float = 0.0
    source_sha256: str = ""
    span: tuple[Optional[float], Optional[float]] = (None, None)
    contact_points: tuple[str, str] = ("unknown", "unknown")
    tags: Mapping[str, Any] = field(default_factory=dict)
    state: str = DirectionalState.INCOMPLETE.value
    notes: tuple[str, ...] = ()

    @property
    def is_oriented(self) -> bool:
        """True when the OSM way orientation relative to XODR is known."""
        return self.osm_direction in (ORIENTATION_FORWARD, ORIENTATION_REVERSE)

    @property
    def is_trustworthy(self) -> bool:
        """True when class, confidence and orientation are all usable."""
        return (
            self.match_class in {"EXACT", "HIGH"}
            and self.is_oriented
            and self.state == DirectionalState.OK.value
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "xodr_road_id": self.xodr_road_id,
            "osm_way_id": self.osm_way_id,
            "osm_direction": self.osm_direction,
            "match_class": self.match_class,
            "confidence": float(self.confidence),
            "source_sha256": self.source_sha256,
            "span": list(self.span),
            "contact_points": list(self.contact_points),
            "tags": dict(self.tags),
            "state": self.state,
            "notes": list(self.notes),
        }


def build_directional_association(
    *,
    xodr_road_id: str,
    osm_way_id: str,
    osm_direction: Optional[str],
    match_class: str,
    confidence: float,
    source_sha256: str = "",
    span: tuple[Optional[float], Optional[float]] = (None, None),
    contact_points: tuple[str, str] = ("unknown", "unknown"),
    tags: Optional[Mapping[str, Any]] = None,
    notes: tuple[str, ...] = (),
) -> RoadOSMDirectionalAssociation:
    """Build a :class:`RoadOSMDirectionalAssociation` with an explicit state."""
    orientation = (osm_direction or "").strip().lower()
    if orientation not in (ORIENTATION_FORWARD, ORIENTATION_REVERSE):
        orientation = ORIENTATION_UNKNOWN

    state = DirectionalState.OK
    extra = list(notes)
    if match_class not in {"EXACT", "HIGH"}:
        state = DirectionalState.AMBIGUOUS
        extra.append("match_class_not_authoritative")
    if orientation == ORIENTATION_UNKNOWN:
        state = (
            DirectionalState.INCOMPLETE
            if state is DirectionalState.OK
            else state
        )
        extra.append("orientation_unknown")

    return RoadOSMDirectionalAssociation(
        xodr_road_id=str(xodr_road_id),
        osm_way_id=str(osm_way_id),
        osm_direction=orientation,
        match_class=str(match_class),
        confidence=float(confidence),
        source_sha256=str(source_sha256 or ""),
        span=(span[0], span[1]) if len(span) == 2 else (None, None),
        contact_points=(
            str(contact_points[0]),
            str(contact_points[1]),
        )
        if len(contact_points) == 2
        else ("unknown", "unknown"),
        tags=dict(tags or {}),
        state=state.value,
        notes=tuple(extra),
    )


def directional_coverage_report(
    associations: Mapping[str, Mapping[str, Any]],
    *,
    source_available: bool,
    source_sha256: str = "",
    reason: str = "",
    release_required: bool = True,
) -> dict[str, Any]:
    """Summarise directional coverage over the matched roads (registry T06).

    ``associations`` maps an XODR road id to the per-road metadata mapping
    produced by :func:`ultimate_pipeline.pipeline_stages.stage_07_lanes.
    _build_structural_osm_metadata` (including the reserved directional
    keys).

    The report never returns ``PASS`` for release-required directionality
    when the OSM source is missing or when no road matched: both are
    ``BLOCKED_INPUT``.
    """
    matched = 0
    reversed_ = 0
    ambiguous = 0
    conflicting = 0
    not_assessable = 0
    fallback = 0
    forward = 0

    for road_id, meta in sorted((associations or {}).items()):
        if not isinstance(meta, Mapping):
            continue
        matched += 1
        orientation = str(meta.get(DIRECTION_KEY) or ORIENTATION_UNKNOWN).strip().lower()
        if orientation == ORIENTATION_REVERSE:
            reversed_ += 1
        elif orientation == ORIENTATION_FORWARD:
            forward += 1
        else:
            not_assessable += 1

        match_class = str(meta.get(MATCH_CLASS_KEY) or "").strip().upper()
        if match_class and match_class not in {"EXACT", "HIGH"}:
            ambiguous += 1

        resolved = resolve_directional_lane_counts(
            meta, osm_direction=orientation if orientation != ORIENTATION_UNKNOWN else None
        )
        if resolved.state == DirectionalState.CONFLICTING.value:
            conflicting += 1
        if resolved.source == "fallback":
            fallback += 1

    if not source_available:
        status = "BLOCKED_INPUT"
    elif matched == 0:
        status = "BLOCKED_INPUT"
    elif not_assessable == matched and release_required:
        status = "INCOMPLETE"
    else:
        status = "PASS"

    return {
        "schema": "osm_directional_coverage/v1",
        "contract_version": OSM_DIRECTION_CONTRACT_VERSION,
        "status": status,
        "reason": reason or ("" if status == "PASS" else "no_authoritative_directional_coverage"),
        "release_required": bool(release_required),
        "source_sha256": source_sha256,
        "counts": {
            "matched": matched,
            "forward": forward,
            "reversed": reversed_,
            "ambiguous": ambiguous,
            "conflicting": conflicting,
            "not_assessable": not_assessable,
            "fallback": fallback,
        },
    }


def write_direction_contract(
    out_path: str | os.PathLike[str],
    *,
    coverage: Optional[Mapping[str, Any]] = None,
) -> str:
    """Write the ``OSM_XODR_DIRECTION_CONTRACT.json`` deliverable."""
    payload: dict[str, Any] = {
        "schema": "osm_xodr_direction_contract/v1",
        "contract_version": OSM_DIRECTION_CONTRACT_VERSION,
        "oneway_states": [state.value for state in OnewayState],
        "directional_states": [state.value for state in DirectionalState],
        "reserved_metadata_keys": {
            "direction": DIRECTION_KEY,
            "osm_way_id": OSM_WAY_ID_KEY,
            "match_class": MATCH_CLASS_KEY,
            "match_confidence": MATCH_CONFIDENCE_KEY,
        },
        "resolution_order": [
            "lanes:forward/lanes:backward (authoritative, directional)",
            "oneway decidable + lanes total (all lanes in the legal direction)",
            "oneway bidirectional + lanes total (deterministic split)",
            "oneway undecidable + lanes total (split retained, flagged unsupported)",
            "no lane tags (one-per-side fallback, flagged incomplete)",
        ],
        "orientation_mapping": {
            "forward": "osm forward == xodr forward (increasing s)",
            "reverse": "osm forward == xodr backward (decreasing s)",
            "unknown": "no swap; recorded as not-assessable",
        },
        "coverage": dict(coverage) if coverage else None,
    }
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return str(target)
