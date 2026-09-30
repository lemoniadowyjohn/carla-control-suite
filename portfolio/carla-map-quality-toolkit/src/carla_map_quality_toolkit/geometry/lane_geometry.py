from __future__ import annotations

import math

import numpy as np

from carla_map_quality_toolkit.io.opendrive import LaneSection, PolynomialRecord, Road


def _poly_value(records: tuple[PolynomialRecord, ...], s: float) -> float:
    if not records:
        return 0.0
    active = records[0]
    for record in records:
        if record.s_offset <= s:
            active = record
        else:
            break
    return active.value(s - active.s_offset)


def _section_at(road: Road, s: float) -> LaneSection:
    if not road.lane_sections:
        raise ValueError(f"Road {road.road_id} has no lane sections")
    section = road.lane_sections[0]
    for candidate in road.lane_sections:
        if candidate.s <= s:
            section = candidate
        else:
            break
    return section


def sample_reference_line(
    road: Road, step: float = 1.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample road reference line as ``(s, xy, heading)`` arrays."""
    if step <= 0:
        raise ValueError("step must be positive")
    s_values: list[float] = []
    points: list[tuple[float, float]] = []
    headings: list[float] = []

    for seg_index, geom in enumerate(road.geometries):
        count = max(1, int(math.ceil(geom.length / step)))
        distances = np.linspace(0.0, geom.length, count + 1)
        if seg_index > 0:
            distances = distances[1:]
        for ds in distances:
            if geom.kind == "line" or abs(geom.curvature) < 1e-12:
                x = geom.x + ds * math.cos(geom.hdg)
                y = geom.y + ds * math.sin(geom.hdg)
                hdg = geom.hdg
            elif geom.kind == "arc":
                k = geom.curvature
                hdg = geom.hdg + k * ds
                x = geom.x + (math.sin(hdg) - math.sin(geom.hdg)) / k
                y = geom.y - (math.cos(hdg) - math.cos(geom.hdg)) / k
            else:
                raise ValueError(f"Unsupported geometry kind: {geom.kind}")
            s_values.append(geom.s + float(ds))
            points.append((x, y))
            headings.append(hdg)

    return np.asarray(s_values), np.asarray(points), np.asarray(headings)


def _lane_width(section: LaneSection, lane_id: int, s_local: float) -> float:
    lane = section.lanes.get(lane_id)
    if lane is None:
        raise KeyError(f"Lane {lane_id} not found")
    return max(0.0, _poly_value(lane.widths, s_local))


def _lane_center_offset(section: LaneSection, lane_id: int, s_local: float) -> float:
    if lane_id == 0:
        return 0.0
    sign = 1.0 if lane_id > 0 else -1.0
    ids = range(1, lane_id + 1) if lane_id > 0 else range(-1, lane_id - 1, -1)
    widths = [_lane_width(section, current, s_local) for current in ids]
    if not widths:
        return 0.0
    return sign * (sum(widths[:-1]) + widths[-1] / 2.0)


def lane_centerline(road: Road, lane_id: int, step: float = 1.0) -> np.ndarray:
    """Approximate an OpenDRIVE lane centerline from the road reference line.

    This implementation intentionally targets deterministic QA geometry rather
    than full OpenDRIVE surface reconstruction. It supports lane-width and
    laneOffset polynomials and is suitable for synthetic/regression fixtures.
    """
    s_values, reference, headings = sample_reference_line(road, step=step)
    result = np.empty_like(reference)
    for i, (s, point, hdg) in enumerate(zip(s_values, reference, headings, strict=True)):
        section = _section_at(road, float(s))
        s_local = float(s - section.s)
        lane_offset = _poly_value(road.lane_offsets, float(s))
        offset = lane_offset + _lane_center_offset(section, lane_id, s_local)
        normal = np.array([-math.sin(float(hdg)), math.cos(float(hdg))])
        result[i] = point + offset * normal
    return result
