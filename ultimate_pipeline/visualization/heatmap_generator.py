# ultimate_pipeline/visualization/heatmap_generator.py

import json
import math
import os
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw


class HeatmapGenerator:
    """
    Draw a top-down heatmap over the road graph, using continuity_debug.json:

    For each road:
      - max_gap (meters)
      - max_hdg (radians)
      - max_len (meters)

    Severity combines these and maps to a color:
      green → mild
      yellow → medium
      red → severe
    """

    @staticmethod
    def _severity_from_metrics(max_gap, max_hdg, max_len):
        # Soft normalizations – tweak if needed
        gap_norm = 5.0         # 5m gap is "bad"
        hdg_norm = math.radians(15.0)
        len_norm = 800.0       # very long segments

        s_gap = min(1.0, max_gap / gap_norm) if gap_norm > 0 else 0.0
        s_hdg = min(1.0, max_hdg / hdg_norm) if hdg_norm > 0 else 0.0
        s_len = min(1.0, max_len / len_norm) if len_norm > 0 else 0.0

        # Max of the three: any one can be bad
        return max(s_gap, s_hdg, s_len)

    @staticmethod
    def _color_from_severity(s):
        """
        s in [0,1] → RGB:
          0.0 ≈ green
          0.5 ≈ yellow
          1.0 ≈ red
        """
        s = max(0.0, min(1.0, s))
        r = int(255 * s)
        g = int(255 * (1.0 - s))
        b = 0
        return r, g, b

    @staticmethod
    def _endpoint(x, y, hdg, length, geo_elem):
        """
        Simple endpoint integrator for visualization.
        Handles <arc>; treats spiral/poly3 as straight line.
        """
        arc = geo_elem.find("arc")
        if arc is not None:
            try:
                k = float(arc.get("curvature", "0"))
            except Exception:
                k = 0.0

            if abs(k) < 1e-9:
                return (
                    x + length * math.cos(hdg),
                    y + length * math.sin(hdg),
                    hdg
                )

            hdg2 = hdg + k * length
            x2 = x + (math.sin(hdg2) - math.sin(hdg)) / k
            y2 = y - (math.cos(hdg2) - math.cos(hdg)) / k
            return x2, y2, hdg2

        # spiral / poly3 / default → line
        return (
            x + length * math.cos(hdg),
            y + length * math.sin(hdg),
            hdg
        )

    @staticmethod
    def run(xodr_path, output_png, debug_json="continuity_debug.json"):
        """
        Generate a PNG heatmap of continuity anomalies.

        Args:
            xodr_path: path to XODR file.
            output_png: path to output PNG.
            debug_json: continuity_debug.json from MeshContinuityRepairer.
        """
        if not os.path.exists(xodr_path):
            print(f"❌ XODR not found: {xodr_path}")
            return

        if not os.path.exists(debug_json):
            print(f"⚠ continuity_debug.json not found at {debug_json} – heatmap skipped.")
            return

        try:
            with open(debug_json, "r", encoding="utf-8") as f:
                debug = json.load(f)
        except Exception as e:
            print(f"⚠ Failed to read {debug_json}: {e}")
            return

        tree = ET.parse(xodr_path)
        root = tree.getroot()

        # 1) Compute bounding box
        xs, ys = [], []
        for road in root.findall("road"):
            for g in road.findall("./planView/geometry"):
                try:
                    xs.append(float(g.get("x", 0.0)))
                    ys.append(float(g.get("y", 0.0)))
                except Exception:
                    continue

        if not xs or not ys:
            print("⚠ No geometry found in XODR – cannot build heatmap.")
            return

        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)

        dx = maxx - minx
        dy = maxy - miny

        if dx <= 0 or dy <= 0:
            print("⚠ Degenerate bounding box – heatmap skipped.")
            return

        # 2) Choose image size / scale
        max_pixels = 4096  # clamp for sanity
        scale = min(max_pixels / dx, max_pixels / dy)
        pad = 20

        width = int(dx * scale) + 2 * pad
        height = int(dy * scale) + 2 * pad

        # 3) Helper: world → image coordinates
        def world_to_img(wx, wy):
            ix = int((wx - minx) * scale) + pad
            # invert Y for image coords
            iy = height - (int((wy - miny) * scale) + pad)
            return ix, iy

        # 4) Create base image
        img = Image.new("RGB", (width, height), (0, 0, 0))
        draw = ImageDraw.Draw(img)

        # First, draw roads faintly as background
        bg_color = (40, 40, 40)

        for road in root.findall("road"):
            geoms = list(road.findall("./planView/geometry"))
            if not geoms:
                continue

            geoms.sort(key=lambda g: float(g.get("s", "0.0")))
            pts = []

            # simple chain using geometry base points only
            for g in geoms:
                try:
                    gx = float(g.get("x", 0.0))
                    gy = float(g.get("y", 0.0))
                except Exception:
                    continue
                pts.append(world_to_img(gx, gy))

            if len(pts) >= 2:
                draw.line(pts, fill=bg_color, width=1)

        # 5) Overlay anomaly-colored lines per road
        for road in root.findall("road"):
            rid = road.get("id", "?")

            info = debug.get(rid)
            if not isinstance(info, dict):
                # might come as string keys from json
                info = debug.get(str(rid), {})

            max_gap = float(info.get("max_gap", 0.0)) if info else 0.0
            max_hdg = float(info.get("max_hdg", 0.0)) if info else 0.0
            max_len = float(info.get("max_len", 0.0)) if info else 0.0

            severity = HeatmapGenerator._severity_from_metrics(
                max_gap, max_hdg, max_len
            )

            if severity <= 0.01:
                # road is essentially clean → draw only background
                continue

            color = HeatmapGenerator._color_from_severity(severity)

            geoms = list(road.findall("./planView/geometry"))
            if len(geoms) < 1:
                continue

            try:
                geoms.sort(key=lambda g: float(g.get("s", "0.0")))
            except Exception:
                pass

            # more detailed polyline using endpoints
            pts = []
            # anchor at first geometry start
            g0 = geoms[0]
            try:
                x0 = float(g0.get("x", 0.0))
                y0 = float(g0.get("y", 0.0))
                hdg0 = float(g0.get("hdg", 0.0))
                L0 = float(g0.get("length", 0.001))
            except Exception:
                continue

            pts.append(world_to_img(x0, y0))

            px, py, ph = x0, y0, hdg0
            pl = L0

            for geo in geoms:
                # we don’t trust geometry.x/y fully; we propagate by integration
                try:
                    L = float(geo.get("length", 0.001))
                except Exception:
                    L = 0.001

                ex, ey, eh = HeatmapGenerator._endpoint(px, py, ph, pl, geo)
                pts.append(world_to_img(ex, ey))

                px, py, ph, pl = ex, ey, eh, L

            if len(pts) >= 2:
                draw.line(pts, fill=color, width=2)

        img.save(output_png)
        print(f"🔥 Heatmap written → {output_png}")
