import xml.etree.ElementTree as ET


class LaneDebugger:
    @staticmethod
    def assert_valid_lane_sections(xodr_path: str) -> None:
        tree = ET.parse(xodr_path)
        root = tree.getroot()

        bad = []
        for road in root.findall("road"):
            lanes = road.find("lanes")
            if lanes is None:
                bad.append(road.get("id"))
                continue
            if not lanes.findall("laneSection"):
                bad.append(road.get("id"))

        if bad:
            raise RuntimeError(
                f"Invalid laneSections in roads: {bad[:10]}"
                + (" ..." if len(bad) > 10 else "")
            )

        print("✓ LaneDebugger: laneSections structurally valid.")
