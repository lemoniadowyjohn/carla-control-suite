from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.tiling.tile_extractor import TileExtractor


def _write_test_xodr(path: Path, georef: str) -> None:
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header", revMajor="1", revMinor="4", name="src")
    geo = ET.SubElement(header, "geoReference")
    geo.text = georef

    road = ET.SubElement(root, "road", id="1", length="20", junction="-1", type="town")
    plan = ET.SubElement(road, "planView")
    ET.SubElement(plan, "geometry", s="0", x="678000.0", y="5403000.0", hdg="0", length="10")
    ET.SubElement(plan, "geometry", s="10", x="678010.0", y="5403010.0", hdg="0", length="10")

    lanes = ET.SubElement(road, "lanes")
    lane_section = ET.SubElement(lanes, "laneSection", s="0")
    ET.SubElement(ET.SubElement(lane_section, "center"), "lane", id="0", type="none", level="false")
    right = ET.SubElement(lane_section, "right")
    lane = ET.SubElement(right, "lane", id="-1", type="driving", level="false")
    ET.SubElement(lane, "width", sOffset="0", a="3", b="0", c="0", d="0")

    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_tile_extractor_preserves_full_parent_georeference(tmp_path: Path) -> None:
    src = tmp_path / "source.xodr"
    tiles_dir = tmp_path / "tiles"
    georef = (
        "+proj=tmerc +lat_0=48.74935649548228 +lon_0=11.422268084715878 +k=1 "
        "+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
    )
    _write_test_xodr(src, georef)

    tiles, _ = TileExtractor.tile(str(src), str(tiles_dir), tile_size=500.0)

    assert tiles, "expected at least one tile to be produced"
    root = ET.parse(tiles[0]).getroot()
    header = root.find("header")
    geo = header.find("geoReference") if header is not None else None
    text = (geo.text or "").strip() if geo is not None else ""

    for token in ("+lat_0=", "+lon_0=", "+k=", "+x_0=", "+y_0=", "+datum=", "+units="):
        assert token in text
