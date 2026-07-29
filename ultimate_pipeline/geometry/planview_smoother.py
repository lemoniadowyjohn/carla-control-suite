# ultimate_pipeline/geometry/planview_smoother.py
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from ultimate_pipeline.core.xodr_sanitizer import _safe_float
from ultimate_pipeline.quality.check_geometric_continuity import (
    recompute_geometry_starts_chained_inplace,
)


def _line_end_xy(g: ET.Element) -> tuple[float, float] | None:
    """Return (x_end, y_end) for a LINE geometry element, or None for other types."""
    for child in g:
        if child.tag != "line":
            return None
        break
    else:
        # no child found → line element absent
        return None
    try:
        x0 = float(g.get("x", "0"))
        y0 = float(g.get("y", "0"))
        hdg = float(g.get("hdg", "0"))
        length = float(g.get("length", "0"))
        return (x0 + length * math.cos(hdg), y0 + length * math.sin(hdg))
    except Exception:
        return None


# Spatial gap larger than this means the next segment is an intentional
# planView discontinuity ("anchor point") and must NOT be merged away.
_SPATIAL_GAP_ANCHOR_THRESHOLD_M: float = 0.5

# Geometries shorter than this are considered "small" for the purposes of
# terminal-anchor detection (they pin road endpoint contactPoints).
_SMALL_GEOMETRY_THRESHOLD_M: float = 0.5


def _is_terminal_anchor_geometry(road_elem, geom_index: int, geom_elem, geoms: list, threshold_m: float = None) -> bool:
    """Return True if this geometry should be protected from heading smoothing.

    A geometry is a terminal anchor if it is the first or last in the road AND
    it is short (length <= threshold) — these short endpoint geometries pin
    the road's predecessor/successor contactPoints and must not have their
    heading altered by smoothing.

    Also protected: any geometry that is adjacent to a spatial discontinuity
    (gap > _SPATIAL_GAP_ANCHOR_THRESHOLD_M) relative to the previous geometry,
    because that discontinuity was preserved intentionally by the merge guards.
    """
    if threshold_m is None:
        threshold_m = _SMALL_GEOMETRY_THRESHOLD_M

    n = len(geoms)
    if n == 0:
        return False

    is_first = (geom_index == 0)
    is_last  = (geom_index == n - 1)

    # Only terminal positions are protected
    if not (is_first or is_last):
        return False

    # Short terminal geometry → anchor
    try:
        length = float(geom_elem.get("length", 0.0))
    except (TypeError, ValueError):
        length = 0.0
    if length <= threshold_m:
        return True

    # Spatial discontinuity adjacent to this terminal geometry:
    # if prev→this gap > threshold, this geometry was placed as an anchor
    if is_last and n >= 2:
        prev = geoms[n - 2]
        try:
            px, py = _line_end_xy(prev)
            cx = float(geom_elem.get("x", 0.0))
            cy = float(geom_elem.get("y", 0.0))
            if math.hypot(cx - px, cy - py) > _SPATIAL_GAP_ANCHOR_THRESHOLD_M:
                return True
        except Exception:
            pass

    if is_first and n >= 2:
        nxt = geoms[1]
        try:
            ex, ey = _line_end_xy(geom_elem)
            nx = float(nxt.get("x", 0.0))
            ny = float(nxt.get("y", 0.0))
            if math.hypot(nx - ex, ny - ey) > _SPATIAL_GAP_ANCHOR_THRESHOLD_M:
                return True
        except Exception:
            pass

    return False


