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
import os
import uuid
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

#: V104 review 4551582442 / 4551582504: the versioned per-road association
#: contract and the OSM source identity must reach the geometry consumer, not
#: just four loose keys.
ASSOCIATION_SCHEMA_KEY = "_osm_association_schema"
ASSOCIATION_STATE_KEY = "_osm_association_state"
SOURCE_SHA_KEY = "_osm_source_sha256"

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
    #: The source admits more than one candidate and none is authoritative.
    AMBIGUOUS = "ambiguous"
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
        # V104 review 4551582303: OSM's implicit one-way defaults.  A
        # ``highway=motorway`` / ``motorway_link`` is one-way unless tagged
        # otherwise, exactly like a roundabout.  Without this the lane total
        # of a motorway was split in half and a counterflow lane was
        # generated on a road that cannot carry contraflow traffic.
        highway = str(_tag(tags, "highway") or "").strip().lower()
        if highway in ("motorway", "motorway_link"):
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


def historical_split_counts(
    tags: Mapping[str, Any] | None,
) -> tuple[int, int, str, float]:
    """The pre-V103 lane assignment as ``(backward, forward, source, confidence)``.

    The historical implementation returned ``total // 2`` for the *backward*
    (left) carriageway and ``total - total // 2`` for the *forward* (right)
    carriageway.  V104 review 4551555409 requires that an odd lane total
    keeps exactly that assignment unless authoritative OSM evidence demands a
    correction, so this is the single definition of the historical split and
    every fallback path routes through it.
    """
    total = _parse_lane_count(_tag(tags, "lanes"))
    if total is not None:
        total = int(total)
        return total // 2, total - total // 2, "osm:lanes", 0.9
    return 1, 1, "fallback", 0.0


