# ultimate_pipeline/visualization/lane_overlay.py

import math
import os
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw


class LaneOverlay:
    """
    Lane-aware centerline overlay.

    Approximation:
      - Compute number of drivable lanes per road (left+right).
      - Draw road centerline colored by lane count:
           1–2 lanes: bluish
           3–4 lanes: green/yellow
           >4 lanes: red
    """

    DRIVING_TYPES = {
        "driving", "mwyEntry", "mwyExit", "bus", "biking", "bike"
    }

    @staticmethod
    def _count_driving_lanes(road: ET.Element) -> int:
        count = 0

        lanes_elem = road.find("lanes")
        if lanes_elem is None:
            return 0

        for side_tag in ("left", "right"):
            side = lanes_elem.find(side_tag)
            if side is None:
                continue
            for lane in side.findall("lane"):
                ltype = lane.get("type", "")
                if ltype in LaneOverlay.DRIVING_TYPES:
                    count += 1

        return count

    @staticmethod
    def _color_for_lane_count(n: int):
        if n <= 0:
            return (90, 90, 90)   # gray
        if n <= 2:
            return (80, 160, 255)  # blue-ish
        if n <= 4:
            return (80, 220, 120)  # green-ish
        if n <= 6:
            return (255, 220, 80)  # yellow-ish
        return (255, 80, 80)       # red for monsters

    @staticmethod
    def _endpoint(x, y, hdg, length, geo_elem):
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

        # spiral/poly3/line fallback
        return (
            x + length * math.cos(hdg),
            y + length * math.sin(hdg),
            hdg
        )

    @staticmethod
    def run(xodr_path, output_png):
        if not os.path.exists(xodr_path):
            print(f"❌ XODR not found: {xodr_path}")
            return

        tree = ET.parse(xodr_path)
        root = tree.getroot()

        xs, ys = [], []
        for road in root.findall("road"):
            for g in road.findall("./planView/geometry"):
                try:
                    xs.append(float(g.get("x", 0.0)))
                    ys.append(float(g.get("y", 0.0)))
                except Exception:
                    continue

        if not xs or not ys:
            print("⚠ No geometry in map for lane overlay.")
            return

        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        dx, dy = maxx - minx, maxy - miny

        max_pixels = 4096
        scale = min(max_pixels / max(dx, 1e-3), max_pixels / max(dy, 1e-3))
        pad = 20

        width = int(dx * scale) + 2 * pad
        height = int(dy * scale) + 2 * pad

        def world_to_img(wx, wy):
            ix = int((wx - minx) * scale) + pad
            iy = height - (int((wy - miny) * scale) + pad)
            return ix, iy

        img = Image.new("RGB", (width, height), (10, 10, 10))
        draw = ImageDraw.Draw(img)

        # faint background
        for road in root.findall("road"):
            geoms = list(road.findall("./planView/geometry"))
            if len(geoms) < 2:
                continue
            try:
                geoms.sort(key=lambda g: float(g.get("s", "0.0")))
            except Exception:
                pass

            pts = []
            for g in geoms:
                try:
                    x = float(g.get("x", 0.0))
                    y = float(g.get("y", 0.0))
                except Exception:
                    continue
                pts.append(world_to_img(x, y))

            if len(pts) >= 2:
                draw.line(pts, fill=(60, 60, 60), width=1)

        # lane-colored centerlines
        for road in root.findall("road"):
            lane_count = LaneOverlay._count_driving_lanes(road)
            color = LaneOverlay._color_for_lane_count(lane_count)

            geoms = list(road.findall("./planView/geometry"))
            if len(geoms) < 1:
                continue
            try:
                geoms.sort(key=lambda g: float(g.get("s", "0.0")))
            except Exception:
                pass

            g0 = geoms[0]
            try:
                x0 = float(g0.get("x", 0.0))
                y0 = float(g0.get("y", 0.0))
                hdg0 = float(g0.get("hdg", 0.0))
                L0 = float(g0.get("length", 0.001))
            except Exception:
                continue

            pts = [world_to_img(x0, y0)]
            px, py, ph, pl = x0, y0, hdg0, L0

            for g in geoms:
                try:
                    L = float(g.get("length", 0.001))
                except Exception:
                    L = 0.001
                ex, ey, eh = LaneOverlay._endpoint(px, py, ph, pl, g)
                pts.append(world_to_img(ex, ey))
                px, py, ph, pl = ex, ey, eh, L

            if len(pts) >= 2:
                width_px = 1 + min(4, lane_count // 2)
                draw.line(pts, fill=color, width=width_px)

        img.save(output_png)
        print(f"🛣 Lane overlay written → {output_png}")
