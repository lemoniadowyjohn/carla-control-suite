import xml.etree.ElementTree as ET, os

src = r"/cities/ingolstadt/clean_ingolstadt_merged_georef.xodr"
dst = src.replace(".xodr", "_subset_50.xodr")

tree = ET.parse(src)
root = tree.getroot()
roads = root.findall("road")

subset = ET.Element("OpenDRIVE")
subset.append(root.find("header"))

for r in roads[:50]:
    subset.append(r)

ET.ElementTree(subset).write(dst, encoding="utf-8", xml_declaration=True)
print(f"✅ subset saved: {dst} with {len(roads[:50])} roads")
