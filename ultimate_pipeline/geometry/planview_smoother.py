# ultimate_pipeline/geometry/planview_smoother.py

import math
import xml.etree.ElementTree as ET

from ultimate_pipeline.core.xodr_sanitizer import _safe_float


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

            for geo in geoms[1:]:
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

                    geo.set("hdg", f"{new_h:.8f}")
                    prev_h = new_h
                    smoothed += 1
                else:
                    prev_h = h

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

                can_merge = (
                    same_type
                    and length < min_length
                    and (prev_len + length) < max_merged_length
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
        of each geometry from the end of the previous one.
        """
        fixed = 0

        for road in root.findall("road"):
            plan = road.find("planView")
            if plan is None:
                continue

            geoms = list(plan.findall("geometry"))
            if len(geoms) < 2:
                continue

            geoms.sort(key=lambda g: float(g.get("s", "0")))

            prev = geoms[0]
            x = float(prev.get("x", "0"))
            y = float(prev.get("y", "0"))
            hdg = float(prev.get("hdg", "0"))

            for g in geoms[1:]:
                g.set("x", f"{x:.8f}")
                g.set("y", f"{y:.8f}")
                g.set("hdg", f"{hdg:.8f}")

                L = float(g.get("length", "0"))

                # conservative: line-only forward integration
                x += L * math.cos(hdg)
                y += L * math.sin(hdg)

                fixed += 1

        return fixed