class PlanViewSmoother:
    """
    PlanView utilities to prevent visual tearing & broken intersections.

    Responsibilities:
    -----------------
    1) smooth_heading_jumps:
       - softens violent heading jumps between consecutive <geometry> entries
       - keeps heading continuous within a road

    2) merge_small_geometries:
       - merges very short geometry segments into their predecessor
       - only merges segments of the same type (line/arc/spiral/poly3)
       - respects a maximum merged length

    3) merge_short_segments:
       - aggressively removes tiny sub-meter fragments
       - focuses on eliminating DEM/SUMO micro-segments

    4) recompute_s_values:
       - reorders segments by s
       - recomputes s starting at 0
       - recomputes road length

    5) clamp_curvature:
       - clamps absurd curvature values in <arc curvature="">
    """

    # ------------------------------------------------------------------
    # Helper: classify geometry type
    # ------------------------------------------------------------------
    @staticmethod
    def _geom_type(g: ET.Element) -> str:
        if g.find("arc") is not None:
            return "arc"
        if g.find("spiral") is not None:
            return "spiral"
        if g.find("poly3") is not None:
            return "poly3"
        return "line"

    # ------------------------------------------------------------------
    # 1) Heading smoothing
    # ------------------------------------------------------------------
    @staticmethod
    def smooth_heading_jumps(root: ET.Element, threshold_deg: float = 12.0) -> int:
        """
        Detect and soften heading discontinuities between consecutive geometries.

        Parameters
        ----------
        root : ET.Element
            Root <OpenDRIVE> element.
        threshold_deg : float
            Maximum allowed heading jump (in degrees) before smoothing kicks in.

        Returns
        -------
        int
            Number of geometry pairs where heading was adjusted.
        """
        threshold = math.radians(threshold_deg)
        smoothed = 0
        considered = 0
        skipped_anchor = 0

        for road in root.findall("road"):
            plan_view = road.find("planView")
            if plan_view is None:
                continue

            geoms = list(plan_view.findall("geometry"))
            if len(geoms) < 2:
                continue

            # Sort geometries by s to ensure deterministic order
            try:
                geoms.sort(key=lambda g: _safe_float(g.get("s", "0"), 0.0))
            except Exception:
                pass

            prev = geoms[0]
            try:
                prev_h = float(prev.get("hdg", "0.0"))
            except Exception:
                prev_h = 0.0

            for i, geo in enumerate(geoms[1:], start=1):
                considered += 1
                try:
                    h = float(geo.get("hdg", "0.0"))
                except Exception:
                    h = prev_h

                # Normalize diff to [-pi, pi]
                diff = h - prev_h
                while diff > math.pi:
                    diff -= 2 * math.pi
                while diff < -math.pi:
                    diff += 2 * math.pi

                # If jump too large → blend both sides toward each other
                if abs(diff) > threshold:
                    new_h = (h + prev_h) / 2.0

                    # Make sure new_h is in a reasonable 2π neighborhood
                    while new_h - prev_h > math.pi:
                        new_h -= 2 * math.pi
                    while new_h - prev_h < -math.pi:
                        new_h += 2 * math.pi

                    # Guard 1: never modify the last geometry's heading.
                    # The last geometry's hdg determines the road endpoint direction
                    # used for predecessor/successor link connectivity. Modifying it
                    # displaces the endpoint and creates 10–60 m link gaps.
                    # Guard 2: never modify a terminal-anchor geometry's heading.
                    # Short endpoint geometries (and those adjacent to spatial gaps)
                    # pin the road's predecessor/successor contactPoints.
                    if geo is not geoms[-1] and not _is_terminal_anchor_geometry(road, i, geo, geoms):
                        geo.set("hdg", f"{new_h:.8f}")
                        smoothed += 1
                    else:
                        skipped_anchor += 1
                    prev_h = new_h
                else:
                    prev_h = h

        import logging as _logging
        _logging.getLogger(__name__).debug(
            "smooth_heading_jumps: considered=%d smoothed=%d skipped_anchor=%d",
            considered, smoothed, skipped_anchor,
        )
        return smoothed

    # ------------------------------------------------------------------
    # 2) Merge tiny geometries by type
    # ------------------------------------------------------------------
    @staticmethod
    def merge_small_geometries(
        root: ET.Element,
        min_length: float = 0.10,
        max_merged_length: float = 300.0,
        *,
        min_len: float | None = None,
    ) -> int:
        """
        Merge very short geometry segments into their predecessor, but only when:

        - they share the same geometry type (line/arc/spiral/poly3)
        - the resulting merged length stays below max_merged_length
        - the segment length is below min_length

        Supports both:
            merge_small_geometries(root, min_length=0.05)
        and:
            merge_small_geometries(root, min_len=0.05)

        Returns
        -------
        int
            Number of segments merged.
        """
        # Compatibility: min_len overrides min_length if provided
        if min_len is not None:
            min_length = min_len

        merged = 0

        for road in root.findall("road"):
            plan = road.find("planView")
            if plan is None:
                continue

            geoms = list(plan.findall("geometry"))
            if len(geoms) < 2:
                continue

            # Sort for deterministic behaviour
            geoms.sort(key=lambda g: _safe_float(g.get("s", "0"), 0.0))

            new_geoms = [geoms[0]]

            for g in geoms[1:]:
                length = _safe_float(g.get("length", "0"), 0.0)
                if length <= 0.0:
                    length = 0.001
                    g.set("length", f"{length:.6f}")

                prev = new_geoms[-1]
                prev_len = _safe_float(prev.get("length", "0"), 0.0)

                same_type = (
                    PlanViewSmoother._geom_type(prev)
                    == PlanViewSmoother._geom_type(g)
                )

                # Guard: never merge across a planView spatial discontinuity.
                # If the candidate segment starts far from where the previous
                # segment ends, it is an intentional anchor point that pins the
                # road's endpoint for link connectivity.  Merging it away would
                # destroy that anchor and produce 100s–1000s m link gaps.
                spatial_ok = True
                if same_type and length < min_length:
                    prev_end = _line_end_xy(prev)
                    if prev_end is not None:
                        try:
                            gx = float(g.get("x", "0"))
                            gy = float(g.get("y", "0"))
                            gap = math.hypot(prev_end[0] - gx, prev_end[1] - gy)
                            if gap > _SPATIAL_GAP_ANCHOR_THRESHOLD_M:
                                spatial_ok = False
                        except Exception:
                            pass

                can_merge = (
                    same_type
                    and length < min_length
                    and (prev_len + length) < max_merged_length
                    and spatial_ok
                )

                if can_merge:
                    prev.set("length", f"{prev_len + length:.6f}")
                    merged += 1
                else:
                    new_geoms.append(g)

            # Replace geometry list in the original <planView>
            plan.clear()
            for g in new_geoms:
                plan.append(g)

        print(f"✓ PlanViewSmoother: merged {merged} tiny geometry segments.")
        return merged

    # ------------------------------------------------------------------
    # 3) Aggressive micro-fragment pruning
    # ------------------------------------------------------------------
    @staticmethod
    def merge_short_segments(
        root: ET.Element,
        min_len: float = 0.25,
        *,
        min_length: float | None = None,
    ) -> int:
        """
        Remove extremely short segments (< min_len) by merging them into
        their predecessor, regardless of type. Use this *after*
        merge_small_geometries to remove pathological leftovers.

        Supports both:
            merge_short_segments(root, min_len=0.25)
        and:
            merge_short_segments(root, min_length=0.25)

        Parameters
        ----------
        root : ET.Element
            Root <OpenDRIVE> element.
        min_len : float
            Minimum allowed geometry length in meters.
        min_length : float | None
            Alternative keyword for the same parameter (compatibility).

        Returns
        -------
        int
            Number of short segments removed.
        """
        # Compatibility: min_length overrides min_len if provided
        if min_length is not None:
            min_len = min_length

        removed = 0

        for road in root.findall("road"):
            plan_view = road.find("planView")
            if plan_view is None:
                continue

            geoms = list(plan_view.findall("geometry"))
            if len(geoms) < 2:
                continue

            # Sort by s for safety
            geoms.sort(key=lambda g: _safe_float(g.get("s", "0"), 0.0))

            i = 0
            while i < len(geoms) - 1:
                g1 = geoms[i]
                g2 = geoms[i + 1]

                length = _safe_float(g2.get("length", "0"), 0.0)

                if length < min_len:
                    # Guard: never merge across a spatial discontinuity anchor.
                    spatial_ok = True
                    g1_end = _line_end_xy(g1)
                    if g1_end is not None:
                        try:
                            gx = float(g2.get("x", "0"))
                            gy = float(g2.get("y", "0"))
                            gap = math.hypot(g1_end[0] - gx, g1_end[1] - gy)
                            if gap > _SPATIAL_GAP_ANCHOR_THRESHOLD_M:
                                spatial_ok = False
                        except Exception:
                            pass

                    if not spatial_ok:
                        i += 1
                        continue

                    # extend previous geometry length
                    prev_len = _safe_float(g1.get("length", "0"), 0.0)
                    g1.set("length", f"{prev_len + length:.6f}")

                    # remove geometry g2
                    plan_view.remove(g2)
                    geoms.pop(i + 1)
                    removed += 1
                    continue  # re-check new neighbor

                i += 1

        if removed > 0:
            print(f"✂️ PlanViewSmoother: removed {removed} ultra-short segments.")
        return removed

    # ------------------------------------------------------------------
    # 4) Recompute s-values & road length
    # ------------------------------------------------------------------
    @staticmethod
    def recompute_s_values(root: ET.Element) -> None:
        """
        Recompute s-coordinates for all <geometry> elements within each road,
        ensuring:

        - geometries are ordered by s
        - s starts at 0
        - s increases monotonically by length
        - road length is updated accordingly
        """
        for road in root.findall("road"):
            plan = road.find("planView")
            if plan is None:
                continue

            geoms = list(plan.findall("geometry"))
            if not geoms:
                continue

            # Sort by existing s for determinism
            geoms.sort(key=lambda g: _safe_float(g.get("s", "0"), 0.0))

            # Reattach in sorted order
            plan.clear()
            for g in geoms:
                plan.append(g)

            s_acc = 0.0
            for g in geoms:
                g.set("s", f"{s_acc:.8f}")
                L = _safe_float(g.get("length", "0"), 0.001)
                if L <= 0.0:
                    L = 0.001
                    g.set("length", f"{L:.8f}")
                s_acc += L

            # Update road length
            road.set("length", f"{s_acc:.8f}")

    # ------------------------------------------------------------------
    # 5) Curvature clamp
    # ------------------------------------------------------------------
    @staticmethod
    def clamp_curvature(root: ET.Element, max_curv: float) -> int:
        """
        Clamp unrealistic curvature values in <geometry><arc curvature="">.

        Parameters
        ----------
        root : ET.Element
            Root <OpenDRIVE> element.
        max_curv : float
            Maximum allowed absolute curvature.

        Returns
        -------
        int
            Number of curvature entries clamped.
        """
        clamped = 0

        for road in root.findall("road"):
            pv = road.find("planView")
            if pv is None:
                continue

            for geom in pv.findall("geometry"):
                arc = geom.find("arc")
                if arc is None:
                    continue

                curv_s = arc.get("curvature")
                if curv_s is None:
                    continue

                try:
                    curv = float(curv_s)
                except Exception:
                    continue

                if abs(curv) > max_curv:
                    new = max_curv if curv > 0 else -max_curv
                    arc.set("curvature", f"{new:.6f}")
                    clamped += 1

        return clamped

    # ------------------------------------------------------------------
    # 6) Recompute geometry start poses (continuity fix)
    # ------------------------------------------------------------------
    @staticmethod
    def recompute_geometry_starts(root: ET.Element) -> int:
        """
        Force perfect geometric continuity by recomputing x/y/hdg
        of each geometry from the exact end pose of the previous one.
        """
        return int(recompute_geometry_starts_chained_inplace(root))
