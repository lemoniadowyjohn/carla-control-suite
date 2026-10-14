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
from typing import Any, Dict, List, Optional

import xml.etree.ElementTree as ET

from ultimate_pipeline.quality.xodr_numeric import (
    parse_required_float,
)
from ultimate_pipeline.quality.xodr_validation_policy import (
    ALL_PRIMITIVES,
    PARAMPOLY3_PRANGE_SUPPORTED,
    PRIMITIVE_REQUIRED_ATTRS,
    ROAD_LENGTH_ABS_TOL_M,
    ROAD_LENGTH_REL_TOL,
    road_length_check,
)


@dataclass
class Issue:
    code: str
    severity: str  # 'error' or 'warn'
    message: str
    context: Dict[str, Any]


def _is_finite(x: float) -> bool:
    return not (math.isnan(x) or math.isinf(x))


def _safe_float(v: Optional[str], default: float = 0.0) -> float:
    """LEGACY fail-open parse (kept for backward-compatible import only).

    Validation code below uses xodr_numeric.parse_required_float instead
    (OC-59 §2): malformed/nonfinite input must be reported, never defaulted.
    """
    parsed = parse_required_float(v)
    if parsed.ok:
        return float(parsed.value)
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


SUPPORTED_PRIMITIVES = set(ALL_PRIMITIVES)

# Road-length tolerance lives in exactly one place (§8):
# xodr_validation_policy.ROAD_LENGTH_ABS_TOL_M / ROAD_LENGTH_REL_TOL.


