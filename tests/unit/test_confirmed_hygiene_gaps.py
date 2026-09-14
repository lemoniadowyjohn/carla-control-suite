from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.lane_width_policy import apply_lane_width_policy
from ultimate_pipeline.quality.map_hygiene import _build_adjacency
from ultimate_pipeline.tiling import tile_extractor


def _road(road_id: str = "1", *, x: float = 0.0, width: tuple[str, str, str, str] = ("3.5", "0", "0", "0")) -> ET.Element:
    road = ET.Element("road", id=road_id, length="10.0", junction="-1")
    plan_view = ET.SubElement(road, "planView")
    geometry = ET.SubElement(plan_view, "geometry", s="0", x=str(x), y="0", hdg="0", length="10")
    ET.SubElement(geometry, "line")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    right = ET.SubElement(section, "right")
    lane = ET.SubElement(right, "lane", id="-1", type="driving")
    ET.SubElement(lane, "width", sOffset="0", a=width[0], b=width[1], c=width[2], d=width[3])
    return road


def test_valid_width_polynomial_is_not_flattened_by_policy() -> None:
    root = ET.Element("OpenDRIVE")
    road = _road(width=("3.6", "0.01", "0", "0"))
    root.append(road)

    report = apply_lane_width_policy(root)

    width = road.find(".//lane[@type='driving']/width")
    assert width is not None
    assert (width.get("a"), width.get("b"), width.get("c"), width.get("d")) == ("3.6", "0.01", "0", "0")
    assert report["totals"]["driving_widths_updated"] == 0


def test_invalid_width_polynomial_is_repaired() -> None:
    root = ET.Element("OpenDRIVE")
    road = _road(width=("3.6", "nan", "0", "0"))
    root.append(road)

    report = apply_lane_width_policy(root)

    width = road.find(".//lane[@type='driving']/width")
    assert width is not None
    assert width.get("a") == "3.500"
    assert width.get("b") == "0.0"
    assert report["totals"]["driving_widths_updated"] == 1


def test_road_and_junction_ids_have_separate_graph_namespaces() -> None:
    road = _road("7")
    link = ET.SubElement(road, "link")
    ET.SubElement(link, "successor", elementType="junction", elementId="7")
    junction = ET.Element("junction", id="7")
    ET.SubElement(junction, "connection", incomingRoad="7", connectingRoad="7")

    graph = _build_adjacency([road], [junction])

    assert set(graph) == {"road:7", "junction:7"}
    assert graph["road:7"] == {"junction:7"}
    assert graph["junction:7"] == {"road:7"}


def test_tile_bounds_cache_includes_planview_content() -> None:
    tile_extractor._BOUNDS_CACHE.clear()
    first = _road("same", x=0.0)
    second = _road("same", x=100.0)

    first_bounds = tile_extractor._road_bounds(first)
    second_bounds = tile_extractor._road_bounds(second)

    assert first_bounds != second_bounds
    assert len(tile_extractor._BOUNDS_CACHE) == 2
