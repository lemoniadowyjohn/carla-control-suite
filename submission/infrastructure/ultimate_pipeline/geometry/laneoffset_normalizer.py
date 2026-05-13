# ultimate_pipeline/geometry/laneoffset_normalizer.py

import xml.etree.ElementTree as ET
from typing import List

from ultimate_pipeline.core.xodr_sanitizer import _safe_float  # you already use this in mesh_continuity_repairer


class LaneOffsetNormalizer:
    """
    Robust laneOffset cleanup:

    - For each road:
        * sort laneOffset by s
        * clamp s into [0, road_length]
        * ensure first laneOffset starts at s=0
        * enforce continuity between segments (a at boundary)
        * clamp absurd offsets to a safe range
    """

    MAX_ABS_OFFSET = 15.0  # meters, sanity clamp

    @staticmethod
    def _sort_offsets(road: ET.Element) -> List[ET.Element]:
        lo_parent = road.find("lanes")
        if lo_parent is None:
            return []

        offsets = list(lo_parent.findall("laneOffset"))
        if not offsets:
            return []

        offsets.sort(key=lambda o: _safe_float(o.get("s", "0.0"), 0.0))

        # rewrite in sorted order
        for o in list(lo_parent.findall("laneOffset")):
            lo_parent.remove(o)
        for o in offsets:
            lo_parent.append(o)

        return offsets

    @staticmethod
    def _eval_poly(a: float, b: float, c: float, d: float, ds: float) -> float:
        return a + b * ds + c * ds * ds + d * ds * ds * ds

    @staticmethod
    def normalize(root: ET.Element):
        for road in root.findall("road"):
            total_len = _safe_float(road.get("length", "0.0"), 0.0)
            if total_len <= 0.0:
                continue

            lanes_elem = road.find("lanes")
            if lanes_elem is None:
                continue

            offsets = LaneOffsetNormalizer._sort_offsets(road)

            # If no laneOffsets → create a simple zero offset
            if not offsets:
                lo = ET.SubElement(lanes_elem, "laneOffset", {
                    "s": "0.0",
                    "a": "0.0",
                    "b": "0.0",
                    "c": "0.0",
                    "d": "0.0",
                })
                continue

            # clamp s in [0, L] and clean coefficients
            for o in offsets:
                s = _safe_float(o.get("s", "0.0"), 0.0)
                s = max(0.0, min(s, max(0.0, total_len - 0.001)))
                o.set("s", f"{s:.8f}")

                a = _safe_float(o.get("a", "0.0"), 0.0)
                b = _safe_float(o.get("b", "0.0"), 0.0)
                c = _safe_float(o.get("c", "0.0"), 0.0)
                d = _safe_float(o.get("d", "0.0"), 0.0)

                # clamp insane offsets
                if abs(a) > LaneOffsetNormalizer.MAX_ABS_OFFSET:
                    a = 0.0

                o.set("a", f"{a:.8f}")
                o.set("b", f"{b:.8f}")
                o.set("c", f"{c:.8f}")
                o.set("d", f"{d:.8f}")

            # ensure first offset starts at 0
            first = offsets[0]
            first.set("s", "0.0")

            # continuity: make segment i start where i-1 ended (value-wise)
            for i in range(1, len(offsets)):
                prev = offsets[i - 1]
                curr = offsets[i]

                s_prev = _safe_float(prev.get("s", "0.0"), 0.0)
                s_curr = _safe_float(curr.get("s", "0.0"), 0.0)

                a_p = _safe_float(prev.get("a", "0.0"), 0.0)
                b_p = _safe_float(prev.get("b", "0.0"), 0.0)
                c_p = _safe_float(prev.get("c", "0.0"), 0.0)
                d_p = _safe_float(prev.get("d", "0.0"), 0.0)

                ds = max(0.0, s_curr - s_prev)
                offset_at_boundary = LaneOffsetNormalizer._eval_poly(a_p, b_p, c_p, d_p, ds)

                # fix current 'a' to continue from previous end
                curr.set("a", f"{offset_at_boundary:.8f}")


def normalize_junction_laneoffsets(
    root: ET.Element, *, max_abs_a: float = 0.5
) -> dict:
    """
    Deterministically neutralize suspicious junction laneOffset polynomials.

    For roads with junction != -1:
    - Inspect the first <laneOffset>.
    - If |a| > max_abs_a, set a=b=c=d=0.0.
    """
    limit = float(max_abs_a)
    offenders = []
    num_checked = 0
    max_abs_before = 0.0
    max_abs_after = 0.0

    for road in root.findall("road"):
        junction_id = road.get("junction")
        if junction_id is None or str(junction_id).strip() == "-1":
            continue
        num_checked += 1
        lanes_elem = road.find("lanes")
        if lanes_elem is None:
            continue
        offsets = list(lanes_elem.findall("laneOffset"))
        if not offsets:
            continue
        first = offsets[0]
        old_a = _safe_float(first.get("a", "0.0"), 0.0)
        max_abs_before = max(max_abs_before, abs(old_a))
        if abs(old_a) > limit:
            first.set("a", "0.0")
            first.set("b", "0.0")
            first.set("c", "0.0")
            first.set("d", "0.0")
            offenders.append(
                {
                    "road_id": str(road.get("id", "")),
                    "junction_id": str(junction_id),
                    "old_a": float(old_a),
                    "new_a": 0.0,
                    "action": "zeroed",
                }
            )

    num_remaining = 0
    for road in root.findall("road"):
        junction_id = road.get("junction")
        if junction_id is None or str(junction_id).strip() == "-1":
            continue
        lanes_elem = road.find("lanes")
        if lanes_elem is None:
            continue
        first = lanes_elem.find("laneOffset")
        if first is None:
            continue
        a_val = _safe_float(first.get("a", "0.0"), 0.0)
        max_abs_after = max(max_abs_after, abs(a_val))
        if abs(a_val) > limit:
            num_remaining += 1

    offenders.sort(
        key=lambda row: (str(row.get("road_id", "")), str(row.get("junction_id", "")))
    )
    return {
        "ok": bool(num_remaining == 0),
        "num_checked": int(num_checked),
        "num_fixed": int(len(offenders)),
        "num_remaining_violations": int(num_remaining),
        "max_abs_a_before": float(max_abs_before),
        "max_abs_a_after": float(max_abs_after),
        "max_abs_a_limit": float(limit),
        "offenders": offenders,
    }