def resolve_directional_lane_counts(
    tags: Mapping[str, Any] | None,
    *,
    osm_direction: Optional[str] = None,
    orientation_required: bool = False,
) -> DirectionalLaneCounts:
    """Resolve the directional driving-lane counts for one road.

    Resolution order (first decisive rule wins):

    1. ``lanes:forward`` / ``lanes:backward`` present -> used directly.
       These are already directional and do not need ``oneway``.
       * Both present -> used as-is; a disagreeing ``lanes`` total is
         reported as :attr:`DirectionalState.CONFLICTING`.
       * One present and a ``lanes`` total present -> the missing side is
         resolved from the total when the arithmetic is consistent
         (V104 review 4551582330); otherwise the result is flagged
         ``incomplete`` rather than silently treating the missing tag as
         zero.
       * One present and no total -> the missing side is unknown; the result
         is flagged ``incomplete`` and is therefore never authoritative.
    2. Only ``lanes`` present, and ``oneway`` is decidable -> **all** lanes
       belong to the legal direction.  A one-way road therefore never gains
       a counterflow driving lane (the T01 fix).
    3. Only ``lanes`` present, and ``oneway`` is bidirectional -> the
       historical deterministic split (V104 review 4551555409).
    4. Only ``lanes`` present and ``oneway`` is undecidable -> the
       historical split is retained for geometry compatibility but the
       result is flagged ``unsupported`` so it is never presented as
       authoritative.
    5. No lane tags at all -> the one-lane-per-side fallback, placed in the
       legal direction when ``oneway`` is decidable (V104 review
       4551582316), flagged ``incomplete``.

    A conditional one-way restriction makes the permitted direction
    time-dependent, so a static ``oneway`` value combined with
    ``oneway:conditional`` is never reported as authoritative when the lane
    counts depend on it (V104 review 4551582276).

    The counts are then mapped from *OSM-way-relative* to *XODR-relative*
    using ``osm_direction``.  A reversed XODR road swaps the two sides.
    When the orientation is required but unknown, the resolution falls back
    to the orientation-independent historical split and is flagged
    ``incomplete`` -- OSM-way-relative counts must never be applied to an
    arbitrary XODR carriageway (V104 review 4551582252).
    """
    forward_tag = _parse_lane_count(_tag(tags, "lanes:forward"))
    backward_tag = _parse_lane_count(_tag(tags, "lanes:backward"))
    total_tag = _parse_lane_count(_tag(tags, "lanes"))
    oneway = parse_oneway(tags)
    conditional = _tag(tags, "oneway:conditional")
    reversible = _tag(tags, "reversible")

    notes: list[str] = []

    # A conditional restriction can change the permitted direction.  Without
    # a time/vehicle context the static plain ``oneway`` value is not a
    # static fact.
    conditional_conflict = bool(conditional) and oneway in (
        OnewayState.FORWARD,
        OnewayState.BACKWARD,
        OnewayState.BIDIRECTIONAL,
    )

    state = DirectionalState.OK
    source = ""
    confidence = 0.0

    if forward_tag is not None or backward_tag is not None:
        source = "osm:lanes:forward+backward"
        confidence = 1.0
        if forward_tag is not None and backward_tag is not None:
            forward = int(forward_tag)
            backward = int(backward_tag)
            if total_tag is not None and int(total_tag) != forward + backward:
                state = DirectionalState.CONFLICTING
                notes.append(f"lanes_total_mismatch:{total_tag}!={forward + backward}")
        elif total_tag is not None:
            # One directional tag is missing; the total resolves it when the
            # arithmetic is consistent.
            known = int(forward_tag if forward_tag is not None else backward_tag)
            missing = int(total_tag) - known
            if missing >= 0:
                forward = int(forward_tag) if forward_tag is not None else missing
                backward = int(backward_tag) if backward_tag is not None else missing
                notes.append(f"partial_directional_counts_resolved_from_total:{missing}")
            else:
                forward = int(forward_tag or 0)
                backward = int(backward_tag or 0)
                state = DirectionalState.CONFLICTING
                notes.append(f"lanes_total_mismatch:{total_tag}!={forward + backward}")
        else:
            # The missing side cannot be resolved from the source.  It is
            # NOT silently treated as zero.
            forward = int(forward_tag or 0)
            backward = int(backward_tag or 0)
            state = DirectionalState.INCOMPLETE
            notes.append("partial_directional_counts_unknown_side")
    elif total_tag is not None:
        total = int(total_tag)
        # Historical assignment (V104 review 4551555409): the backward
        # (left) carriageway receives total // 2, the forward (right)
        # carriageway the remainder.
        split_forward = total - total // 2
        split_backward = total // 2
        if oneway is OnewayState.FORWARD:
            forward, backward = total, 0
            source = "osm:oneway+lanes"
            confidence = 1.0
        elif oneway is OnewayState.BACKWARD:
            forward, backward = 0, total
            source = "osm:oneway+lanes"
            confidence = 1.0
        elif oneway is OnewayState.BIDIRECTIONAL:
            forward, backward = split_forward, split_backward
            source = "osm:lanes"
            confidence = 0.9
        else:
            forward, backward = split_forward, split_backward
            source = "osm:lanes"
            confidence = 0.5
            state = DirectionalState.UNSUPPORTED
            if reversible or oneway is OnewayState.REVERSIBLE:
                notes.append("reversible_oneway")
            if conditional:
                notes.append("oneway_conditional")
            notes.append("oneway_unknown")
        if conditional_conflict and state is DirectionalState.OK:
            # The conditional rule can change the permitted direction, so the
            # static lane counts are not an authoritative fact.
            state = DirectionalState.UNSUPPORTED
            notes.append("oneway_conditional_conflicts_with_static_oneway")
    else:
        # No lane-count evidence at all.  A decidable oneway still decides
        # where the single fallback lane goes, so a one-way road does not
        # gain a counterflow lane.
        if oneway is OnewayState.FORWARD:
            forward, backward = 1, 0
        elif oneway is OnewayState.BACKWARD:
            forward, backward = 0, 1
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
        if orientation_required:
            # A correspondence association exists but could not orient the
            # road, so the OSM-way-relative counts cannot be attributed to
            # an XODR carriageway.  Fall back to the orientation-independent
            # historical split and mark the resolution non-authoritative.
            backward, forward, source, confidence = historical_split_counts(tags)
            if state is DirectionalState.OK:
                state = DirectionalState.INCOMPLETE
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
    def has_usable_confidence(self) -> bool:
        """True when the match carries usable confidence evidence."""
        try:
            return float(self.confidence) > 0.0
        except (TypeError, ValueError):
            return False

    @property
    def is_trustworthy(self) -> bool:
        """True when class, confidence and orientation are all usable.

        V104 review 4551582421: a match with zero (or unusable) confidence
        carries no confidence evidence at all and must not be trusted.
        """
        return (
            self.match_class in {"EXACT", "HIGH"}
            and self.is_oriented
            and self.has_usable_confidence
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
    match_class_counts: Optional[Mapping[str, Any]] = None,
    xodr_road_count: Optional[int] = None,
    minimum_authoritative_rate_percent: Optional[float] = None,
) -> dict[str, Any]:
    """Summarise directional coverage over the matched roads (registry T06).

    ``associations`` maps an XODR road id to the per-road metadata mapping
    produced by :func:`ultimate_pipeline.pipeline_stages.stage_07_lanes.
    _build_structural_osm_metadata` (including the reserved directional
    keys).

    The report never returns ``PASS`` for release-required directionality
    when the OSM source is missing or when no road matched: both are
    ``BLOCKED_INPUT``.

    **Two populations, never mixed (V104 P2).**  The ``counts`` block mixes
    two *different* denominators:

    * ``matched`` / ``authoritative`` / ``forward`` / ``reversed`` ... count
      **XODR roads** (the association map is keyed by XODR road id);
    * ``correspondence_exact`` / ``correspondence_high`` /
      ``ambiguous_correspondence`` / ``unmatched_correspondence`` count
      **OSM ways** (the ``match_class_counts`` population).

    Reporting "44 of 3057 roads matched" divides an XODR-road numerator by
    an OSM-way denominator and is not a rate at all.  Every rate in this
    report therefore states its denominator explicitly, and the
    ``population`` block names both populations.

    **The ``status`` verdict is the contract verdict, not an adequacy
    verdict (V104 P2).**  Per the frozen V103-O1 contract, ``PASS`` means
    "release-required directional evidence exists and is authoritative for at
    least one road".  It does *not* mean "the coverage is adequate" -- no
    minimum was declared, so no adequacy judgement can be made.  The
    adequacy judgement is reported separately in ``coverage_qualification``,
    whose status is ``UNDECLARED_THRESHOLD`` until a caller declares a
    minimum via ``minimum_authoritative_rate_percent``.  A report that says
    ``PASS`` while its coverage is 0.13% is therefore no longer possible to
    read as "coverage is adequate".
    """
    matched = 0
    reversed_ = 0
    ambiguous = 0
    conflicting = 0
    not_assessable = 0
    fallback = 0
    forward = 0
    authoritative = 0

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
        road_ambiguous = bool(match_class) and match_class not in {"EXACT", "HIGH"}
        if road_ambiguous:
            ambiguous += 1

        resolved = resolve_directional_lane_counts(
            meta, osm_direction=orientation if orientation != ORIENTATION_UNKNOWN else None
        )
        road_conflicting = resolved.state == DirectionalState.CONFLICTING.value
        if road_conflicting:
            conflicting += 1
        if resolved.source == "fallback":
            fallback += 1

        # V104 review 4551555419 / 4551582396 / 4551582407: a road is
        # authoritative for directionality only when
        #   * its match class is explicitly EXACT/HIGH (an absent match class
        #     is NOT evidence of an authoritative match),
        #   * its orientation is known,
        #   * its confidence is usable,
        #   * and the lane resolution itself is authoritative (an
        #     ``unsupported`` or ``fallback`` resolution is not).
        match_class_ok = match_class in {"EXACT", "HIGH"}
        try:
            confidence = float(meta.get(MATCH_CONFIDENCE_KEY))
        except (TypeError, ValueError):
            confidence = 0.0
        if (
            match_class_ok
            and not road_ambiguous
            and orientation != ORIENTATION_UNKNOWN
            and confidence > 0.0
            and not road_conflicting
            and resolved.is_authoritative
        ):
            authoritative += 1

    if not source_available:
        status = "BLOCKED_INPUT"
    elif matched == 0:
        status = "BLOCKED_INPUT"
    elif authoritative == 0 and release_required:
        # Nothing matched authoritatively: ambiguous, conflicting or
        # not-assessable roads are not a release-eligible directionality
        # result.
        status = "INCOMPLETE"
    else:
        status = "PASS"

    # V104 review 4551582370: the ambiguous / unmatched correspondence
    # population is reported here so it is not lost when the stage filters
    # the association map down to EXACT/HIGH.
    class_counts = dict(match_class_counts or {})

    # ------------------------------------------------------------------
    # V104 P2: state the populations, then measure the rates against the
    # population each numerator actually belongs to.
    # ------------------------------------------------------------------
    # The OSM-way population is the sum of the correspondence match classes.
    source_way_count = sum(
        int(class_counts.get(key, 0) or 0)
        for key in ("EXACT", "HIGH", "AMBIGUOUS", "UNMATCHED")
    )
    # The XODR-road population is the number of roads in the audited map.
    # It is supplied by the caller; when it is unknown the road-level rates
    # are reported as None rather than computed against a wrong denominator.
    road_population = int(xodr_road_count) if xodr_road_count else 0

    def _rate(numerator: int, denominator: int) -> Optional[float]:
        if not denominator:
            return None
        return round(100.0 * numerator / denominator, 4)

    # Road-level rates: numerator and denominator are both XODR roads.
    matched_road_rate = _rate(matched, road_population)
    authoritative_road_rate = _rate(authoritative, road_population)
    # Way-level rate: numerator and denominator are both OSM ways.
    matched_way_count = int(class_counts.get("EXACT", 0) or 0) + int(
        class_counts.get("HIGH", 0) or 0
    )
    matched_way_rate = _rate(matched_way_count, source_way_count)

    # ------------------------------------------------------------------
    # V104 P2: the adequacy verdict is separate from the contract verdict.
    # ------------------------------------------------------------------
    if minimum_authoritative_rate_percent is None:
        qualification_status = "UNDECLARED_THRESHOLD"
        qualification_reason = "no_declared_minimum_authoritative_rate"
    elif authoritative_road_rate is None:
        qualification_status = "UNDECLARED_THRESHOLD"
        qualification_reason = "no_declared_minimum_authoritative_rate"
    elif authoritative_road_rate < float(minimum_authoritative_rate_percent):
        qualification_status = "BELOW_MINIMUM"
        qualification_reason = (
            f"authoritative_rate_below_minimum:"
            f"{authoritative_road_rate:.4f}%<"
            f"{float(minimum_authoritative_rate_percent):.4f}%"
        )
    else:
        qualification_status = "MEETS_MINIMUM"
        qualification_reason = ""

    return {
        "schema": "osm_directional_coverage/v1",
        "contract_version": OSM_DIRECTION_CONTRACT_VERSION,
        "status": status,
        "reason": reason or ("" if status == "PASS" else "no_authoritative_directional_coverage"),
        "release_required": bool(release_required),
        "source_sha256": source_sha256,
        # V104 P2: the two populations, named and counted, so no reader can
        # divide a road numerator by a way denominator.
        "population": {
            "xodr_road_count": road_population or None,
            "osm_way_count": source_way_count or None,
            "xodr_road_count_note": (
                "denominator of matched_road_rate_percent and "
                "authoritative_road_rate_percent"
            ),
            "osm_way_count_note": (
                "denominator of matched_way_rate_percent; NOT a road denominator"
            ),
        },
        "rates": {
            "matched_road_rate_percent": matched_road_rate,
            "authoritative_road_rate_percent": authoritative_road_rate,
            "matched_way_rate_percent": matched_way_rate,
            "matched_road_count": matched,
            "authoritative_road_count": authoritative,
            "matched_way_count": matched_way_count,
        },
        "coverage_qualification": {
            "status": qualification_status,
            "reason": qualification_reason,
            "minimum_authoritative_rate_percent": (
                None
                if minimum_authoritative_rate_percent is None
                else float(minimum_authoritative_rate_percent)
            ),
            "note": (
                "the coverage status above is the CONTRACT verdict "
                "(directional evidence exists and is authoritative for at "
                "least one road). This block is the ADEQUACY verdict; it is "
                "UNDECLARED_THRESHOLD until a minimum authoritative rate is "
                "declared, so a PASS here must not be read as 'the coverage "
                "is adequate'."
            ),
        },
        "counts": {
            "matched": matched,
            "forward": forward,
            "reversed": reversed_,
            "ambiguous": ambiguous,
            "conflicting": conflicting,
            "not_assessable": not_assessable,
            "fallback": fallback,
            "authoritative": authoritative,
            "ambiguous_correspondence": int(class_counts.get("AMBIGUOUS", 0)),
            "unmatched_correspondence": int(class_counts.get("UNMATCHED", 0)),
            "correspondence_exact": int(class_counts.get("EXACT", 0)),
            "correspondence_high": int(class_counts.get("HIGH", 0)),
        },
    }


def _atomic_write_json(path: "os.PathLike[str] | str", payload: Mapping[str, Any]) -> str:
    """Write JSON atomically: unique temp file in the destination directory,
    fsync, then ``os.replace``.

    V104 review 4551582458: writing directly to the destination lets an
    interrupted or concurrent write leave a truncated artifact that a later
    reader cannot load.
    """
    import tempfile

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, default=str, ensure_ascii=True)
    if not text.endswith("\n"):
        text += "\n"
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp), str(target))
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return str(target)


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
    # V104 review 4551582458: write to a unique temporary file in the
    # destination directory and atomically replace the destination, so an
    # interrupted or concurrent write can never leave a truncated artifact.
    _atomic_write_json(target, payload)
    return str(target)