class StrictCarlaOpendriveGate:
    """A strict, CARLA-focused OpenDRIVE validator."""

    # Intentionally loose (catch obvious corruption, not fight the mapper);
    # single-sourced from xodr_validation_policy -- do not redefine here.
    ROAD_LENGTH_REL_TOL = ROAD_LENGTH_REL_TOL
    ROAD_LENGTH_ABS_TOL = ROAD_LENGTH_ABS_TOL_M

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
            length_res = parse_required_float(road.get("length"))
            if not length_res.ok:
                out.append(Issue(
                    f"road_length_{length_res.status.lower()}", "error",
                    f"Road length is {length_res.status} (raw={length_res.raw!r}); "
                    "refusing to substitute a default.",
                    {"road": rid, "length": road.get("length")}))
                length = float("nan")
            else:
                length = float(length_res.value)
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

            # Validate geometry sequence (strict numerics: malformed attrs
            # are errors with their outcome, never defaulted zeros).
            s_prev = -1.0
            sum_len = 0.0
            for idx, g in enumerate(geoms):
                s_res = parse_required_float(g.get("s"))
                glen_res = parse_required_float(g.get("length"))
                x_res = parse_required_float(g.get("x"))
                y_res = parse_required_float(g.get("y"))
                hdg_res = parse_required_float(g.get("hdg"))

                # Exactly one known primitive child (§7); unknown is explicit.
                prim_names = [c.tag for c in list(g)
                              if isinstance(c.tag, str)]
                known = [t for t in prim_names if t in ALL_PRIMITIVES]
                unknown = [t for t in prim_names if t not in ALL_PRIMITIVES]
                if unknown:
                    prim = f"unknown:{unknown[0]}"
                    out.append(Issue("geometry_unknown_primitive", "error",
                                     f"Geometry has unknown primitive child '{unknown[0]}'.",
                                     {"road": rid, "index": idx,
                                      "primitive": prim}))
                elif len(known) != 1:
                    prim = "ambiguous" if known else "missing"
                    out.append(Issue("geometry_primitive_count", "error",
                                     "Geometry must have exactly one known "
                                     "primitive child.",
                                     {"road": rid, "index": idx,
                                      "children": prim_names}))
                else:
                    prim = known[0]
                    out.extend(StrictCarlaOpendriveGate._check_primitive_coeffs(
                        rid, idx, g, prim))

                # Previous geometry end and next geometry start
                prev_end = None
                next_start = None
                if idx > 0:
                    prev_g = geoms[idx - 1]
                    prev_s = parse_required_float(prev_g.get("s"))
                    prev_len = parse_required_float(prev_g.get("length"))
                    if prev_s.ok and prev_len.ok:
                        prev_end = float(prev_s.value) + float(prev_len.value)
                if idx < len(geoms) - 1:
                    nxt = parse_required_float(geoms[idx + 1].get("s"))
                    if nxt.ok:
                        next_start = float(nxt.value)

                if not s_res.ok:
                    out.append(Issue(
                        f"geometry_s_{s_res.status.lower()}", "error",
                        f"Geometry s is {s_res.status} (raw={s_res.raw!r}).",
                        {"road": rid, "index": idx}))
                else:
                    s = float(s_res.value)
                    if s < 0.0:
                        out.append(Issue("geometry_s_negative", "error", "Geometry s must be >= 0.", {"road": rid, "s": s, "index": idx}))
                    if s <= s_prev:
                        out.append(Issue("geometry_s_not_increasing", "error", "Geometry s must be strictly increasing.", {"road": rid, "prev": s_prev, "s": s, "index": idx}))
                    s_prev = s

                glen_raw = g.get("length")
                if not glen_res.ok or float(glen_res.value if glen_res.ok else 0.0) <= 0.0:
                    out.append(Issue(
                        "geometry_length_invalid" if glen_res.ok else
                        f"geometry_length_{glen_res.status.lower()}",
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
                    sum_len += float(glen_res.value)

                # Coordinates must be finite (strict: absent/malformed/
                # nonfinite each reported, never defaulted).
                for field, res, raw in (("x", x_res, g.get("x")),
                                        ("y", y_res, g.get("y")),
                                        ("hdg", hdg_res, g.get("hdg"))):
                    if not res.ok:
                        out.append(Issue(
                            f"geometry_{field}_{res.status.lower()}", "error",
                            f"Geometry {field} is {res.status} "
                            f"(raw={res.raw!r}).",
                            {"road": rid, "index": idx, field: raw}))

            # Road length sanity relative to geometry sum (single policy §8).
            if math.isfinite(length) and length > 0.0 and sum_len > 0.0:
                verdict = road_length_check(length, sum_len)
                if verdict["status"] == "MISMATCH":
                    out.append(Issue(
                        "road_length_mismatch",
                        "warn",
                        "Road length differs substantially from sum(planView.geometry.length). Large mismatches are linked to CARLA import instability.",
                        {"road": rid, "road_length": length, "sum_geometry_length": sum_len,
                         "absolute_error_m": verdict["absolute_error_m"],
                         "relative_error": verdict["relative_error"]},
                    ))

            # Elevation optional; if present validate finiteness.
            for e in road.findall("./elevationProfile/elevation"):
                for k in ("s", "a", "b", "c", "d"):
                    if k not in e.attrib:
                        out.append(Issue("elevation_missing_attr", "warn", "Elevation element missing coefficient.", {"road": rid, "attr": k}))
                        continue
                    # _safe_float would silently substitute a finite default for a non-finite
                    # input, making this check unreachable; _parse_float_strict returns None
                    # for non-finite/unparseable values instead, so the check actually fires.
                    if _parse_float_strict(e.get(k)) is None:
                        out.append(Issue("elevation_nonfinite", "error", "Elevation coefficient must be finite.", {"road": rid, "attr": k, "value": e.get(k)}))

        return out

    @staticmethod
    def _check_primitive_coeffs(rid: str, idx: int, g: ET.Element,
                                prim: str) -> List[Issue]:
        """Required finite coefficients per primitive (shared contract §6)."""
        out: List[Issue] = []
        el = g.find(prim)
        if el is None:
            return out
        for attr in PRIMITIVE_REQUIRED_ATTRS.get(prim, ()):
            res = parse_required_float(el.get(attr))
            if not res.ok:
                out.append(Issue(
                    f"{prim}_{attr}_{res.status.lower()}", "error",
                    f"Primitive {prim}@{attr} is {res.status} "
                    f"(raw={res.raw!r}).",
                    {"road": rid, "index": idx, "primitive": prim}))
        if prim == "paramPoly3":
            prange = el.get("pRange", "arcLength")
            if prange not in PARAMPOLY3_PRANGE_SUPPORTED:
                out.append(Issue(
                    "paramPoly3_pRange_unsupported", "error",
                    "paramPoly3 pRange must be arcLength or normalized.",
                    {"road": rid, "index": idx, "pRange": el.get("pRange")}))
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

                # Driving lanes must have at least one positive width
                # (strict: malformed/nonfinite `a` is an error with its
                # outcome, not a defaulted value that happens to trip the
                # bound check for the wrong reason).
                for ln in sec.findall(".//lane[@type='driving']"):
                    widths = ln.findall('width')
                    if not widths:
                        out.append(Issue('driving_lane_missing_width', 'error', 'Driving lane missing <width> record.', {'road': rid, 'lane': ln.get('id')}))
                        continue
                    for w in widths:
                        a_res = parse_required_float(w.get('a'))
                        if not a_res.ok:
                            out.append(Issue(
                                f"lane_width_a_{a_res.status.lower()}", 'error',
                                f"Lane width a is {a_res.status} "
                                f"(raw={a_res.raw!r}).",
                                {'road': rid, 'lane': ln.get('id')}))
                            continue
                        a = float(a_res.value)
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
