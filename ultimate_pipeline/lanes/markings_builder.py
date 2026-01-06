import xml.etree.ElementTree as ET
from typing import Dict, Any, List


class MarkingBuilder:
    """
    CARLA-safe road markings for OpenDRIVE.

    Features:
      - Lane 0 → solid yellow centerline with <line> child
      - Left/right lanes → inner broken, outer solid
      - Only lanes with width records get markings
      - Only allowed lane *types* get markings
      - Per-road + per-lane disable switches
      - Summary helper for diagnostics / validation report
    """

    # Lane types that are allowed to receive markings
    ALLOWED_TYPES = {
        "driving", "shoulder", "biking", "bike",
        "stop", "mwyEntry", "mwyExit"
    }

    # Attribute values that mean "false" / "off"
    FALSE_VALUES = {"0", "false", "False", "no", "No", "off", "OFF"}

    # ------------------------------------------------------------
    #  PUBLIC PIPELINE API  (NEW + BACKWARD COMPAT)
    # ------------------------------------------------------------

    @staticmethod
    def add_basic_markings(root: ET.Element) -> None:
        """
        NEW pipeline entry point.
        Apply CARLA-safe markings to all roads.
        Respects per-road and per-lane disable flags.
        """
        for road in root.findall("road"):
            if MarkingBuilder._road_markings_disabled(road):
                continue
            MarkingBuilder._fix_road_markings(road)

    @staticmethod
    def add_basic(root: ET.Element) -> None:
        """
        BACKWARD-COMPAT alias for older pipeline code.

        Old API:
            MarkingBuilder.add_basic(root)

        Now simply calls the new add_basic_markings().
        """
        MarkingBuilder.add_basic_markings(root)

    @staticmethod
    def summarize_markings(root: ET.Element) -> Dict[str, Any]:
        """
        Returns a diagnostics dict with marking statistics.

        Example:
        {
          "total_marked_lanes": 532,
          "total_center_marks": 120,
          "by_color": {"white": 480, "yellow": 120},
          "by_type": {"solid": 300, "broken": 300}
        }
        """
        color_counts: Dict[str, int] = {}
        type_counts: Dict[str, int] = {}
        total_marked_lanes = 0
        total_center_marks = 0

        for road in root.findall("road"):
            for lane in road.findall(".//lane"):
                rms = lane.findall("roadMark")
                if not rms:
                    continue

                total_marked_lanes += 1

                # Count center vs non-center
                if lane.get("id") == "0":
                    total_center_marks += 1

                for rm in rms:
                    rtype = rm.get("type", "unknown")
                    rcolor = rm.get("color", "unknown")

                    type_counts[rtype] = type_counts.get(rtype, 0) + 1
                    color_counts[rcolor] = color_counts.get(rcolor, 0) + 1

        return {
            "total_marked_lanes": total_marked_lanes,
            "total_center_marks": total_center_marks,
            "by_color": color_counts,
            "by_type": type_counts,
        }

    # ------------------------------------------------------------
    #  INTERNAL HELPERS
    # ------------------------------------------------------------

    @staticmethod
    def _road_markings_disabled(road: ET.Element) -> bool:
        """
        Check <userData> for a 'disable_markings' flag:
            <userData>
               <vector name="disable_markings" value="true"/>
            </userData>
        """
        udata = road.find("userData")
        if udata is None:
            return False

        for vec in udata.findall("vector"):
            name = vec.get("name", "")
            if name != "disable_markings":
                continue
            val = vec.get("value", "").strip()
            if val.lower() in {"1", "true", "yes", "on"}:
                return True

        return False

    @staticmethod
    def _lane_markings_disabled(lane: ET.Element) -> bool:
        """
        Lane-local disable flag, e.g.:
            <lane id="1" mark="off" ...>
        or
            <lane id="1" markings="false" ...>
        """
        for attr in ("mark", "marks", "markings"):
            val = lane.get(attr)
            if val is None:
                continue
            if val in MarkingBuilder.FALSE_VALUES:
                return True
        return False

    @staticmethod
    def _get_lane_type(lane: ET.Element) -> str:
        """
        OpenDRIVE stores type sometimes as a child <type>, sometimes as attribute.
        We support both and normalize to a simple string.
        """
        # 1) Attribute
        attr_type = lane.get("type")
        if attr_type:
            return attr_type

        # 2) Child element <type type="driving" ... />
        type_elem = lane.find("type")
        if type_elem is not None:
            t = type_elem.get("type")
            if t:
                return t

        return "none"

    @staticmethod
    def _has_width_records(lane: ET.Element) -> bool:
        return bool(lane.findall("width"))

    # ------------------------------------------------------------
    #  PER-ROAD MARKING LOGIC
    # ------------------------------------------------------------

    @staticmethod
    def _fix_road_markings(road: ET.Element) -> None:
        """
        Internal per-road marking logic (enhanced).
        """
        lanes_elem = road.find("lanes")
        if lanes_elem is None:
            return

        for section in lanes_elem.findall("laneSection"):
            left_lanes: List[Any] = []
            right_lanes: List[Any] = []
            center_lane: ET.Element | None = None

            # ----- center lane (id = 0) -----
            center_elem = section.find("center")
            if center_elem is not None:
                for lane in center_elem.findall("lane"):
                    if lane.get("id") == "0":
                        center_lane = lane

            # ----- left lanes -----
            left_elem = section.find("left")
            if left_elem is not None:
                for lane in left_elem.findall("lane"):
                    try:
                        lid = int(lane.get("id", ""))
                    except Exception:
                        continue
                    left_lanes.append((lid, lane))

            # ----- right lanes -----
            right_elem = section.find("right")
            if right_elem is not None:
                for lane in right_elem.findall("lane"):
                    try:
                        lid = int(lane.get("id", ""))
                    except Exception:
                        continue
                    right_lanes.append((lid, lane))

            # Sort lanes by ID (inner → outer)
            left_lanes.sort(key=lambda x: x[0])                 # 1,2,3,...
            right_lanes.sort(key=lambda x: x[0], reverse=True)  # -1,-2,-3,...

            # ----- centerline marking -----
            if center_lane is not None and not MarkingBuilder._lane_markings_disabled(center_lane):
                MarkingBuilder._apply_center_mark(center_lane)

            # ----- right side markings -----
            for i, (_, lane) in enumerate(right_lanes):
                if MarkingBuilder._lane_markings_disabled(lane):
                    continue

                lane_type = MarkingBuilder._get_lane_type(lane)
                if lane_type not in MarkingBuilder.ALLOWED_TYPES:
                    continue

                if not MarkingBuilder._has_width_records(lane):
                    continue

                is_outer = (i == len(right_lanes) - 1)
                m_type = "solid" if is_outer else "broken"
                MarkingBuilder._apply_lane_mark(lane, m_type, "white")

            # ----- left side markings -----
            for i, (_, lane) in enumerate(left_lanes):
                if MarkingBuilder._lane_markings_disabled(lane):
                    continue

                lane_type = MarkingBuilder._get_lane_type(lane)
                if lane_type not in MarkingBuilder.ALLOWED_TYPES:
                    continue

                if not MarkingBuilder._has_width_records(lane):
                    continue

                is_outer = (i == len(left_lanes) - 1)
                m_type = "solid" if is_outer else "broken"
                MarkingBuilder._apply_lane_mark(lane, m_type, "white")

    @staticmethod
    def fix_road_markings(road: ET.Element) -> None:
        """
        BACKWARD-COMPAT alias for older code that called:
            MarkingBuilder.fix_road_markings(road)
        """
        MarkingBuilder._fix_road_markings(road)

    # ------------------------------------------------------------
    #  APPLY MARKINGS (CARLA-SAFE)
    # ------------------------------------------------------------

    @staticmethod
    def _apply_center_mark(lane: ET.Element) -> None:
        """
        Lane 0: solid yellow centerline.
        CARLA-safe:
          - has <line> child
          - laneChange="none"
          - rule="noPassing"
        """
        # Remove existing marks
        for rm in list(lane.findall("roadMark")):
            lane.remove(rm)

        rm = ET.SubElement(lane, "roadMark", {
            "sOffset": "0.0",
            "type": "solid",
            "weight": "standard",
            "color": "yellow",
            "width": "0.15",
            "laneChange": "none",
        })

        ET.SubElement(rm, "line", {
            "length": "0.0",
            "space": "0.0",
            "tOffset": "0.0",
            "sOffset": "0.0",
            "rule": "noPassing",
            "width": "0.15",
        })

    @staticmethod
    def _apply_lane_mark(lane: ET.Element, m_type: str, color: str) -> None:
        """
        Apply marking to left/right lanes.

        CARLA rules enforced:
          - solid → laneChange="none"
          - broken → laneChange="both"
          - always has <line> child
        """
        lane_type = MarkingBuilder._get_lane_type(lane)
        if lane_type not in MarkingBuilder.ALLOWED_TYPES:
            return

        if not MarkingBuilder._has_width_records(lane):
            return

        # Remove old marks
        for rm in list(lane.findall("roadMark")):
            lane.remove(rm)

        lane_change = "both" if m_type == "broken" else "none"
        rule = "caution" if m_type == "broken" else "noPassing"

        rm = ET.SubElement(lane, "roadMark", {
            "sOffset": "0.0",
            "type": m_type,
            "weight": "standard",
            "color": color,
            "width": "0.15",
            "laneChange": lane_change,
        })

        ET.SubElement(rm, "line", {
            "length": "3.0" if m_type == "broken" else "0.0",
            "space": "6.0" if m_type == "broken" else "0.0",
            "tOffset": "0.0",
            "sOffset": "0.0",
            "rule": rule,
            "width": "0.15",
        })
