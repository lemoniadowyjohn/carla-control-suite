# ultimate_pipeline/enrichment/sidewalk_builder.py

import xml.etree.ElementTree as ET
from typing import Optional


class SidewalkBuilder:
    """
    Adds or normalizes sidewalk lanes based on:
    - road category (optional)
    - existing lane structure
    - optional OSM hints (sidewalk=both/left/right)

    This works purely at XODR level and is CARLA-safe.
    """

    @staticmethod
    def _get_osm_sidewalk_hint(road: ET.Element) -> Optional[str]:
        """
        If your converter writes OSM tags into <userData> or <type>/<link>,
        you can read them here. For now it's just a stub that always returns None.
        """
        # Example if you had <userData><vector key="sidewalk" value="both"/></userData>
        user_data = road.find("userData")
        if user_data is None:
            return None

        for vec in user_data.findall("vector"):
            key = vec.get("key")
            val = vec.get("value")
            if key == "sidewalk":
                return val
        return None

    @staticmethod
    def _ensure_side_section(lanes_elem: ET.Element, side: str) -> ET.Element:
        """
        Ensure <left> or <right> exists under <lanes>.
        """
        sec = lanes_elem.find(side)
        if sec is None:
            sec = ET.SubElement(lanes_elem, side)
        return sec

    @staticmethod
    def _create_sidewalk_lane(parent: ET.Element, lane_id: int) -> ET.Element:
        lane = ET.SubElement(parent, "lane", {
            "id": str(lane_id),
            "type": "sidewalk",
            "level": "true",
        })
        # Minimal width – CARLA will mesh it
        ET.SubElement(lane, "width", {
            "sOffset": "0.0",
            "a": "2.0",
            "b": "0.0",
            "c": "0.0",
            "d": "0.0",
        })
        return lane

    @staticmethod
    def add_sidewalks(root: ET.Element, default_both_sides: bool = True) -> None:
        """
        Add sidewalk lanes to roads that should have them.

        Strategy:
        - Look at OSM hint (if present).
        - Otherwise, if road has 'urban' or low speedLimit → add both sides.
        - Never overwrite existing sidewalk lanes.
        """
        for road in root.findall("road"):
            lanes_elem = road.find("lanes")
            if lanes_elem is None:
                continue

            hint = SidewalkBuilder._get_osm_sidewalk_hint(road)

            # Decide which sides get sidewalks
            add_left = False
            add_right = False

            if hint == "both":
                add_left = add_right = True
            elif hint == "left":
                add_left = True
            elif hint == "right":
                add_right = True
            elif default_both_sides:
                # very simple heuristic: if road has more than 1 lane per side,
                # assume it's an urban-ish road.
                left = lanes_elem.find("left")
                right = lanes_elem.find("right")
                n_left = len(left.findall("lane")) if left is not None else 0
                n_right = len(right.findall("lane")) if right is not None else 0
                if n_left + n_right >= 2:
                    add_left = add_right = True

            if not (add_left or add_right):
                continue

            for lane_section in lanes_elem.findall("laneSection"):
                # Left side
                if add_left:
                    left = lane_section.find("left")
                    left = left if left is not None else ET.SubElement(lane_section, "left")
                    # Find outermost lane id on left side
                    existing_ids = []
                    for lane in left.findall("lane"):
                        try:
                            existing_ids.append(int(lane.get("id", "1")))
                        except ValueError:
                            pass
                    new_id = (max(existing_ids) + 1) if existing_ids else 1
                    # only add if no existing sidewalk
                    if not any(l.get("type") == "sidewalk" for l in left.findall("lane")):
                        SidewalkBuilder._create_sidewalk_lane(left, new_id)

                # Right side (negative ids!)
                if add_right:
                    right = lane_section.find("right")
                    right = right if right is not None else ET.SubElement(lane_section, "right")
                    existing_ids = []
                    for lane in right.findall("lane"):
                        try:
                            existing_ids.append(int(lane.get("id", "-1")))
                        except ValueError:
                            pass
                    new_id = (min(existing_ids) - 1) if existing_ids else -1
                    if not any(l.get("type") == "sidewalk" for l in right.findall("lane")):
                        SidewalkBuilder._create_sidewalk_lane(right, new_id)
