
import xml.etree.ElementTree as ET
def repair(xodr_in, xodr_out, default_width=3.5):
    tree = ET.parse(xodr_in); root = tree.getroot()
    for road in root.findall("road"):
        for lane in road.findall(".//lane"):
            if lane.find("width") is None:
                w = ET.SubElement(lane, "width")
                w.set("sOffset","0"); w.set("a",str(default_width))
                w.set("b","0"); w.set("c","0"); w.set("d","0")
    tree.write(xodr_out, encoding="utf-8", xml_declaration=True)
