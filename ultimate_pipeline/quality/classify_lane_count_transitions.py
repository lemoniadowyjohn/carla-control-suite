"""Evidence-based classification of the "unexplained" lane-count bucket.

``check_lane_count_changes.check_lane_count_changes`` (the companion module
this one wraps) only recognises one kind of evidence for a lane-count
change across a road link: BOTH linked endpoints carrying an explicit
``lane_count_source`` userData tag whose value starts with ``"osm:"``. Every
other changed boundary -- regardless of how ordinary or well-modelled it is
-- falls into a single ``UNEXPLAINED_CHANGE`` bucket. Because only a tiny
fraction of driving lanes in this pipeline's generated maps ever carry that
OSM provenance tag, "no provenance" and "evidence of corruption" are
currently indistinguishable in that bucket.

This module does NOT change what ``check_lane_count_changes`` measures, and
does NOT fabricate OSM provenance that is not present in the XODR. It adds a
second pass, driven purely by observable XODR topology and geometry, that
splits the ``UNEXPLAINED_CHANGE`` findings into finer categories:

- ``source_proven_lane_change``: one side (not both -- both would already be
  ``OSM_EXPLAINED_CHANGE`` upstream) carries genuine, unfabricated
  ``osm:``-prefixed provenance. Real evidence, just asymmetric.
- ``junction_transition``: the boundary is a road that is itself a junction
  connecting road (``road/@junction != "-1"``), verified two ways:
  - ``declared_connection``: the exact (incomingRoad, connectingRoad) pair
    is declared in a ``<junction><connection>`` element, AND the number of
    distinct ``laneLink/@to`` ids on that connection matches the connecting
    road's own driving-lane count at that edge (i.e. the declared routing
    topology actually accounts for the lane count observed). This is the
    strongest tier.
  - ``connector_adjacent``: one side is a junction connecting road that IS
    registered as a ``connectingRoad`` somewhere in the file (so it is a
    real, registered connector, not just a road with a stray ``junction``
    attribute), but this specific link is its *other* end (the
    connector-to-outgoing-road side), which OpenDRIVE's ``<connection>``
    schema does not separately declare.
- ``ramp_connector_transition``: neither side is a formal junction road, but
  one side is a short link road (heuristic length threshold), consistent
  with an un-registered ramp/connector segment.
- ``lanesection_local_transition``: the edge laneSection nearest the link
  boundary is short relative to the road, i.e. the lane-count change is
  actually modelled as a local laneSection taper zone tucked right up
  against the link, not an abrupt jump at the link itself.
- ``ordinary_merge`` / ``ordinary_split``: no structural explanation above
  applies, but the lane(s) present on only one side show real tapering
  geometry (their width collapses towards the boundary relative to their
  width elsewhere in the same laneSection), consistent with a genuine
  converging/diverging lane rather than an arbitrary jump.
- ``missing_provenance``: none of the above evidence exists, but the change
  is small (|delta| == 1) and both sides otherwise resolve cleanly -- this
  is the "would look ordinary except OSM tagging is sparse" bucket.
- ``suspicious_unexplained_discontinuity``: none of the above -- the
  genuine review set.
- ``unresolved_link``: a structural problem in the underlying road data
  itself (e.g. a linked road with no laneSection element at all) prevented
  classification.

All thresholds are named constants below, documented, and covered by the
synthetic fixtures in
``ultimate_pipeline/tests/unit/test_classify_lane_count_transitions.py``.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from ultimate_pipeline.quality.check_lane_count_changes import (
    _edge_lanes,
    _float,
    _osm_provenance,
    check_lane_count_changes,
)

# --- category identifiers -------------------------------------------------

SOURCE_PROVEN = "source_proven_lane_change"
JUNCTION_TRANSITION = "junction_transition"
RAMP_CONNECTOR_TRANSITION = "ramp_connector_transition"
LANESECTION_LOCAL_TRANSITION = "lanesection_local_transition"
ORDINARY_MERGE = "ordinary_merge"
ORDINARY_SPLIT = "ordinary_split"
MISSING_PROVENANCE = "missing_provenance"
SUSPICIOUS = "suspicious_unexplained_discontinuity"
UNRESOLVED_LINK = "unresolved_link"

ALL_CATEGORIES = (
    SOURCE_PROVEN,
    JUNCTION_TRANSITION,
    RAMP_CONNECTOR_TRANSITION,
    LANESECTION_LOCAL_TRANSITION,
    ORDINARY_MERGE,
    ORDINARY_SPLIT,
    MISSING_PROVENANCE,
    SUSPICIOUS,
    UNRESOLVED_LINK,
)

# --- tunable thresholds (named, documented, exercised by tests) ----------

#: A link road with length at or below this, outside any formal <junction>,
#: is treated as a candidate ramp/connector segment.
RAMP_MAX_LENGTH_M = 25.0

#: An edge laneSection (the one nearest the link boundary) with length at or
#: below this is treated as a local taper zone rather than a full-road
#: lane-count regime.
LANESECTION_LOCAL_MAX_LENGTH_M = 5.0

#: A lane counted as "extra" on the more-numerous side is treated as a real
#: taper (merge/split geometry) if its width at the link boundary is at
#: most this fraction of its own width at the opposite end of the same
#: laneSection.
TAPER_WIDTH_RATIO_MAX = 0.34

#: Small, plausible-looking lane-count deltas that lack any other evidence
#: are reported as missing-provenance rather than suspicious.
MISSING_PROVENANCE_MAX_DELTA = 1


def _road_length(road: ET.Element) -> float:
    return _float(road.get("length"))


def _lane_sections_sorted(road: ET.Element) -> list[ET.Element]:
    return sorted(
        road.findall("./lanes/laneSection"), key=lambda section: _float(section.get("s"))
    )


def _is_junction_road(road: ET.Element | None) -> bool:
    if road is None:
        return False
    junction = road.get("junction")
    return junction not in (None, "", "-1")


def _driving_lane_ids(road: ET.Element, at_start: bool) -> set[str]:
    return {str(lane.get("id")) for lane in _edge_lanes(road, at_start)}


def _width_segments(lane: ET.Element) -> list[tuple[float, float, float, float, float]]:
    segments = []
    for width in lane.findall("./width"):
        segments.append(
            (
                _float(width.get("sOffset")),
                _float(width.get("a")),
                _float(width.get("b")),
                _float(width.get("c")),
                _float(width.get("d")),
            )
        )
    return sorted(segments, key=lambda item: item[0])


def _eval_width(lane: ET.Element, local_s: float) -> float | None:
    segments = _width_segments(lane)
    if not segments:
        return None
    chosen = segments[0]
    for segment in segments:
        if segment[0] <= local_s:
            chosen = segment
        else:
            break
    s_offset, a, b, c, d = chosen
    ds = max(0.0, local_s - s_offset)
    return a + b * ds + c * ds ** 2 + d * ds ** 3


def _section_length(road: ET.Element, sections: list[ET.Element], index: int) -> float:
    section_s = _float(sections[index].get("s"))
    if index + 1 < len(sections):
        return max(0.0, _float(sections[index + 1].get("s")) - section_s)
    return max(0.0, _road_length(road) - section_s)


def _lane_by_id(section: ET.Element, lane_id: str) -> ET.Element | None:
    for lane in section.findall(".//lane"):
        if lane.get("type") == "driving" and str(lane.get("id")) == lane_id:
            return lane
    return None


def _taper_ratio(road: ET.Element, at_start: bool, lane_id: str) -> float | None:
    """Ratio of a lane's width at the link boundary to its width at the far
    end of the same laneSection. Small ratio == genuine taper."""
    sections = _lane_sections_sorted(road)
    if not sections:
        return None
    index = 0 if at_start else len(sections) - 1
    section = sections[index]
    lane = _lane_by_id(section, lane_id)
    if lane is None:
        return None
    length = _section_length(road, sections, index)
    boundary_local_s = 0.0 if at_start else length
    far_local_s = length if at_start else 0.0
    boundary_w = _eval_width(lane, boundary_local_s)
    far_w = _eval_width(lane, far_local_s)
    if boundary_w is None or far_w is None or far_w <= 1e-9:
        return None
    return max(0.0, boundary_w) / far_w


def _has_wellformed_lanes(road: ET.Element | None) -> bool:
    if road is None:
        return False
    return len(road.findall("./lanes/laneSection")) > 0


class _JunctionIndex:
    """Pre-parsed <junction> topology, built once per XODR document."""

    def __init__(self, root: ET.Element) -> None:
        self.declared: dict[tuple[str, str], ET.Element] = {}
        self.registered_connectors: set[str] = set()
        for junction in root.findall("./junction"):
            for connection in junction.findall("./connection"):
                incoming = str(connection.get("incomingRoad", ""))
                connecting = str(connection.get("connectingRoad", ""))
                if incoming and connecting:
                    self.declared[(incoming, connecting)] = connection
                    self.registered_connectors.add(connecting)

    def declared_connection(self, road_a: str, road_b: str) -> ET.Element | None:
        found = self.declared.get((road_a, road_b))
        if found is not None:
            return found
        return self.declared.get((road_b, road_a))

    def is_registered_connector(self, road_id: str) -> bool:
        return road_id in self.registered_connectors


def _connection_lane_count_consistent(
    connection: ET.Element, source: dict[str, Any], target: dict[str, Any]
) -> bool:
    connecting_id = connection.get("connectingRoad")
    to_ids = {link.get("to") for link in connection.findall("./laneLink")}
    if source["road_id"] == connecting_id:
        connecting_count = source["driving_lane_count"]
    elif target["road_id"] == connecting_id:
        connecting_count = target["driving_lane_count"]
    else:
        return False
    return len(to_ids) == connecting_count


def _classify_one(
    finding: dict[str, Any],
    roads: dict[str, ET.Element],
    junctions: _JunctionIndex,
) -> dict[str, Any]:
    source = finding["source"]
    target = finding["target"]
    source_road = roads.get(source["road_id"])
    target_road = roads.get(target["road_id"])

    if not _has_wellformed_lanes(source_road) or not _has_wellformed_lanes(target_road):
        return {"category": UNRESOLVED_LINK, "evidence": {"reason": "linked road has no laneSection data"}}

    source_full_osm = _osm_provenance(source)
    target_full_osm = _osm_provenance(target)
    if source_full_osm or target_full_osm:
        # Both-sides-full-provenance already leaves check_lane_count_changes
        # as OSM_EXPLAINED_CHANGE upstream, so reaching here means exactly
        # one side has real, unfabricated OSM provenance.
        return {
            "category": SOURCE_PROVEN,
            "evidence": {"proven_side": "source" if source_full_osm else "target"},
        }

    source_junction = _is_junction_road(source_road)
    target_junction = _is_junction_road(target_road)
    if source_junction or target_junction:
        connection = junctions.declared_connection(source["road_id"], target["road_id"])
        if connection is not None and _connection_lane_count_consistent(connection, source, target):
            return {
                "category": JUNCTION_TRANSITION,
                "evidence": {
                    "tier": "declared_connection",
                    "connection_id": connection.get("id"),
                    "incoming_road": connection.get("incomingRoad"),
                    "connecting_road": connection.get("connectingRoad"),
                },
            }
        for connector_id in (
            [source["road_id"], target["road_id"]]
            if source_junction and target_junction
            else [source["road_id"] if source_junction else target["road_id"]]
        ):
            if junctions.is_registered_connector(connector_id):
                return {
                    "category": JUNCTION_TRANSITION,
                    "evidence": {"tier": "connector_adjacent", "connector_road_id": connector_id},
                }
        # A road claims a junction id but is never used as a connectingRoad
        # anywhere in the file's <junction> topology -- that mismatch is
        # itself suspicious, not an explanation.

    source_len = _road_length(source_road)
    target_len = _road_length(target_road)
    if not source_junction and not target_junction:
        if source_len <= RAMP_MAX_LENGTH_M or target_len <= RAMP_MAX_LENGTH_M:
            short_side = "source" if source_len <= target_len else "target"
            return {
                "category": RAMP_CONNECTOR_TRANSITION,
                "evidence": {"short_side": short_side, "length_m": min(source_len, target_len)},
            }

    source_sections = _lane_sections_sorted(source_road)
    target_sections = _lane_sections_sorted(target_road)
    source_edge_len = (
        _section_length(source_road, source_sections, 0 if source["contact_point"] == "start" else len(source_sections) - 1)
        if source_sections
        else None
    )
    target_edge_len = (
        _section_length(target_road, target_sections, 0 if target["contact_point"] == "start" else len(target_sections) - 1)
        if target_sections
        else None
    )
    if (len(source_sections) > 1 and source_edge_len is not None and source_edge_len <= LANESECTION_LOCAL_MAX_LENGTH_M) or (
        len(target_sections) > 1 and target_edge_len is not None and target_edge_len <= LANESECTION_LOCAL_MAX_LENGTH_M
    ):
        return {
            "category": LANESECTION_LOCAL_TRANSITION,
            "evidence": {"source_edge_section_length_m": source_edge_len, "target_edge_section_length_m": target_edge_len},
        }

    before = source["driving_lane_count"]
    after = target["driving_lane_count"]
    delta = after - before
    if delta != 0:
        larger_side, larger_road, larger_at_start, larger_ids = (
            ("source", source_road, source["contact_point"] == "start", _driving_lane_ids(source_road, source["contact_point"] == "start"))
            if before > after
            else ("target", target_road, target["contact_point"] == "start", _driving_lane_ids(target_road, target["contact_point"] == "start"))
        )
        smaller_ids = (
            _driving_lane_ids(target_road, target["contact_point"] == "start")
            if larger_side == "source"
            else _driving_lane_ids(source_road, source["contact_point"] == "start")
        )
        extra_ids = larger_ids - smaller_ids
        if extra_ids and len(extra_ids) == abs(delta):
            ratios = [
                _taper_ratio(larger_road, larger_at_start, lane_id)
                for lane_id in extra_ids
            ]
            if ratios and all(r is not None and r <= TAPER_WIDTH_RATIO_MAX for r in ratios):
                category = ORDINARY_MERGE if before > after else ORDINARY_SPLIT
                return {
                    "category": category,
                    "evidence": {"tapering_lane_ids": sorted(extra_ids), "width_ratios": ratios},
                }

    if abs(delta) <= MISSING_PROVENANCE_MAX_DELTA:
        return {"category": MISSING_PROVENANCE, "evidence": {"delta": delta}}

    return {"category": SUSPICIOUS, "evidence": {"delta": delta}}


def classify_lane_count_transitions(xodr_path: str | Path) -> dict[str, Any]:
    """Classify every ``UNEXPLAINED_CHANGE`` finding from
    ``check_lane_count_changes`` using observable XODR topology/geometry.

    The raw ``check_lane_count_changes`` output -- including its
    ``unexplained_change`` count -- is returned verbatim under ``raw_check``
    so the original metric remains reproducible unchanged. This function
    never fabricates OSM provenance and never marks the whole bucket as
    either uniformly fine or uniformly suspicious without evidence.
    """

    raw = check_lane_count_changes(xodr_path)
    root = ET.parse(xodr_path).getroot()
    roads = {str(road.get("id")): road for road in root.findall("./road") if road.get("id")}
    junctions = _JunctionIndex(root)

    classified: list[dict[str, Any]] = []
    for finding in raw["findings"]:
        if finding["category"] != "UNEXPLAINED_CHANGE":
            continue
        result = _classify_one(finding, roads, junctions)
        classified.append(
            {
                "source": finding["source"],
                "target": finding["target"],
                "category": result["category"],
                "evidence": result["evidence"],
            }
        )

    classified.sort(
        key=lambda item: (
            item["category"],
            item["source"]["road_id"],
            item["source"]["contact_point"],
            item["target"]["road_id"],
            item["target"]["contact_point"],
        )
    )
    counts = Counter(item["category"] for item in classified)
    suspicious_review_set = [item for item in classified if item["category"] == SUSPICIOUS]

    return {
        "ok": True,
        "advisory": True,
        "input": str(xodr_path),
        "raw_check": raw,
        "classification_summary": {category: counts.get(category, 0) for category in ALL_CATEGORIES},
        "classified_unexplained_count": len(classified),
        "classified_findings": classified,
        "suspicious_review_set": suspicious_review_set,
        "thresholds": {
            "ramp_max_length_m": RAMP_MAX_LENGTH_M,
            "lanesection_local_max_length_m": LANESECTION_LOCAL_MAX_LENGTH_M,
            "taper_width_ratio_max": TAPER_WIDTH_RATIO_MAX,
            "missing_provenance_max_delta": MISSING_PROVENANCE_MAX_DELTA,
        },
        "claim_boundary": (
            "Advisory only. This is a topology/geometry-driven classification of "
            "check_lane_count_changes' UNEXPLAINED_CHANGE bucket. It does not repair "
            "lane links, does not fabricate OSM provenance, and a 'junction_transition' "
            "or 'ordinary_merge/split' classification is not a claim that the map is "
            "otherwise defect-free -- only that this specific lane-count change has a "
            "structural/geometric explanation independent of OSM tagging."
        ),
    }
