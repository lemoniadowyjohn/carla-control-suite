#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GeometryValidator
-----------------
Runs BEFORE MeshContinuityRepairer.

This module performs lightweight structural repairs that make the later
continuity pass less destructive. It ensures that each road's geometry
segments form a valid, monotonic chain and have sane curvature, heading,
and offsets.

Validator rules:
    • reorder segments by s
    • enforce monotonic sOffsets
    • remove zero-length segments
    • normalize headings into [0, 2π)
    • clamp absurd curvature
    • detect spiral inconsistencies (curvStart/curvEnd)
    • back-fill missing x,y,hdg using ENDPOINT heading for curved primitives
    • produce structured debug output

All XML mutations are explicit: elements are removed from planView and
re-appended in sorted order. The serialized XML reflects all repairs.
"""

from __future__ import annotations

import math
import json
from xml.etree.ElementTree import Element

from ultimate_pipeline.core.repair_diff import diff_log
from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint as geometry_endpoint


def canonical_horizontal_geometry_fingerprint(root) -> str:
    """Calculate canonical fingerprint of planView geometry at freeze.

    Prevents the horizontal geometry shape from silently changing between
    the geometry freeze point and a later stage (GEOM-FREEZE-001). The
    fingerprint is a SHA-256 over roads sorted by id and their planView
    geometry attributes (s, x, y, hdg, length) plus each primitive tag and
    its sorted attributes. Flagged by OC-1 independent review; this function
    is pure and read-only so it composes with the P0-reconciled validator.
    """
    import hashlib

    h = hashlib.sha256()
    for road in sorted(root.findall("road"), key=lambda r: r.get("id", "")):
        rid = road.get("id", "")
        h.update(rid.encode())
        plan = road.find("planView")
        if plan is None:
            continue
        for geom in plan.findall("geometry"):
            for k in ["s", "x", "y", "hdg", "length"]:
                v = geom.get(k, "")
                h.update(f"{k}={v}".encode())
            prim = next(iter(geom), None)
            if prim is not None:
                h.update(prim.tag.encode())
                for kk, vv in sorted(prim.attrib.items()):
                    h.update(f"{kk}={vv}".encode())
    return h.hexdigest()


# ---------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------


def _norm_angle(h: float) -> float:
    """Normalize angle into [0, 2π)."""
    while h < 0:
        h += 2 * math.pi
    while h >= 2 * math.pi:
        h -= 2 * math.pi
    return h


def _safe_float(val, default=None):
    try:
        return float(val)
    except Exception:
        return default


def _segment_length(geom: Element) -> float:
    try:
        return float(geom.attrib.get("length", 0.0))
    except Exception:
        return 0.0


# ---------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------


class GeometryValidator:

    MAX_CURV = 1.0          # clamp radius too tight spirals
    MIN_SEG_LEN = 0.001     # zero-length threshold (meters)

    @staticmethod
    def validate(root: Element, debug_json_path: str | None = None):
        """
        Entry point.
        Mutates the XML in-place.
        """
        report = {"roads": {}}

        for road in root.findall(".//road"):
            rid = road.attrib.get("id", "UNKNOWN")
            rep = GeometryValidator._validate_road(road, rid)
            report["roads"][rid] = rep

        if debug_json_path:
            try:
                with open(debug_json_path, "w", encoding="utf-8") as f:
                    json.dump(report, f, indent=2)
            except Exception:
                pass

        return report

    # -----------------------------------------------------------------
    @staticmethod
    def _validate_road(road: Element, rid: str):
        """Validate <planView> geometry inside one road.

        All repairs are applied to the XML tree:
        - zero-length geometries are REMOVED from planView
        - geometries are REORDERED to match increasing s
        - missing hdg backfill uses ENDPOINT heading of previous geometry
        """
        plan = road.find("./planView")
        if plan is None:
            return {"status": "no_planView"}

        geoms = plan.findall("geometry")
        if not geoms:
            return {"status": "empty"}

        # Collect elements and parse attributes
        parsed = []
        issues = []
        zero_length_elems = []

        for g in geoms:
            s = _safe_float(g.attrib.get("s"))
            l = _safe_float(g.attrib.get("length"))
            hdg = _safe_float(g.attrib.get("hdg"))

            parsed.append({"elem": g, "s": s, "length": l, "hdg": hdg})

        # --------------------------------------------------------------
        # 1) Identify zero-length segments for XML removal
        # --------------------------------------------------------------
        cleaned = []
        for d in parsed:
            if (d["length"] is None or not math.isfinite(d["length"])
                    or d["length"] <= GeometryValidator.MIN_SEG_LEN):
                issues.append(f"removed_zero_length_segment_at_s={d['s']}")
                diff_log.add("geometry_validator", rid,
                             {"fix": "removed_zero_length_segment", "s": d["s"]})
                zero_length_elems.append(d["elem"])
            else:
                cleaned.append(d)

        # REMOVE zero-length geometries from XML
        for elem in zero_length_elems:
            if elem in plan:
                plan.remove(elem)

        if not cleaned:
            return {"status": "all_zero_length_removed", "issues": issues}

        # --------------------------------------------------------------
        # 2) Sort by s and REORDER XML children
        # --------------------------------------------------------------
        cleaned.sort(key=lambda d: d["s"])
        for d in cleaned:
            d["elem"].attrib["s"] = str(d["s"])

        # Remove all remaining geometries from planView and re-append in sorted order
        remaining_elems = {d["elem"] for d in cleaned}
        for elem in remaining_elems:
            if elem in plan:
                plan.remove(elem)
        for d in cleaned:
            plan.append(d["elem"])

        parsed = cleaned

        # --------------------------------------------------------------
        # 3) Fix negative sOffsets
        # --------------------------------------------------------------
        last_s = parsed[0]["s"]
        for d in parsed[1:]:
            if d["s"] < last_s:
                old_s = d["s"]
                d["s"] = last_s + 0.001
                d["elem"].attrib["s"] = str(d["s"])
                issues.append("fixed_negative_sOffset")
                diff_log.add("geometry_validator", rid,
                             {"fix": "fixed_negative_sOffset", "old_s": old_s, "new_s": d["s"]})
            last_s = d["s"]

        # --------------------------------------------------------------
        # 4) Normalize hdg
        # --------------------------------------------------------------
        for d in parsed:
            if d["hdg"] is not None:
                old_h = d["hdg"]
                d["hdg"] = _norm_angle(d["hdg"])
                d["elem"].attrib["hdg"] = str(d["hdg"])
                if old_h != d["hdg"]:
                    issues.append("normalized_heading")
                    diff_log.add("geometry_validator", rid,
                                 {"fix": "normalized_heading", "old_hdg": old_h, "new_hdg": d["hdg"]})

        # --------------------------------------------------------------
        # 5) Curvature sanity: clamp extreme spirals
        # --------------------------------------------------------------
        for d in parsed:
            spiral = d["elem"].find("spiral")
            if spiral is not None:
                cs = _safe_float(spiral.attrib.get("curvStart"))
                ce = _safe_float(spiral.attrib.get("curvEnd"))

                if cs is not None and (not math.isfinite(cs) or abs(cs) > GeometryValidator.MAX_CURV):
                    old = cs
                    clamped = max(-GeometryValidator.MAX_CURV, min(cs, GeometryValidator.MAX_CURV))
                    spiral.attrib["curvStart"] = str(clamped)
                    issues.append("clamped_curvStart")
                    diff_log.add("geometry_validator", rid,
                                 {"fix": "clamped_curvStart", "original": old, "clamped": clamped})

                if ce is not None and (not math.isfinite(ce) or abs(ce) > GeometryValidator.MAX_CURV):
                    old = ce
                    clamped = max(-GeometryValidator.MAX_CURV, min(ce, GeometryValidator.MAX_CURV))
                    spiral.attrib["curvEnd"] = str(clamped)
                    issues.append("clamped_curvEnd")
                    diff_log.add("geometry_validator", rid,
                                 {"fix": "clamped_curvEnd", "original": old, "clamped": clamped})

        # --------------------------------------------------------------
        # 6) Missing x,y,hdg propagation using ENDPOINT heading
        # --------------------------------------------------------------
        for i in range(1, len(parsed)):
            prev = parsed[i - 1]
            cur = parsed[i]

            # Backfill x,y using geometry_endpoint
            if "x" not in cur["elem"].attrib or "y" not in cur["elem"].attrib:
                if "x" in prev["elem"].attrib and "y" in prev["elem"].attrib:
                    px = _safe_float(prev["elem"].attrib["x"])
                    py = _safe_float(prev["elem"].attrib["y"])
                    try:
                        end = geometry_endpoint(prev["elem"])
                        cur["elem"].attrib["x"] = str(end.x)
                        cur["elem"].attrib["y"] = str(end.y)
                        issues.append(f"backfilled_xy_at_index={i}")
                        diff_log.add("geometry_validator", rid,
                                     {"fix": "backfilled_xy", "index": i,
                                      "px": px, "py": py,
                                      "dx": end.x - px, "dy": end.y - py})
                    except (TypeError, ValueError):
                        pass

            # Backfill hdg using ENDPOINT heading of previous geometry (not start heading)
            if cur["hdg"] is None and prev["hdg"] is not None:
                try:
                    prev_end = geometry_endpoint(prev["elem"])
                    cur["hdg"] = prev_end.heading
                    cur["elem"].attrib["hdg"] = str(cur["hdg"])
                    issues.append(f"backfilled_hdg_endpoint_at_index={i}")
                    diff_log.add("geometry_validator", rid,
                                 {"fix": "backfilled_hdg_endpoint", "index": i, "value": cur["hdg"]})
                except (TypeError, ValueError):
                    # Fallback only if endpoint computation fails
                    cur["hdg"] = prev["hdg"]
                    cur["elem"].attrib["hdg"] = str(cur["hdg"])
                    issues.append(f"backfilled_hdg_fallback_at_index={i}")
                    diff_log.add("geometry_validator", rid,
                                 {"fix": "backfilled_hdg_fallback", "index": i, "value": cur["hdg"]})

        return {
            "status": "ok",
            "num_segments": len(parsed),
            "issues": issues,
        }
