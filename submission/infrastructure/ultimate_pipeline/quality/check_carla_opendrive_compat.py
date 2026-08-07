#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Offline CARLA-compatibility quality gate for OpenDRIVE (*.xodr).

CARLA's OpenDRIVE importer can hard-crash on certain malformed or unsupported
OpenDRIVE constructs. This gate catches common crash-inducing patterns before
attempting to load the map in CARLA.

This is not a full OpenDRIVE schema validator. It focuses on invariants that
are repeatedly implicated in CARLA import failures: missing header/geoReference,
non-finite or non-positive lengths, broken junction references, inconsistent
"connectingRoad" semantics, missing center lanes, and discontinuous planView
geometry.

Interface
---------
StrictCarlaOpendriveGate.validate(root) -> list[dict]
Returns an empty list if no problems were found.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import xml.etree.ElementTree as ET


@dataclass
class Issue:
    code: str
    severity: str  # 'error' or 'warn'
    message: str
    context: Dict[str, Any]


def _is_finite(x: float) -> bool:
    return not (math.isnan(x) or math.isinf(x))


def _safe_float(v: Optional[str], default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        x = float(v)
        return x if _is_finite(x) else default
    except Exception:
        return default


def _parse_float_strict(v: Optional[str]) -> Optional[float]:
    """Parse a float attribute; return None for missing, NaN, or Inf.

    Unlike _safe_float, this does NOT substitute defaults for non-finite
    values so that callers can distinguish "missing" from "non-finite".
    """
    if v is None:
        return None
    try:
        x = float(v)
        if not _is_finite(x):
            return None
        return x
    except Exception:
        return None


SUPPORTED_PRIMITIVES = {"line", "arc", "spiral", "poly3", "paramPoly3"}


class StrictCarlaOpendriveGate:
    """A strict, CARLA-focused OpenDRIVE validator."""

    # These tolerances are intentionally loose; the goal is to catch obvious
    # corruption, not fight the mapper.
    ROAD_LENGTH_REL_TOL = 0.25
    ROAD_LENGTH_ABS_TOL = 5.0

    @staticmethod
    def validate(root: ET.Element) -> List[Dict[str, Any]]:
        issues: List[Issue] = []

        if root.tag != 'OpenDRIVE':
            issues.append(Issue('root_tag', 'error', 'Root tag must be <OpenDRIVE>.', {'tag': root.tag}))
            return [i.__dict__ for i in issues]

        issues.extend(StrictCarlaOpendriveGate._check_header(root))
        road_map = StrictCarlaOpendriveGate._index_roads(root, issues)
        if not road_map:
            return [i.__dict__ for i in issues]

        issues.extend(StrictCarlaOpendriveGate._check_roads(root, road_map))
        issues.extend(StrictCarlaOpendriveGate._check_junctions(root, road_map))
        issues.extend(StrictCarlaOpendriveGate._check_lane_sections(root, road_map))

        return [i.__dict__ for i in issues]

    @staticmethod
    def _check_header(root: ET.Element) -> List[Issue]:
        out: List[Issue] = []
        header = root.find('header')
        if header is None:
            out.append(Issue('missing_header', 'error', 'Missing <header> element.', {}))
            return out

        geo = header.find('geoReference')
        if geo is None or not (geo.text and geo.text.strip()):
            # Older CARLA versions have been reported to crash when geoReference
            # is missing or unparsable.
            out.append(Issue('missing_georeference', 'error', 'Missing or empty <geoReference> in <header>.', {}))

        # Offset is not strictly required but helps avoid huge coordinates.
        off = header.find('offset')
        if off is None:
            out.append(Issue('missing_offset', 'warn', 'Missing <offset> in <header> (recommended).', {}))
        else:
            for k in ('x', 'y', 'z', 'hdg'):
                if k not in off.attrib:
                    out.append(Issue('offset_missing_attr', 'warn', f'<offset> missing attribute {k}.', {}))
        return out

    @staticmethod
    def _index_roads(root: ET.Element, issues: List[Issue]) -> Dict[str, ET.Element]:
        road_map: Dict[str, ET.Element] = {}
        for r in root.findall('road'):
            rid = r.get('id')
            if not rid:
                issues.append(Issue('road_missing_id', 'error', 'A <road> is missing required id attribute.', {}))
                continue
            if rid in road_map:
                issues.append(Issue('duplicate_road_id', 'error', 'Duplicate road id detected.', {'id': rid}))
                continue
            road_map[rid] = r
        return road_map

    @staticmethod
    def _check_roads(root: ET.Element, road_map: Dict[str, ET.Element]) -> List[Issue]:
        out: List[Issue] = []
        for rid, road in road_map.items():
            jid = road.get("junction")
            length = _safe_float(road.get("length"), -1.0)
            if length <= 0.0:
                out.append(Issue("road_length_nonpositive", "error", "Road length must be > 0.", {"road": rid, "length": road.get("length")}))

            plan = road.find("planView")
            if plan is None:
                out.append(Issue("missing_planView", "error", "Road missing <planView>.", {"road": rid}))
                continue

            geoms = plan.findall("geometry")
            if not geoms:
                out.append(Issue("missing_geometry", "error", "Road planView contains no <geometry>.", {"road": rid}))
                continue

            # Validate geometry sequence.
            s_prev = -1.0
            sum_len = 0.0
            for idx, g in enumerate(geoms):
                s = _parse_float_strict(g.get("s"))
                glen_raw = g.get("length")
                glen = _parse_float_strict(glen_raw)
                x_raw = g.get("x")
                y_raw = g.get("y")
                hdg_raw = g.get("hdg")
                x = _parse_float_strict(x_raw)
                y = _parse_float_strict(y_raw)
                hdg = _parse_float_strict(hdg_raw)

                # Determine primitive type
                prim = "unknown"
                if g.find("line") is not None:
                    prim = "line"
                elif g.find("arc") is not None:
                    prim = "arc"
                elif g.find("spiral") is not None:
                    prim = "spiral"
                elif g.find("poly3") is not None:
                    prim = "poly3"
                elif g.find("paramPoly3") is not None:
                    prim = "paramPoly3"

                # Previous geometry end and next geometry start
                prev_end = None
                next_start = None
                if idx > 0:
                    prev_g = geoms[idx - 1]
                    prev_s = _parse_float_strict(prev_g.get("s"))
                    prev_len = _parse_float_strict(prev_g.get("length"))
                    if prev_s is not None and prev_len is not None:
                        prev_end = prev_s + prev_len
                if idx < len(geoms) - 1:
                    nxt_g = geoms[idx + 1]
                    next_start = _parse_float_strict(nxt_g.get("s"))

                if s is None:
                    out.append(Issue("geometry_missing_s", "error", "Geometry missing s attribute.", {"road": rid, "index": idx}))
                else:
                    if s < 0.0:
                        out.append(Issue("geometry_s_negative", "error", "Geometry s must be >= 0.", {"road": rid, "s": s, "index": idx}))
                    if s <= s_prev:
                        out.append(Issue("geometry_s_not_increasing", "error", "Geometry s must be strictly increasing.", {"road": rid, "prev": s_prev, "s": s, "index": idx}))
                    s_prev = s

                if glen is None or glen <= 0.0:
                    out.append(Issue(
                        "geometry_length_invalid",
                        "error",
                        "Geometry length must be finite and > 0.",
                        {
                            "road": rid,
                            "junction": jid,
                            "index": idx,
                            "primitive": prim,
                            "s": g.get("s"),
                            "length": glen_raw,
                            "previous_geometry_end": prev_end,
                            "next_geometry_start": next_start,
                            "road_length": road.get("length"),
                        },
                    ))
                else:
                    sum_len += glen

                # Coordinates must be finite.
                if x is None or y is None or hdg is None:
                    bad_attrs = []
                    if x is None and x_raw is not None:
                        bad_attrs.append("x")
                    if y is None and y_raw is not None:
                        bad_attrs.append("y")
                    if hdg is None and hdg_raw is not None:
                        bad_attrs.append("hdg")
                    out.append(Issue("geometry_nonfinite", "error", f"Geometry {', '.join(bad_attrs)} is not finite.", {"road": rid, "index": idx, "bad_attrs": bad_attrs}))

                # CARLA supports line/arc/spiral/poly3/paramPoly3 in practice.
                if prim not in SUPPORTED_PRIMITIVES:
                    out.append(Issue("geometry_unsupported_primitive", "warn", f"Geometry has unsupported primitive type '{prim}'.", {"road": rid, "index": idx, "primitive": prim}))

            # Road length sanity relative to geometry sum.
            if length > 0.0 and sum_len > 0.0:
                abs_err = abs(length - sum_len)
                rel_err = abs_err / max(length, 1e-6)
                if abs_err > StrictCarlaOpendriveGate.ROAD_LENGTH_ABS_TOL and rel_err > StrictCarlaOpendriveGate.ROAD_LENGTH_REL_TOL:
                    out.append(Issue(
                        "road_length_mismatch",
                        "warn",
                        "Road length differs substantially from sum(planView.geometry.length). Large mismatches are linked to CARLA import instability.",
                        {"road": rid, "road_length": length, "sum_geometry_length": sum_len, "abs_err": abs_err, "rel_err": rel_err},
                    ))

            # Elevation optional; if present validate finiteness.
            for e in road.findall("./elevationProfile/elevation"):
                for k in ("s", "a", "b", "c", "d"):
                    if k not in e.attrib:
                        out.append(Issue("elevation_missing_attr", "warn", "Elevation element missing coefficient.", {"road": rid, "attr": k}))
                        continue
                    if not _is_finite(_safe_float(e.get(k), 0.0)):
                        out.append(Issue("elevation_nonfinite", "error", "Elevation coefficient must be finite.", {"road": rid, "attr": k, "value": e.get(k)}))

        return out

    @staticmethod
    def _check_lane_sections(root: ET.Element, road_map: Dict[str, ET.Element]) -> List[Issue]:
        out: List[Issue] = []
        for rid, road in road_map.items():
            lanes = road.find('lanes')
            if lanes is None:
                out.append(Issue('missing_lanes', 'error', 'Road missing <lanes>.', {'road': rid}))
                continue

            for sec in lanes.findall('laneSection'):
                center = sec.find('center')
                if center is None or center.find("lane[@id='0']") is None:
                    out.append(Issue('missing_center_lane', 'error', 'LaneSection must contain a center lane with id=0.', {'road': rid}))

                # Lane ids should be unique per section.
                lane_ids = []
                for ln in sec.findall('.//lane'):
                    if ln.get('id') is not None:
                        lane_ids.append(ln.get('id'))
                if len(lane_ids) != len(set(lane_ids)):
                    out.append(Issue('duplicate_lane_id', 'warn', 'Duplicate lane id within a laneSection.', {'road': rid}))

                # Driving lanes must have at least one positive width.
                for ln in sec.findall(".//lane[@type='driving']"):
                    widths = ln.findall('width')
                    if not widths:
                        out.append(Issue('driving_lane_missing_width', 'error', 'Driving lane missing <width> record.', {'road': rid, 'lane': ln.get('id')}))
                        continue
                    for w in widths:
                        a = _safe_float(w.get('a'), -1.0)
                        if a <= 0.0:
                            out.append(Issue('lane_width_nonpositive', 'error', 'Lane width a must be > 0.', {'road': rid, 'lane': ln.get('id'), 'a': w.get('a')}))

        return out

    @staticmethod
    def _check_junctions(root: ET.Element, road_map: Dict[str, ET.Element]) -> List[Issue]:
        out: List[Issue] = []
        for j in root.findall('junction'):
            jid = j.get('id', 'UNKNOWN')
            for c in j.findall('connection'):
                inc = c.get('incomingRoad')
                con = c.get('connectingRoad')
                if not inc or inc not in road_map:
                    out.append(Issue('junction_missing_incoming', 'error', 'Junction connection references missing incomingRoad.', {'junction': jid, 'incomingRoad': inc}))
                if not con or con not in road_map:
                    out.append(Issue('junction_missing_connecting', 'error', 'Junction connection references missing connectingRoad.', {'junction': jid, 'connectingRoad': con}))
                    continue

                # CARLA expects connectingRoads to belong to the junction.
                con_road = road_map[con]
                con_j = con_road.get('junction')
                if con_j is None:
                    out.append(Issue('connectingRoad_missing_junction_attr', 'warn', 'Connecting road missing road@junction attribute.', {'junction': jid, 'connectingRoad': con}))
                elif con_j != jid:
                    out.append(Issue('connectingRoad_wrong_junction', 'warn', 'connectingRoad road@junction does not match junction id.', {'junction': jid, 'connectingRoad': con, 'road_junction': con_j}))

                # Lane links are recommended for stable routing.
                lane_links = c.findall('laneLink')
                if not lane_links:
                    out.append(Issue('junction_missing_laneLink', 'warn', 'Junction connection has no <laneLink> entries.', {'junction': jid, 'connectingRoad': con}))

        return out
