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
    • back-fill missing x,y,hdg
    • produce structured debug output
"""

from __future__ import annotations

import math
import json
from xml.etree.ElementTree import Element

from ultimate_pipeline.core.repair_diff import diff_log
from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint as geometry_endpoint


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


def _is_finite(val):
    """Check if value is finite (not NaN, Inf, -Inf)."""
    try:
        return math.isfinite(float(val))
    except Exception:
        return False


# ---------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------


class GeometryValidator:

    MAX_CURV = 1.0          # clamp radius too tight spirals
    MIN_SEG_LEN = 0.001     # zero-length threshold (meters)

    # Status constants
    STATUS_OK = "ok"
    STATUS_FAIL = "fail"
    STATUS_REJECTED_REPAIR = "rejected_repair"
    STATUS_VALID_REPAIR = "valid_repair"

    @staticmethod
    def validate(root: Element, debug_json_path: str | None = None):
        """
        Entry point - performs full validation with repairs.
        Mutates the XML in-place.
        """
        plan_result = GeometryValidator._plan_geometry_repairs(root)
        apply_result = GeometryValidator._apply_geometry_repairs(root, plan_result)
        inspect_result = GeometryValidator.inspect_geometry(root)

        # Merge results
        report = {"roads": {}}
        for road in root.findall(".//road"):
            rid = road.attrib.get("id", "UNKNOWN")
            rep = {
                "status": apply_result.get("roads", {}).get(rid, {}).get("status", "ok"),
                "num_segments": inspect_result.get("roads", {}).get(rid, {}).get("num_segments", 0),
                "issues": plan_result.get("roads", {}).get(rid, {}).get("issues", []),
            }
            report["roads"][rid] = rep

        if debug_json_path:
            try:
                with open(debug_json_path, "w", encoding="utf-8") as f:
                    json.dump(report, f, indent=2)
            except Exception:
                pass

        return report

    # -----------------------------------------------------------------
    # 1. INSPECTION (read-only)
    # -----------------------------------------------------------------
    @staticmethod
    def inspect_geometry(root: Element):
        """
        Read-only inspection of geometry structure.
        Does NOT mutate XML.
        Returns a report dictionary.
        """
        report = {"roads": {}}

        for road in root.findall(".//road"):
            rid = road.attrib.get("id", "UNKNOWN")
            plan = road.find("./planView")
            if plan is None:
                report["roads"][rid] = {"status": "no_planView", "num_segments": 0}
                continue

            geoms = plan.findall("geometry")
            if not geoms:
                report["roads"][rid] = {"status": "empty", "num_segments": 0}
                continue

            issues = []
            for g in geoms:
                s = _safe_float(g.attrib.get("s"))
                l = _safe_float(g.attrib.get("length"))
                hdg = _safe_float(g.attrib.get("hdg"))

                if s is None:
                    issues.append("missing_s_attribute")
                if l is None:
                    issues.append("missing_length_attribute")
                if hdg is not None and not _is_finite(hdg):
                    issues.append("nonfinite_hdg")
                if l is not None and (not _is_finite(l) or l <= GeometryValidator.MIN_SEG_LEN):
                    issues.append("zero_or_negative_length")

            report["roads"][rid] = {
                "status": "ok" if not issues else "issues_found",
                "num_segments": len(geoms),
                "issues": issues,
            }

        return report

    # -----------------------------------------------------------------
    # 2. PLAN REPAIRS (compute what needs to be done, no XML mutation)
    # -----------------------------------------------------------------
    @staticmethod
    def _plan_geometry_repairs(root: Element):
        """
        Compute repair plan for all roads.
        Does NOT mutate XML.
        Returns a plan dictionary.
        """
        plan = {"roads": {}}

        for road in root.findall(".//road"):
            rid = road.attrib.get("id", "UNKNOWN")
            plan_elem = road.find("./planView")
            if plan_elem is None:
                plan["roads"][rid] = {"status": "no_planView", "actions": []}
                continue

            geoms = plan_elem.findall("geometry")
            if not geoms:
                plan["roads"][rid] = {"status": "empty", "actions": []}
                continue

            # Parse all geometries
            parsed = []
            issues = []

            for g in geoms:
                s = _safe_float(g.attrib.get("s"))
                l = _safe_float(g.attrib.get("length"))
                hdg = _safe_float(g.attrib.get("hdg"))

                # Check for nonfinite/missing values
                if s is None:
                    issues.append({"type": "missing_s", "elem": g, "action": "reject"})
                    continue
                if not _is_finite(s):
                    issues.append({"type": "nonfinite_s", "elem": g, "action": "reject"})
                    continue
                if l is None:
                    issues.append({"type": "missing_length", "elem": g, "action": "reject"})
                    continue
                if not _is_finite(l):
                    issues.append({"type": "nonfinite_length", "elem": g, "action": "reject"})
                    continue
                if hdg is not None and not _is_finite(hdg):
                    issues.append({"type": "nonfinite_hdg", "elem": g, "action": "normalize"})
                    # We'll normalize later

                parsed.append({
                    "elem": g,
                    "s": s,
                    "length": l,
                    "hdg": hdg,
                })

            # If any rejectable issues, mark road as rejected
            reject_issues = [i for i in issues if i.get("action") == "reject"]
            if reject_issues:
                plan["roads"][rid] = {
                    "status": GeometryValidator.STATUS_REJECTED_REPAIR,
                    "issues": issues,
                    "actions": [],
                }
                continue

            # 1) Reorder by s
            parsed.sort(key=lambda d: d["s"])

            actions = []

            # 2) Remove zero/negative length geometries
            cleaned = []
            for d in parsed:
                if d["length"] <= GeometryValidator.MIN_SEG_LEN:
                    actions.append({
                        "type": "remove_zero_length",
                        "s": d["s"],
                        "elem": d["elem"],
                    })
                    issues.append(f"removed_zero_length_segment_at_s={d['s']}")
                else:
                    cleaned.append(d)
            parsed = cleaned

            if not parsed:
                plan["roads"][rid] = {
                    "status": "all_zero_length_removed",
                    "issues": issues,
                    "actions": actions,
                }
                continue

            # 3) Fix negative sOffsets
            last_s = parsed[0]["s"]
            for d in parsed[1:]:
                if d["s"] < last_s:
                    old_s = d["s"]
                    d["s"] = last_s + 0.001
                    actions.append({
                        "type": "fix_negative_sOffset",
                        "old_s": old_s,
                        "new_s": d["s"],
                        "elem": d["elem"],
                    })
                    issues.append("fixed_negative_sOffset")
                last_s = d["s"]

            # 4) Normalize headings
            for d in parsed:
                if d["hdg"] is not None and not _is_finite(d["hdg"]):
                    # Will be normalized to 0
                    actions.append({
                        "type": "normalize_hdg",
                        "old_hdg": d["hdg"],
                        "new_hdg": 0.0,
                        "elem": d["elem"],
                    })
                    d["hdg"] = 0.0
                    issues.append("normalized_nonfinite_heading")
                elif d["hdg"] is not None:
                    old_h = d["hdg"]
                    new_h = _norm_angle(d["hdg"])
                    if old_h != new_h:
                        d["hdg"] = new_h
                        actions.append({
                            "type": "normalize_heading",
                            "old_hdg": old_h,
                            "new_hdg": new_h,
                            "elem": d["elem"],
                        })
                        issues.append("normalized_heading")

            # 5) Curvature sanity: clamp extreme spirals
            for d in parsed:
                spiral = d["elem"].find("spiral")
                if spiral is not None:
                    cs = _safe_float(spiral.attrib.get("curvStart"))
                    ce = _safe_float(spiral.attrib.get("curvEnd"))

                    if cs is not None and (not _is_finite(cs) or abs(cs) > GeometryValidator.MAX_CURV):
                        old = cs
                        clamped = max(-GeometryValidator.MAX_CURV, min(cs, GeometryValidator.MAX_CURV))
                        actions.append({
                            "type": "clamp_curvStart",
                            "original": old,
                            "clamped": clamped,
                            "elem": d["elem"],
                        })
                        issues.append("clamped_curvStart")

                    if ce is not None and (not _is_finite(ce) or abs(ce) > GeometryValidator.MAX_CURV):
                        old = ce
                        clamped = max(-GeometryValidator.MAX_CURV, min(ce, GeometryValidator.MAX_CURV))
                        actions.append({
                            "type": "clamp_curvEnd",
                            "original": old,
                            "clamped": clamped,
                            "elem": d["elem"],
                        })
                        issues.append("clamped_curvEnd")

            # 6) Missing x,y,hdg backfill (plan only)
            for i in range(1, len(parsed)):
                prev = parsed[i - 1]
                cur = parsed[i]

                # Backfill x,y if missing
                if "x" not in cur["elem"].attrib or "y" not in cur["elem"].attrib:
                    if "x" in prev["elem"].attrib and "y" in prev["elem"].attrib:
                        try:
                            end = geometry_endpoint(prev["elem"])
                            actions.append({
                                "type": "backfill_xy",
                                "index": i,
                                "x": end.x,
                                "y": end.y,
                                "elem": cur["elem"],
                            })
                            issues.append(f"backfilled_xy_at_index={i}")
                        except (TypeError, ValueError):
                            # A malformed predecessor cannot safely provide a pose.
                            pass

                # Backfill hdg if missing - USE ENDPOINT HEADING for curved primitives
                if cur["hdg"] is None and prev["hdg"] is not None:
                    # Compute the actual endpoint heading of the previous geometry
                    try:
                        prev_end = geometry_endpoint(prev["elem"])
                        cur["hdg"] = prev_end.heading
                        actions.append({
                            "type": "backfill_hdg",
                            "index": i,
                            "value": cur["hdg"],
                            "elem": cur["elem"],
                        })
                        issues.append(f"backfilled_hdg_at_index={i}")
                    except (TypeError, ValueError):
                        # Fallback to previous geometry's start heading if endpoint fails
                        cur["hdg"] = prev["hdg"]
                        actions.append({
                            "type": "backfill_hdg_fallback",
                            "index": i,
                            "value": cur["hdg"],
                            "elem": cur["elem"],
                        })
                        issues.append(f"backfilled_hdg_fallback_at_index={i}")

            plan["roads"][rid] = {
                "status": GeometryValidator.STATUS_OK,
                "issues": issues,
                "actions": actions,
                "parsed": parsed,
            }

        return plan

    # -----------------------------------------------------------------
    # 3. APPLY REPAIRS (mutate XML based on plan)
    # -----------------------------------------------------------------
    @staticmethod
    def _apply_geometry_repairs(root: Element, plan_result: dict):
        """
        Apply planned repairs to XML.
        Mutates XML in-place.
        """
        apply_report = {"roads": {}}

        for road in root.findall(".//road"):
            rid = road.attrib.get("id", "UNKNOWN")
            road_plan = plan_result.get("roads", {}).get(rid, {})

            if road_plan.get("status") == GeometryValidator.STATUS_REJECTED_REPAIR:
                apply_report["roads"][rid] = {"status": GeometryValidator.STATUS_REJECTED_REPAIR}
                continue

            if road_plan.get("status") == "all_zero_length_removed":
                apply_report["roads"][rid] = {"status": "all_zero_length_removed"}
                continue

            actions = road_plan.get("actions", [])
            parsed = road_plan.get("parsed", [])
            plan_elem = road.find("./planView")

            if plan_elem is None:
                apply_report["roads"][rid] = {"status": "no_planView"}
                continue

            # Apply removal actions first (collect elements to remove)
            elements_to_remove = set()
            for action in actions:
                if action["type"] == "remove_zero_length":
                    elements_to_remove.add(action["elem"])

            # Actually remove from XML
            for elem in elements_to_remove:
                plan_elem.remove(elem)

            # Apply other mutations
            for action in actions:
                elem = action["elem"]
                if action["type"] == "fix_negative_sOffset":
                    elem.attrib["s"] = str(action["new_s"])
                    diff_log.add("geometry_validator", rid, {
                        "fix": "fixed_negative_sOffset", "old_s": action["old_s"], "new_s": action["new_s"]
                    })
                elif action["type"] == "normalize_heading" or action["type"] == "normalize_nonfinite_heading":
                    elem.attrib["hdg"] = str(action["new_hdg"])
                    diff_log.add("geometry_validator", rid, {
                        "fix": "normalized_heading", "old_hdg": action["old_hdg"], "new_hdg": action["new_hdg"]
                    })
                elif action["type"] == "clamp_curvStart":
                    spiral = elem.find("spiral")
                    if spiral is not None:
                        spiral.attrib["curvStart"] = str(action["clamped"])
                        diff_log.add("geometry_validator", rid, {
                            "fix": "clamped_curvStart", "original": action["original"], "clamped": action["clamped"]
                        })
                elif action["type"] == "clamp_curvEnd":
                    spiral = elem.find("spiral")
                    if spiral is not None:
                        spiral.attrib["curvEnd"] = str(action["clamped"])
                        diff_log.add("geometry_validator", rid, {
                            "fix": "clamped_curvEnd", "original": action["original"], "clamped": action["clamped"]
                        })
                elif action["type"] == "backfill_xy":
                    elem.attrib["x"] = str(action["x"])
                    elem.attrib["y"] = str(action["y"])
                    diff_log.add("geometry_validator", rid, {
                        "fix": "backfilled_xy", "index": action["index"], "x": action["x"], "y": action["y"]
                    })
                elif action["type"] == "backfill_hdg" or action["type"] == "backfill_hdg_fallback":
                    elem.attrib["hdg"] = str(action["value"])
                    diff_log.add("geometry_validator", rid, {
                        "fix": "backfilled_hdg", "index": action["index"], "value": action["value"]
                    })

            # Apply reordering by moving XML elements
            if parsed:
                # Remove all remaining geometries from planView and re-append in sorted order
                remaining_elems = {d["elem"] for d in parsed}
                for d in parsed:
                    if d["elem"] in plan_elem:
                        plan_elem.remove(d["elem"])

                # Re-append in parsed order (which is sorted by s)
                for d in parsed:
                    d["elem"].attrib["s"] = str(d["s"])
                    plan_elem.append(d["elem"])

            apply_report["roads"][rid] = {"status": GeometryValidator.STATUS_VALID_REPAIR}

        return apply_report

    # -----------------------------------------------------------------
    # Legacy method for backward compatibility
    # -----------------------------------------------------------------
    @staticmethod
    def _validate_road(road: Element, rid: str):
        """Legacy single-method validation - kept for compatibility."""
        plan_elem = road.find("./planView")
        if plan_elem is None:
            return {"status": "no_planView"}

        geoms = plan_elem.findall("geometry")
        if not geoms:
            return {"status": "empty"}

        # Parse
        parsed = []
        issues = []

        for g in geoms:
            s = _safe_float(g.attrib.get("s"))
            l = _safe_float(g.attrib.get("length"))
            hdg = _safe_float(g.attrib.get("hdg"))

            parsed.append({
                "elem": g,
                "s": s,
                "length": l,
                "hdg": hdg,
            })

        # Reorder by s (legacy: just sort list, doesn't reorder XML)
        parsed.sort(key=lambda d: d["s"])
        for d in parsed:
            d["elem"].attrib["s"] = str(d["s"])

        # Remove zero-length (legacy: doesn't remove from XML)
        cleaned = []
        for d in parsed:
            if (
                d["length"] is None
                or not math.isfinite(d["length"])
                or d["length"] <= GeometryValidator.MIN_SEG_LEN
            ):
                issues.append(f"removed_zero_length_segment_at_s={d['s']}")
                diff_log.add("geometry_validator", rid, {"fix": "removed_zero_length_segment", "s": d["s"]})
            else:
                cleaned.append(d)
        parsed = cleaned

        if not parsed:
            return {"status": "all_zero_length_removed", "issues": issues}

        # Fix negative sOffsets
        last_s = parsed[0]["s"]
        for d in parsed[1:]:
            if d["s"] < last_s:
                old_s = d["s"]
                d["s"] = last_s + 0.001
                d["elem"].attrib["s"] = str(d["s"])
                issues.append("fixed_negative_sOffset")
                diff_log.add("geometry_validator", rid, {"fix": "fixed_negative_sOffset", "old_s": old_s, "new_s": d["s"]})
            last_s = d["s"]

        # Normalize hdg
        for d in parsed:
            if d["hdg"] is not None:
                old_h = d["hdg"]
                d["hdg"] = _norm_angle(d["hdg"])
                d["elem"].attrib["hdg"] = str(d["hdg"])
                if old_h != d["hdg"]:
                    issues.append("normalized_heading")
                    diff_log.add("geometry_validator", rid, {"fix": "normalized_heading", "old_hdg": old_h, "new_hdg": d["hdg"]})

        # Clamp curvature
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
                    diff_log.add("geometry_validator", rid, {"fix": "clamped_curvStart", "original": old, "clamped": clamped})

                if ce is not None and (not math.isfinite(ce) or abs(ce) > GeometryValidator.MAX_CURV):
                    old = ce
                    clamped = max(-GeometryValidator.MAX_CURV, min(ce, GeometryValidator.MAX_CURV))
                    spiral.attrib["curvEnd"] = str(clamped)
                    issues.append("clamped_curvEnd")
                    diff_log.add("geometry_validator", rid, {"fix": "clamped_curvEnd", "original": old, "clamped": clamped})

        # Backfill x,y,hdg (legacy: uses previous start heading)
        for i in range(1, len(parsed)):
            prev = parsed[i - 1]
            cur = parsed[i]

            if "x" not in cur["elem"].attrib or "y" not in cur["elem"].attrib:
                if "x" in prev["elem"].attrib and "y" in prev["elem"].attrib:
                    try:
                        end = geometry_endpoint(prev["elem"])
                        dx, dy = end.x - _safe_float(prev["elem"].attrib["x"]), end.y - _safe_float(prev["elem"].attrib["y"])
                        cur["elem"].attrib["x"] = str(end.x)
                        cur["elem"].attrib["y"] = str(end.y)
                        issues.append(f"backfilled_xy_at_index={i}")
                        diff_log.add("geometry_validator", rid, {"fix": "backfilled_xy", "index": i, "px": prev["elem"].attrib["x"], "py": prev["elem"].attrib["y"], "dx": dx, "dy": dy})
                    except (TypeError, ValueError):
                        pass

            if cur["hdg"] is None and prev["hdg"] is not None:
                cur["hdg"] = prev["hdg"]
                cur["elem"].attrib["hdg"] = str(cur["hdg"])
                issues.append(f"backfilled_hdg_at_index={i}")
                diff_log.add("geometry_validator", rid, {"fix": "backfilled_hdg", "index": i, "value": cur["hdg"]})

        return {
            "status": "ok",
            "num_segments": len(parsed),
            "issues": issues,
        }
def canonical_horizontal_geometry_fingerprint(root) -> str:
    """Calculate canonical fingerprint of planView geometry at freeze."""
    import hashlib
    import xml.etree.ElementTree as ET
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
            # primitive
            prim = next(iter(geom), None)
            if prim is not None:
                h.update(prim.tag.encode())
                for kk, vv in sorted(prim.attrib.items()):
                    h.update(f"{kk}={vv}".encode())
    return h.hexdigest()
