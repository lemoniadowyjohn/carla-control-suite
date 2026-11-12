"""Diagnose why the real Ingolstadt OSM <-> manual XODR correspondence finds 0 matches."""

import sys
import xml.etree.ElementTree as ET

from safe_xml import safe_parse
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

XODR = REPO / "campaigns/ingolstadt_cooked_perception_v1/source/manual/Grid0828.xodr"
OSM = REPO / "campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm"

# V104 security finding: parse through the safe XML boundary.
root = safe_parse(str(XODR))
header = root.find("header")
print("=== XODR header attrs ===")
for k, v in (header.attrib if header is not None else {}).items():
    print(f"  {k} = {v}")
if header is not None:
    geo = header.find("geoReference")
    print("  geoReference.text =", repr(geo.text if geo is not None else None))
    off = header.find("offset")
    print("  offset:", off.attrib if off is not None else None)

print()
print("=== first 3 roads: id / first geometry x,y ===")
for road in root.findall("./road")[:3]:
    g = road.find("./planView/geometry")
    print(
        "  road", road.get("id"),
        "name", road.get("name"),
        "len", road.get("length"),
        "x", g.get("x") if g is not None else None,
        "y", g.get("y") if g is not None else None,
    )

print()
print("=== OSM way sample (first structural way) ===")
from ultimate_pipeline.enrichment.osm_meta_index import (
    extract_structural_osm_lane_metadata_ways,
    project_positioned_osm_metadata_ways,
)

ways = extract_structural_osm_lane_metadata_ways(str(OSM))
print("structural ways:", len(ways))
for w in ways[:3]:
    print("  way", w.get("id"), "name", (w.get("metadata") or {}).get("name"),
          "geom[:2]", (w.get("geometry") or [])[:2])

projected = project_positioned_osm_metadata_ways(ways, root)
print()
print("projected ways:", len(projected))
for w in projected[:3]:
    print("  way", w.get("id"), "name", (w.get("metadata") or {}).get("name"),
          "geom[:2]", (w.get("geometry") or [])[:2])

print()
print("=== XODR road coordinate range (first 200 roads) ===")
xs = []
ys = []
for road in root.findall("./road")[:200]:
    g = road.find("./planView/geometry")
    if g is None:
        continue
    try:
        xs.append(float(g.get("x")))
        ys.append(float(g.get("y")))
    except (TypeError, ValueError):
        pass
if xs:
    print(f"  x [{min(xs):.1f}, {max(xs):.1f}]  y [{min(ys):.1f}, {max(ys):.1f}]")

print()
print("=== projected OSM coordinate range ===")
pxs = []
pys = []
for w in projected:
    for pt in (w.get("geometry") or []):
        try:
            pxs.append(float(pt[0]))
            pys.append(float(pt[1]))
        except (TypeError, ValueError, IndexError):
            pass
if pxs:
    print(f"  x [{min(pxs):.1f}, {max(pxs):.1f}]  y [{min(pys):.1f}, {max(pys):.1f}]")
