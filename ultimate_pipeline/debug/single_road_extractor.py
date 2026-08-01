# ultimate_pipeline/debug/single_road_extractor.py

import xml.etree.ElementTree as ET
import os

class SingleRoadExtractor:

    @staticmethod
    def extract(input_path: str, road_id: str, output_path: str):
        print(f"🔍 Extracting road {road_id} from: {input_path}")

        if not os.path.exists(input_path):
            raise FileNotFoundError(input_path)

        tree = ET.parse(input_path)
        root = tree.getroot()

        # ---------- Create new root ----------
        new_root = ET.Element("OpenDRIVE")

        # ---------- Header ----------
        header = root.find("header")
        if header is None:
            raise RuntimeError("❌ Input XODR missing <header>")

        # copy header (deep copy)
        new_root.append(SingleRoadExtractor._clone(header))

        # ---------- georeference safety ----------
        geo = new_root.find(".//geoReference")
        if geo is None:
            geo = ET.SubElement(new_root.find("header"), "geoReference")
            geo.text = "+proj=utm +zone=32 +datum=WGS84 +units=m +no_defs"

        # ---------- find the road ----------
        road = root.find(f"./road[@id='{road_id}']")
        if road is None:
            raise RuntimeError(f"❌ Road ID {road_id} not found in file.")

        new_root.append(SingleRoadExtractor._clone(road))

        # ---------- Controllers (if linked) ----------
        for ctrl in root.findall("controller"):
            for cont_road in ctrl.findall("control"):
                if cont_road.get("road") == road_id:
                    new_root.append(SingleRoadExtractor._clone(ctrl))
                    break

        # ---------- Junctions (if connected) ----------
        for junc in root.findall("junction"):
            for conn in junc.findall("connection"):
                if (conn.get("incomingRoad") == road_id or
                    conn.get("connectingRoad") == road_id):
                    new_root.append(SingleRoadExtractor._clone(junc))
                    break

        # ---------- Save ----------
        out_tree = ET.ElementTree(new_root)
        out_tree.write(output_path, encoding="utf-8", xml_declaration=True)

        print(f"✓ Saved single-road XODR → {output_path}")

    @staticmethod
    def _clone(elem: ET.Element) -> ET.Element:
        """Deep copy of an XML node."""
        new = ET.Element(elem.tag, elem.attrib)
        for child in list(elem):
            new.append(SingleRoadExtractor._clone(child))
        if elem.text:
            new.text = elem.text
        return new
