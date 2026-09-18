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
        Read the OSM sidewalk tag from:
          1) <userData><vector key="sidewalk" value="both/left/right/no"/>
          2) <userData><vectorObject key="sidewalk" value="..."/> (alternate schema)
          3) road attribute osm:sidewalk (written by some converters)
        Returns one of: "both", "left", "right", "no", or None (→ heuristic fallback).
        """
        # 1) Standard userData vector
        user_data = road.find("userData")
        if user_data is not None:
            for vec in user_data.findall("vector"):
                key = vec.get("key", "")
                val = vec.get("value", "")
                if key == "sidewalk" and val:
                    return val.lower().strip()
            # 2) vectorObject variant (some converters use this)
            for vec in user_data.findall("vectorObject"):
                key = vec.get("key", "")
                val = vec.get("value", "")
                if key == "sidewalk" and val:
                    return val.lower().strip()

        # 3) Some converters write osm:sidewalk as a road-level attribute
        osm_sw = road.get("osm:sidewalk") or road.get("sidewalk")
        if osm_sw:
            return osm_sw.lower().strip()

        return None

    @staticmethod
    def _road_has_driving_lane(road: ET.Element) -> bool:
        lanes = road.find("lanes")
        if lanes is None:
            return False
        for lane in lanes.findall(".//lane"):
            if lane.get("type") == "driving":
                return True
        return False

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
            "level": "false",
        })
        # Minimal width - CARLA will mesh it
        ET.SubElement(lane, "width", {
            "sOffset": "0.0",
            "a": "2.0",
            "b": "0.0",
            "c": "0.0",
            "d": "0.0",
        })

        # Give CARLA something explicit to draw/boundary-mark
        ET.SubElement(lane, "roadMark", {
            "sOffset": "0.0",
            "type": "solid",
            "weight": "standard",
            "color": "standard",
            "laneChange": "none",
        })
        return lane

    @staticmethod
    def _count_side_lanes(lanes_elem: ET.Element) -> tuple[int, int]:
        n_left = 0
        n_right = 0
        for lane_section in lanes_elem.findall("laneSection"):
            left = lane_section.find("left")
            right = lane_section.find("right")
            if left is not None:
                n_left += len(left.findall("lane"))
            if right is not None:
                n_right += len(right.findall("lane"))
        return n_left, n_right

    @staticmethod
    def count_sidewalk_lanes(root: ET.Element) -> int:
        count = 0
        for lane in root.findall(".//lane"):
            if lane.get("type") == "sidewalk":
                count += 1
        return count

    @staticmethod
    def add_sidewalks(root: ET.Element, default_both_sides: bool = True) -> int:
        """
        Add sidewalk lanes to roads that should have them.

        Strategy:
        - Look at OSM hint (if present).
        - Otherwise, if road has 'urban' or low speedLimit -> add both sides.
        - Never overwrite existing sidewalk lanes.
        """
        added = 0
        for road in root.findall("road"):
            # Skip junction connectors; sidewalk meshing there is often ugly and unstable
            if road.get("junction", "-1") != "-1":
                continue
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
                # Better heuristic: if it has a driving lane, it likely deserves sidewalks.
                if SidewalkBuilder._road_has_driving_lane(road):
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
                        added += 1

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
                        added += 1

        return added
