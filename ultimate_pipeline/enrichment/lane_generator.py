#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
FINAL LaneGenerator (production-stable)
--------------------------------------
This is the ONLY LaneGenerator the pipeline must use.

Key guarantees:
 - Does NOT delete valid laneSections unless they contain 0 lanes.
 - Creates correct left/center/right structures.
 - Produces CARLA-safe lane definitions.
 - Does not conflict with continuity repair or geometry smoothing.
 - Fully deterministic and SANITY-CHECKED.
"""

from __future__ import annotations
from copy import deepcopy
import xml.etree.ElementTree as ET
import json
import math
from pathlib import Path
from typing import Mapping, Any

from ultimate_pipeline.enrichment.lane_width_policy import (
    DEFAULT_DRIVING_WIDTH_M,
    HIGHWAY_DEFAULT_WIDTH_M,
    target_driving_width_m,
    driving_lane_counts,
    road_lane_width_metadata,
)

DEFAULT_WIDTH = DEFAULT_DRIVING_WIDTH_M
CENTER_WIDTH = 0.20   # dummy center lane width

_RAST06_WIDTH: dict = dict(HIGHWAY_DEFAULT_WIDTH_M)
_RAST06_WIDTH.update({"path": 2.0, "cycleway": 2.0, "footway": 1.5, "pedestrian": 2.0})

TURN_LANE_APPROACH_LENGTH_M = 30.0
CYCLE_LANE_WIDTH_M = _RAST06_WIDTH["cycleway"]
_TURN_THROUGH_VALUES = {"through", "straight", "none", "no"}
_TURN_VALUES = {
    "left",
    "right",
    "slight_left",
    "slight_right",
    "sharp_left",
    "sharp_right",
    "reverse",
    "uturn",
    "u_turn",
    "merge_to_left",
    "merge_to_right",
}


def _road_type_width(
    road: ET.Element,
    osm_meta: Mapping[str, Mapping[str, Any]] | None = None,
) -> float:
    """Return per-type lane width for non-junction roads; falls back to DEFAULT_WIDTH."""
    decision = target_driving_width_m(road, osm_meta=osm_meta)
    if decision.source != "fallback":
        return decision.width_m
    type_elem = road.find("type")
    if type_elem is None:
        return DEFAULT_WIDTH
    road_type = (type_elem.get("type") or "").strip().lower()
    return _RAST06_WIDTH.get(road_type, DEFAULT_WIDTH)


class LaneGenerator:

    # ---------------------------------------------------------------
    @staticmethod
    def _lane_count(road: ET.Element) -> int:
        lanes = road.find("lanes")
        if lanes is None:
            return 0

        count = 0
        for lsec in lanes.findall("laneSection"):
            for side in ("left", "right", "center"):
                s_elem = lsec.find(side)
                if s_elem is None:
                    continue
                count += len(s_elem.findall("lane"))
        return count

    # ---------------------------------------------------------------
    @staticmethod
    def _has_driving_lanes(road: ET.Element) -> bool:
        lanes = road.find("lanes")
        if lanes is None:
            return False

        for lsec in lanes.findall("laneSection"):
            for side_name in ("left", "right"):
                side = lsec.find(side_name)
                if side is None:
                    continue
                for lane in side.findall("lane"):
                    if lane.get("type") == "driving":
                        return True

        return False

    # ---------------------------------------------------------------
    @staticmethod
    def _is_connector(road: ET.Element) -> bool:
        return road.get("junction", "-1") != "-1"

    # ---------------------------------------------------------------
    @staticmethod
    def _ensure(parent: ET.Element, tag: str) -> ET.Element:
        child = parent.find(tag)
        return child if child is not None else ET.SubElement(parent, tag)

    # ---------------------------------------------------------------
    @staticmethod
    def _add_width(elem: ET.Element, width: float):
        ET.SubElement(elem, "width",
                      sOffset="0.0", a=str(width),
                      b="0.0", c="0.0", d="0.0")

    @staticmethod
    def _add_provenance(lane: ET.Element, *, source: str, confidence: float, count: int) -> None:
        user_data = lane.find("userData")
        if user_data is None:
            user_data = ET.SubElement(lane, "userData")
        LaneGenerator._set_vector(user_data, "lane_count_source", source)
        LaneGenerator._set_vector(
            user_data, "lane_count_confidence", f"{confidence:.3f}"
        )
        LaneGenerator._set_vector(user_data, "lane_count", str(count))

    @staticmethod
    def _set_vector(user_data: ET.Element, key: str, value: str) -> None:
        for vector in user_data.findall("vector"):
            if vector.get("key") == key:
                vector.set("value", value)
                return
        ET.SubElement(user_data, "vector", key=key, value=value)

    @staticmethod
    def _lane_user_data(lane: ET.Element) -> ET.Element:
        user_data = lane.find("userData")
        return user_data if user_data is not None else ET.SubElement(lane, "userData")

    @staticmethod
    def _safe_float(raw: str | None, default: float = 0.0) -> float:
        try:
            value = float(raw or default)
        except (TypeError, ValueError):
            return default
        return value if math.isfinite(value) else default

    @staticmethod
    def _ordered_lane_sections(lanes: ET.Element) -> list[ET.Element]:
        return sorted(
            lanes.findall("laneSection"),
            key=lambda section: LaneGenerator._safe_float(section.get("s")),
        )

    @staticmethod
    def _append_lane_section(lanes: ET.Element, section: ET.Element) -> None:
        """Append a laneSection while preserving monotonically ordered s values."""
        lanes.append(section)
        sections = LaneGenerator._ordered_lane_sections(lanes)
        for item in sections:
            lanes.remove(item)
        for item in sections:
            lanes.append(item)

    @staticmethod
    def _split_turn_pattern(raw: Any) -> list[str]:
        if raw is None:
            return []
        pattern = [item.strip().lower() for item in str(raw).split("|")]
        return pattern if any(pattern) else []

    @staticmethod
    def _dedicated_turn_cell(value: str) -> bool:
        tokens = {
            token.strip().lower()
            for token in value.replace(",", ";").split(";")
            if token.strip()
        }
        if not tokens or tokens & _TURN_THROUGH_VALUES:
            return False
        return bool(tokens & _TURN_VALUES)

    @staticmethod
    def _turn_patterns(
        road: ET.Element,
        structural_osm_meta: Mapping[str, Mapping[str, Any]] | None,
    ) -> list[tuple[str, list[str], str, float]]:
        """Resolve OSM turn-lane semantics without mixing directions.

        OSM's directional tags are authoritative.  The combined tag is only
        considered when neither directional tag exists; it applies to the
        forward XODR carriageway, which is the OSM way direction convention.
        """
        meta = LaneGenerator._structural_feature_metadata(
            road, structural_osm_meta
        )
        forward = LaneGenerator._split_turn_pattern(meta.get("turn:lanes:forward"))
        backward = LaneGenerator._split_turn_pattern(meta.get("turn:lanes:backward"))
        if forward or backward:
            patterns: list[tuple[str, list[str], str, float]] = []
            if forward:
                patterns.append(
                    ("forward", forward, "osm:turn:lanes:forward", 1.0)
                )
            if backward:
                patterns.append(
                    ("backward", backward, "osm:turn:lanes:backward", 1.0)
                )
            return patterns

        combined = LaneGenerator._split_turn_pattern(
            meta.get("turn:lanes") or meta.get("turn_lanes")
        )
        return (
            [("forward", combined, "osm:turn:lanes", 0.75)] if combined else []
        )

    @staticmethod
    def _structural_feature_metadata(
        road: ET.Element,
        structural_osm_meta: Mapping[str, Mapping[str, Any]] | None,
    ) -> dict[str, str]:
        """Return only road-resolved OSM tags suitable for geometry mutation.

        ``build_osm_meta_index`` is keyed by street name and is intentionally
        useful for hints such as maxspeed.  Turn-lane and cycleway tags are
        position-specific, so applying that name index to structural geometry
        would create lanes on unrelated segments.  Geometry therefore accepts
        only direct XODR OSM provenance or an explicit XODR-road-ID map from a
        correspondence engine.
        """
        meta = road_lane_width_metadata(road, osm_meta=None)
        road_id = (road.get("id") or "").strip()
        resolved = structural_osm_meta.get(road_id) if structural_osm_meta else None
        if resolved:
            for key, value in resolved.items():
                if value is not None:
                    meta[str(key).strip().lower()] = str(value).strip()
        return meta

    @staticmethod
    def _junction_approach_section(
        road: ET.Element, direction: str
    ) -> ET.Element | None:
        """Return the lane section covering a junction approach, creating a split.

        The split confines an inferred turn lane to the final approach portion
        of the road.  Roads without an explicit junction endpoint are left
        unchanged because a name-level OSM match cannot safely identify an
        approach on an arbitrary road segment.
        """
        lanes = road.find("lanes")
        link = road.find("link")
        if lanes is None or link is None:
            return None
        endpoint_name = "successor" if direction == "forward" else "predecessor"
        endpoint = link.find(endpoint_name)
        if endpoint is None or (endpoint.get("elementType") or "").lower() != "junction":
            return None

        length = LaneGenerator._safe_float(road.get("length"))
        sections = LaneGenerator._ordered_lane_sections(lanes)
        if length <= 0.0 or not sections:
            return None
        approach = min(TURN_LANE_APPROACH_LENGTH_M, length)

        if direction == "forward":
            current = sections[-1]
            current_s = LaneGenerator._safe_float(current.get("s"))
            start_s = max(current_s, length - approach)
            if start_s > current_s + 1e-9:
                current = deepcopy(current)
                current.set("s", f"{start_s:.6f}")
                LaneGenerator._append_lane_section(lanes, current)
            return current

        current = sections[0]
        current_s = LaneGenerator._safe_float(current.get("s"))
        end_s = min(length, current_s + approach)
        next_s = (
            LaneGenerator._safe_float(sections[1].get("s"))
            if len(sections) > 1
            else None
        )
        if next_s is not None and next_s <= end_s + 1e-9:
            return current
        if end_s < length - 1e-9:
            restore = deepcopy(current)
            restore.set("s", f"{end_s:.6f}")
            LaneGenerator._append_lane_section(lanes, restore)
        return current

    @staticmethod
    def _driving_lanes_in_pattern_order(
        lane_section: ET.Element, side_name: str
    ) -> list[ET.Element]:
        side = lane_section.find(side_name)
        if side is None:
            return []
        lanes: list[tuple[int, ET.Element]] = []
        for lane in side.findall("lane"):
            if lane.get("type") != "driving":
                continue
            try:
                lane_id = int(lane.get("id", ""))
            except ValueError:
                continue
            if (side_name == "right" and lane_id < 0) or (
                side_name == "left" and lane_id > 0
            ):
                lanes.append((lane_id, lane))
        lanes.sort(key=lambda item: abs(item[0]), reverse=side_name == "left")
        return [lane for _, lane in lanes]

    @staticmethod
    def _pattern_lane_id(side_name: str, index: int, count: int) -> int:
        return -(index + 1) if side_name == "right" else count - index

    @staticmethod
    def _driving_lane_count(road: ET.Element) -> int:
        return len(road.findall(".//lane[@type='driving']"))

    @staticmethod
    def _ensure_turn_pattern(
        road: ET.Element,
        lane_section: ET.Element,
        *,
        direction: str,
        pattern: list[str],
        source: str,
        confidence: float,
        width_m: float,
    ) -> int:
        if not any(LaneGenerator._dedicated_turn_cell(cell) for cell in pattern):
            return 0
        side_name = "right" if direction == "forward" else "left"
        side = LaneGenerator._ensure(lane_section, side_name)
        existing = LaneGenerator._driving_lanes_in_pattern_order(
            lane_section, side_name
        )
        if len(existing) >= len(pattern):
            assigned = existing[: len(pattern)]
        else:
            # Preserve through lanes first.  This makes the newly created
            # geometry correspond to the dedicated turn movement whenever
            # the base profile only contains through traffic.
            preferred = [
                index
                for index, cell in enumerate(pattern)
                if not LaneGenerator._dedicated_turn_cell(cell)
            ]
            preferred.extend(
                index for index in range(len(pattern)) if index not in preferred
            )
            assigned_by_index: dict[int, ET.Element] = {}
            for index, lane in zip(preferred, existing):
                assigned_by_index[index] = lane
            assigned = []
            for index in range(len(pattern)):
                lane = assigned_by_index.get(index)
                if lane is None:
                    lane = ET.SubElement(
                        side,
                        "lane",
                        type="driving",
                        level="false",
                    )
                    LaneGenerator._add_width(lane, width_m)
                    LaneGenerator._add_provenance(
                        lane,
                        source=source,
                        confidence=confidence,
                        count=len(pattern),
                    )
                assigned.append(lane)

        created = max(0, len(pattern) - len(existing))
        for index, (lane, cell) in enumerate(zip(assigned, pattern)):
            lane.set("id", str(LaneGenerator._pattern_lane_id(side_name, index, len(pattern))))
            user_data = LaneGenerator._lane_user_data(lane)
            LaneGenerator._set_vector(user_data, "turn_lane_pattern", cell)
            LaneGenerator._set_vector(user_data, "turn_lane_direction", direction)
            LaneGenerator._set_vector(
                user_data,
                "turn_lane_dedicated",
                "true" if LaneGenerator._dedicated_turn_cell(cell) else "false",
            )
            if lane.find("width") is None:
                LaneGenerator._add_width(lane, width_m)
        return created

    @staticmethod
    def _apply_turn_lane_geometry(
        road: ET.Element,
        structural_osm_meta: Mapping[str, Mapping[str, Any]] | None,
    ) -> int:
        if LaneGenerator._is_connector(road):
            return 0
        width_m = _road_type_width(road, osm_meta=None)
        created = 0
        for direction, pattern, source, confidence in LaneGenerator._turn_patterns(
            road, structural_osm_meta
        ):
            lane_section = LaneGenerator._junction_approach_section(road, direction)
            if lane_section is None:
                continue
            created += LaneGenerator._ensure_turn_pattern(
                road,
                lane_section,
                direction=direction,
                pattern=pattern,
                source=source,
                confidence=confidence,
                width_m=width_m,
            )
        return created

    @staticmethod
    def _apply_cycle_lane_geometry(
        road: ET.Element,
        structural_osm_meta: Mapping[str, Mapping[str, Any]] | None,
    ) -> int:
        if LaneGenerator._is_connector(road):
            return 0
        meta = LaneGenerator._structural_feature_metadata(
            road, structural_osm_meta
        )
        if (meta.get("highway") or "").strip().lower() == "cycleway":
            return 0

        def is_dedicated(value: Any) -> bool:
            return str(value or "").strip().lower() in {"lane", "track"}

        sides: list[tuple[str, str, float]] = []
        for side in ("left", "right"):
            if is_dedicated(meta.get(f"cycleway:{side}")):
                sides.append((side, f"osm:cycleway:{side}", 1.0))
        if not sides and is_dedicated(meta.get("cycleway")):
            # The generic OSM tag confirms a facility but not a side.  Keep
            # that uncertainty visible in provenance instead of duplicating
            # a lane on both carriageways.
            sides.append(("right", "osm:cycleway:side_unknown", 0.5))
        if not sides:
            return 0

        created = 0
        lanes = road.find("lanes")
        if lanes is None:
            return 0
        for lane_section in LaneGenerator._ordered_lane_sections(lanes):
            for side_name, source, confidence in sides:
                side = LaneGenerator._ensure(lane_section, side_name)
                if any(
                    lane.get("type") == "biking"
                    for lane in side.findall("lane")
                ):
                    continue
                lane_ids = []
                for lane in side.findall("lane"):
                    try:
                        lane_ids.append(int(lane.get("id", "")))
                    except ValueError:
                        continue
                lane_id = (
                    min([item for item in lane_ids if item < 0], default=0) - 1
                    if side_name == "right"
                    else max([item for item in lane_ids if item > 0], default=0) + 1
                )
                biking = ET.SubElement(
                    side,
                    "lane",
                    id=str(lane_id),
                    type="biking",
                    level="false",
                )
                LaneGenerator._add_width(biking, CYCLE_LANE_WIDTH_M)
                LaneGenerator._add_provenance(
                    biking, source=source, confidence=confidence, count=1
                )
                user_data = LaneGenerator._lane_user_data(biking)
                LaneGenerator._set_vector(user_data, "cycle_lane_source", source)
                created += 1
        return created

    # ---------------------------------------------------------------
    @staticmethod
    def ensure_lanes(
        root: ET.Element,
        verbose=True,
        osm_meta: Mapping[str, Mapping[str, Any]] | None = None,
        structural_osm_meta: Mapping[str, Mapping[str, Any]] | None = None,
        provenance_report_path: str | Path | None = None,
    ) -> int:
        created = 0
        turn_lanes_created = 0
        cycle_lanes_created = 0

        for road in root.findall("road"):
            rid = road.get("id", "?")

            if not LaneGenerator._has_driving_lanes(road):
                lanes = road.find("lanes")
                if lanes is None:
                    lanes = ET.SubElement(road, "lanes")

                def _lane_count_section(lsec):
                    return sum(
                        len(side.findall("lane"))
                        for side_name in ("left", "right", "center")
                        if (side := lsec.find(side_name)) is not None
                    )

                for lane_section in list(lanes.findall("laneSection")):
                    if _lane_count_section(lane_section) == 0:
                        lanes.remove(lane_section)

                lane_section = ET.SubElement(lanes, "laneSection", s="0.0")
                left = LaneGenerator._ensure(lane_section, "left")
                center = LaneGenerator._ensure(lane_section, "center")
                right = LaneGenerator._ensure(lane_section, "right")

                if LaneGenerator._is_connector(road):
                    center_lane = ET.SubElement(
                        center, "lane", id="0", type="none", level="false"
                    )
                    LaneGenerator._add_width(center_lane, CENTER_WIDTH)
                    driving = ET.SubElement(
                        right, "lane", id="-1", type="driving", level="false"
                    )
                    LaneGenerator._add_width(
                        driving,
                        target_driving_width_m(road, osm_meta=osm_meta).width_m,
                    )
                    created += 1
                    if verbose:
                        print(
                            f"[LaneGenerator] Connector road {rid} → center none + right driving lane"
                        )
                else:
                    road_w = _road_type_width(road, osm_meta=osm_meta)
                    left_count, right_count, count_source, count_confidence = (
                        driving_lane_counts(road, osm_meta=osm_meta)
                    )
                    center_lane = ET.SubElement(
                        center, "lane", id="0", type="none", level="false"
                    )
                    LaneGenerator._add_width(center_lane, CENTER_WIDTH)
                    for index in range(left_count):
                        lane = ET.SubElement(
                            left,
                            "lane",
                            id=str(index + 1),
                            type="driving",
                            level="false",
                        )
                        LaneGenerator._add_width(lane, road_w)
                        LaneGenerator._add_provenance(
                            lane,
                            source=count_source,
                            confidence=count_confidence,
                            count=left_count + right_count,
                        )
                    for index in range(right_count):
                        lane = ET.SubElement(
                            right,
                            "lane",
                            id=str(-(index + 1)),
                            type="driving",
                            level="false",
                        )
                        LaneGenerator._add_width(lane, road_w)
                        LaneGenerator._add_provenance(
                            lane,
                            source=count_source,
                            confidence=count_confidence,
                            count=left_count + right_count,
                        )
                    created += 1
                    if verbose:
                        print(f"[LaneGenerator] Added full lane profile for road {rid}")

            turn_lanes_created += LaneGenerator._apply_turn_lane_geometry(
                road, structural_osm_meta
            )
            cycle_lanes_created += LaneGenerator._apply_cycle_lane_geometry(
                road, structural_osm_meta
            )

        if verbose:
            print(f"[LaneGenerator] Total new lane assignments: {created}")
            print(
                "[LaneGenerator] Structural lane features: "
                f"turn={turn_lanes_created}, cycle={cycle_lanes_created}"
            )

        if provenance_report_path is not None:
            Path(provenance_report_path).write_text(
                json.dumps(LaneGenerator.lane_provenance_report(root), indent=2, sort_keys=True),
                encoding="utf-8",
            )
        return created

    @staticmethod
    def lane_provenance_report(root: ET.Element) -> dict[str, Any]:
        roads = []
        connector_mapping_limitations = []
        for road in sorted(root.findall("road"), key=lambda item: item.get("id", "")):
            lanes = []
            for lane in road.findall(".//lane"):
                if lane.get("id") == "0":
                    continue
                values = {
                    node.get("key"): node.get("value")
                    for node in lane.findall("./userData/vector")
                }
                try:
                    lane_id = int(lane.get("id", "0"))
                    confidence = float(values.get("lane_count_confidence", "1.0"))
                    count = int(values.get("lane_count", "0"))
                except (TypeError, ValueError):
                    continue
                turn_pattern = values.get("turn_lane_pattern")
                mapping_status = (
                    "requires_lanelink_rebuild"
                    if turn_pattern is not None
                    else "not_applicable"
                )
                lane_report = {
                    "lane_id": lane_id,
                    "type": lane.get("type", "none"),
                    "source": values.get("lane_count_source", "existing_xodr"),
                    "confidence": confidence,
                    "count": count,
                    "turn_pattern": turn_pattern,
                    "turn_direction": values.get("turn_lane_direction"),
                    "connector_mapping_status": mapping_status,
                }
                lanes.append(lane_report)
                if mapping_status == "requires_lanelink_rebuild":
                    connector_mapping_limitations.append(
                        {
                            "road_id": road.get("id", ""),
                            "lane_id": lane_id,
                            "reason": "turn_lane_geometry_requires_lanelink_rebuild",
                        }
                    )
            roads.append(
                {
                    "road_id": road.get("id", ""),
                    "lanes": sorted(lanes, key=lambda item: item["lane_id"]),
                }
            )
        return {
            "schema_version": 1,
            "roads": roads,
            "known_limitations": {
                "connector_mapping": connector_mapping_limitations,
            },
        }
