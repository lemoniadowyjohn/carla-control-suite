import xml.etree.ElementTree as ET
import math
import os


class XODRCropper:
    """
    Extracts a bounding-box subset of an XODR for fast CARLA preview.
    Does NOT modify the original network, only filters roads.
    """

    @staticmethod
    def crop(input_xodr: str, output_xodr: str,
             cx: float, cy: float, r: float = 300.0) -> None:
        """
        Crop around center (cx, cy) with radius r (meters).
        """

        tree = ET.parse(input_xodr)
        root = tree.getroot()

        roads = root.findall("road")

        keep = []
        for road in roads:
            planview = road.find("planView")
            if planview is None:
                continue

            inside = False
            for geom in planview.findall("geometry"):
                x = float(geom.get("x", "0"))
                y = float(geom.get("y", "0"))

                if math.hypot(x - cx, y - cy) <= r:
                    inside = True
                    break

            if inside:
                keep.append(road)

        # remove all roads, then re-add kept
        for r_node in roads:
            root.remove(r_node)
        for r_node in keep:
            root.append(r_node)

        tree.write(output_xodr, encoding="utf-8", xml_declaration=True)
        print(f"🗂 XODR crop created → {output_xodr} (roads kept: {len(keep)})")
