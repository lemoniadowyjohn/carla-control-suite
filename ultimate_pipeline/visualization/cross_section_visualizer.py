# ultimate_pipeline/visualization/cross_section_visualizer.py

import math
import os
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw


class CrossSectionVisualizer:
    """
    Draws a simple per-road cross-section strip:

      |<----left lanes----|center|----right lanes---->|

    Each road becomes one row in the image, built from the
    FIRST laneSection only (good enough for global sanity checks).
    """

    # lane type → color
    LANE_COLORS = {
        "driving": (80, 200, 120),
        "biking": (80, 160, 255),
        "bike": (80, 160, 255),
        "bus": (255, 180, 80),
        "shoulder": (120, 120, 120),
        "parking": (160, 160, 160),
        "sidewalk": (200, 200, 200),
    }

    @staticmethod
    def _lane_color(ltype: str, is_left: bool):
        base = CrossSectionVisualizer.LANE_COLORS.get(ltype, (140, 140, 140))
        if is_left:
            return base
        # tint right lanes slightly different
        r, g, b = base
        return (min(255, int(r * 1.1)), g, b)

    @staticmethod
    def _sample_section(road: ET.Element):
        """
        Returns (left_lanes, right_lanes) where each is a list of (width, type).
        Uses the first laneSection in the road.
        """

        lanes_elem = road.find("lanes")
        if lanes_elem is None:
            return [], []

        # choose first laneSection by s
        sections = list(lanes_elem.findall("laneSection"))
        if not sections:
            return [], []

        try:
            sections.sort(key=lambda s: float(s.get("s", "0.0")))
        except Exception:
            pass
        sec = sections[0]

        left_lanes = []
        right_lanes = []

        left = sec.find("left")
        if left is not None:
            for lane in left.findall("lane"):
                ltype = lane.get("type", "driving")
                # pick first width segment
                w_elem = lane.find("width")
                if w_elem is None:
                    continue
                try:
                    w = float(w_elem.get("a", "0.0"))
                except Exception:
                    w = 0.0
                if w <= 0:
                    continue
                left_lanes.append((w, ltype))

        right = sec.find("right")
        if right is not None:
            for lane in right.findall("lane"):
                ltype = lane.get("type", "driving")
                w_elem = lane.find("width")
                if w_elem is None:
                    continue
                try:
                    w = float(w_elem.get("a", "0.0"))
                except Exception:
                    w = 0.0
                if w <= 0:
                    continue
                right_lanes.append((w, ltype))

        # sort: center-near first
        left_lanes = list(left_lanes)          # already from center outward
        right_lanes = list(right_lanes)        # usually center outward

        return left_lanes, right_lanes

    @staticmethod
    def run(xodr_path, out_png, max_roads=200):
        if not os.path.exists(xodr_path):
            print(f"❌ XODR not found: {xodr_path}")
            return

        tree = ET.parse(xodr_path)
        root = tree.getroot()

        roads = list(root.findall("road"))
        if not roads:
            print("⚠ No roads for cross-section visualizer.")
            return

        roads = roads[:max_roads]

        # layout
        row_h = 18
        pad_x = 40
        pad_y = 20
        img_w = 800
        img_h = pad_y * 2 + row_h * len(roads)

        img = Image.new("RGB", (img_w, img_h), (15, 15, 15))
        draw = ImageDraw.Draw(img)

        for idx, road in enumerate(roads):
            rid = road.get("id", "?")
            y_top = pad_y + idx * row_h
            y_bot = y_top + row_h - 4

            left_lanes, right_lanes = CrossSectionVisualizer._sample_section(road)

            # compute total half-widths for scaling
            left_total = sum(w for w, _ in left_lanes)
            right_total = sum(w for w, _ in right_lanes)
            max_half = max(left_total, right_total, 1e-3)

            # scale factor: largest half-width maps to ~ (img_w - 2*pad_x)/2
            half_pixels = (img_w - 2 * pad_x) / 2.0
            scale = half_pixels / max_half

            cx = img_w // 2

            # center reference line
            draw.line((cx, y_top, cx, y_bot), fill=(200, 200, 200))

            # LEFT side (negative X): from center outward
            x_left = cx
            for w, ltype in left_lanes:
                px = w * scale
                x0 = int(x_left - px)
                x1 = int(x_left)
                color = CrossSectionVisualizer._lane_color(ltype, is_left=True)
                draw.rectangle((x0, y_top, x1, y_bot), fill=color)
                x_left = x0

            # RIGHT side (positive X): from center outward
            x_right = cx
            for w, ltype in right_lanes:
                px = w * scale
                x0 = int(x_right)
                x1 = int(x_right + px)
                color = CrossSectionVisualizer._lane_color(ltype, is_left=False)
                draw.rectangle((x0, y_top, x1, y_bot), fill=color)
                x_right = x1

            # road ID label
            label = f"road {rid} (L={left_total:.1f}m R={right_total:.1f}m)"
            draw.text((5, y_top + 2), label, fill=(220, 220, 220))

        img.save(out_png)
        print(f"📊 Cross-section visualizer written → {out_png}")
