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


    @staticmethod
    def full_scan(xodr_path: str) -> None:
        """Run all available lane diagnostics.

        Historically some dev tooling called `LaneDebugger.full_scan()`.
        This repo only required a structural laneSection check for most
        experiments, so we keep this as a convenience wrapper.
        """
        LaneDebugger.assert_valid_lane_sections(xodr_path)
