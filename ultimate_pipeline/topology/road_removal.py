# SAFE RoadRemoval — preserves all roads

import xml.etree.ElementTree as ET

class RoadRemoval:
    @staticmethod
    def remove(root: ET.Element, road_ids):
        print("⚠ SAFE MODE: RoadRemoval.remove() requested but ignored.")
        print("⚠ No roads removed.\n")
        return 0
