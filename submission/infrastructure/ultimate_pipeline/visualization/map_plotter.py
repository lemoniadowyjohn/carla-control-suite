#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import math
import xml.etree.ElementTree as ET
import numpy as np

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import ArrowStyle, FancyArrowPatch, Circle


class MapPlotter:
    """
    Pipeline-grade OpenDRIVE visualizer with:
        - Curvature/arc rendering
        - Lane boundary lines
        - Junction color coding
        - Roundabout highlighting (NEW)
        - Overlap detection
        - Road direction arrows
        - PNG exporting (non-blocking)
    """

    # ===========================
    # Geometry helpers
    # ===========================

    @staticmethod
    def _sample_geometry(geom, step=1.0):
        """Turn planView geometry into sampled (x, y) points."""
        try:
            x0 = float(geom.get("x"))
            y0 = float(geom.get("y"))
            hdg = float(geom.get("hdg"))
            length = float(geom.get("length"))
        except:
            return [], []

        gtype = list(geom)[0].tag if list(geom) else "line"

        xs, ys = [], []

        if gtype == "line":
            for s in range(0, int(length) + 1, int(step)):
                xs.append(x0 + s * math.cos(hdg))
                ys.append(y0 + s * math.sin(hdg))
            return xs, ys

        if gtype == "arc":
            arc = geom.find("arc")
            curvature = float(arc.get("curvature"))
            radius = 1.0 / curvature if curvature != 0 else 1e9

            for s in range(0, int(length) + 1, int(step)):
                heading = hdg + s * curvature
                xs.append(x0 + radius * (math.sin(heading) - math.sin(hdg)))
                ys.append(y0 - radius * (math.cos(heading) - math.cos(hdg)))
            return xs, ys

        if gtype == "spiral":
            spiral = geom.find("spiral")
            curvStart = float(spiral.get("curvStart"))
            curvEnd = float(spiral.get("curvEnd"))
            dk = (curvEnd - curvStart) / length

            x, y = x0, y0
            heading = hdg
            curvature = curvStart

            for _ in range(int(length)):
                xs.append(x)
                ys.append(y)

                heading += curvature
                curvature += dk

                x += math.cos(heading)
                y += math.sin(heading)

            return xs, ys

        return [], []

    # ===========================
    # Lane / direction helpers
    # ===========================

    @staticmethod
    def _draw_lane_boundaries(ax, lane_section):
        """
        Draws lane boundaries in road-local coordinates (s, lateral).
        NOTE: This is not yet projected to global (X, Y).
        Currently disabled to avoid visual confusion on global maps.
        """
        pass

    @staticmethod
    def _draw_direction_arrow(ax, xs, ys):
        if len(xs) < 5:
            return
        idx = len(xs) // 2
        x0, y0 = xs[idx], ys[idx]
        x1, y1 = xs[idx + 1], ys[idx + 1]

        arrow = FancyArrowPatch(
            (x0, y0), (x1, y1),
            arrowstyle=ArrowStyle.Simple(head_length=4, head_width=2),
            color="green", linewidth=0.8, alpha=0.7
        )
        ax.add_patch(arrow)

    # ===========================
    # Roundabout helpers (NEW)
    # ===========================

    @staticmethod
    def _road_is_roundabout(road: ET.Element) -> bool:
        rtype = road.find("type")
        if rtype is not None and rtype.get("type") == "roundabout":
            return True
        return False

    @staticmethod
    def _draw_roundabout_center(ax, road: ET.Element):
        geoms = road.findall("./planView/geometry")
        if not geoms:
            return

        # compute approximate center using arc curvature
        g0 = geoms[0]
        arc = g0.find("arc")
        if arc is None:
            return

        try:
            curvature = float(arc.get("curvature"))
            if curvature == 0:
                return

            R = abs(1.0 / curvature)

            # approximate center using tangent offset
            x = float(g0.get("x"))
            y = float(g0.get("y"))
            hdg = float(g0.get("hdg"))

            cx = x - R * math.sin(hdg)
            cy = y + R * math.cos(hdg)

            c = Circle((cx, cy), 2.0, color="magenta", alpha=0.3)
            ax.add_patch(c)

            circ = Circle((cx, cy), R, edgecolor="magenta",
                          facecolor="none", linestyle="--", linewidth=1.0)
            ax.add_patch(circ)
        except Exception:
            pass

    # ===========================
    # Overlaps
    # ===========================

    @staticmethod
    def _detect_overlaps(road_geoms):
        """
        Efficiently detect overlapping roads using pre-calculated bounding boxes and numpy.
        """
        overlaps = []
        roads = list(road_geoms.keys())

        # 1. Pre-process to numpy and bounds
        processed = {}
        for rid in roads:
            xs, ys = road_geoms[rid]
            if not xs:
                continue
            xa = np.array(xs, dtype=np.float32)
            ya = np.array(ys, dtype=np.float32)
            processed[rid] = {
                "x": xa, "y": ya,
                "xmin": xa.min(), "xmax": xa.max(),
                "ymin": ya.min(), "ymax": ya.max()
            }

        # 2. Compare pairs
        p_roads = list(processed.keys())
        for i in range(len(p_roads)):
            r1 = p_roads[i]
            d1 = processed[r1]
            for j in range(i + 1, len(p_roads)):
                r2 = p_roads[j]
                d2 = processed[r2]

                # Bounding box check
                if (d1["xmax"] < d2["xmin"] or d2["xmax"] < d1["xmin"] or
                    d1["ymax"] < d2["ymin"] or d2["ymax"] < d1["ymin"]):
                    continue

                # Point-wise check
                n = min(len(d1["x"]), len(d2["x"]))
                if n < 2:
                    continue

                diff_x = np.abs(d1["x"][:n] - d2["x"][:n])
                diff_y = np.abs(d1["y"][:n] - d2["y"][:n])
                matches = (diff_x < 0.4) & (diff_y < 0.4)
                if np.sum(matches) > 0.7 * n:
                    overlaps.append((r1, r2))

        return overlaps

    # ===========================
    # Public API
    # ===========================

    @staticmethod
    def save_preview(xodr_path, out_dir, stage="preview"):
        if not os.path.exists(xodr_path):
            return

        try:
            tree = ET.parse(xodr_path)
            root = tree.getroot()
        except Exception:
            return

        # Explicitly use non-interactive Agg backend to avoid crashes on Windows
        import matplotlib
        matplotlib.use('Agg', force=True)
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(12, 12))
        ax.set_title(f"{stage}: {os.path.basename(xodr_path)}")
        ax.set_xlabel("X (m)")
        ax.set_ylabel("Y (m)")
        ax.axis("equal")

        road_geoms = {}

        for road in root.findall("road"):
            rid = road.get("id")
            junction_id = road.get("junction", "")
            is_roundabout = MapPlotter._road_is_roundabout(road)

            if is_roundabout:
                color = "magenta"
            elif junction_id and junction_id != "-1":
                color = "blue"
            else:
                color = "black"

            xs_all, ys_all = [], []
            for geom in road.findall("./planView/geometry"):
                xs, ys = MapPlotter._sample_geometry(geom)
                if xs:
                    xs_all += xs
                    ys_all += ys

            if not xs_all:
                continue

            road_geoms[rid] = (xs_all, ys_all)
            ax.plot(xs_all, ys_all, color=color, linewidth=0.8, alpha=0.9)

            # Direction arrows (skip for extremely short roads)
            if len(xs_all) > 2:
                MapPlotter._draw_direction_arrow(ax, xs_all, ys_all)

            if is_roundabout:
                MapPlotter._draw_roundabout_center(ax, road)

        # Highlight overlaps
        try:
            overlaps = MapPlotter._detect_overlaps(road_geoms)
            for r1, r2 in overlaps:
                xs, ys = road_geoms[r1]
                ax.plot(xs, ys, color="red", linewidth=1.2, alpha=0.9)
                xs, ys = road_geoms[r2]
                ax.plot(xs, ys, color="darkred", linewidth=1.2, alpha=0.9)
        except Exception as e:
            print(f"⚠ Overlap detection failed: {e}")

        # Save PNG
        out_img = os.path.join(out_dir, f"map_preview_{stage}.png")
        try:
            plt.savefig(out_img, dpi=180)
            print(f"🖼 Saved map preview (enhanced) → {out_img}")
        except Exception as e:
            print(f"❌ Failed to save preview: {e}")
        finally:
            plt.close(fig)
            plt.clf()
