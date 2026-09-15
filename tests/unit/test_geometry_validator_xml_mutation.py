import xml.etree.ElementTree as ET
import pytest
from ultimate_pipeline.geometry.geometry_validator import GeometryValidator


def _make_road(id, geoms):
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id=str(id), length="100")
    plan = ET.SubElement(road, "planView")
    for i, (s, length, hdg) in enumerate(geoms):
        g = ET.SubElement(plan, "geometry", s=str(s), length=str(length), hdg=str(hdg))
    return root, road


class TestGeometryValidatorXMLMutation:
    def test_sort_reorders_xml_children(self):
        geoms = [(10, 5, 0), (0, 5, 0), (5, 5, 0)]
        root, road = _make_road(1, geoms)
        GeometryValidator.validate(root)
        plan = road.find("./planView")
        s_vals = [float(g.attrib["s"]) for g in plan.findall("geometry")]
        assert s_vals == [0.0, 5.0, 10.0], f"XML not reordered: {s_vals}"

    def test_zero_length_removed_from_xml(self):
        geoms = [(0, 0.0001, 0), (1, 5, 0)]
        root, road = _make_road(1, geoms)
        GeometryValidator.validate(root)
        plan = road.find("./planView")
        geoms_after = plan.findall("geometry")
        assert len(geoms_after) == 1, f"Zero-length not removed: {len(geoms_after)}"

    def test_heading_backfill_uses_endpoint(self):
        geoms = [(0, 10, 0), (10, 10, None)]
        root, road = _make_road(1, geoms)
        GeometryValidator.validate(root)
        plan = road.find("./planView")
        hdg = plan.findall("geometry")[1].attrib["hdg"]
        assert hdg is not None, \
            f"Heading not backfilled: {hdg}"

    def test_validate_returns_report(self):
        geoms = [(0, 10, 0), (10, 5, 1.57)]
        root, _ = _make_road(1, geoms)
        report = GeometryValidator.validate(root)
        assert "roads" in report
        assert report["roads"]["1"]["status"] == "ok"

    def test_zero_length_report_status(self):
        geoms = [(0, 0.0001, 0)]
        root, _ = _make_road(1, geoms)
        report = GeometryValidator.validate(root)
        assert report["roads"]["1"]["status"] == "all_zero_length_removed"

    def test_xml_reorder_not_just_list_sort(self):
        geoms = [(30, 5, 0), (10, 5, 0), (20, 5, 0)]
        root, road = _make_road(1, geoms)
        GeometryValidator.validate(root)
        plan = road.find("./planView")
        s_vals = [float(g.attrib["s"]) for g in plan.findall("geometry")]
        assert s_vals == [10.0, 20.0, 30.0], f"XML not reordered: {s_vals}"
        first_elem = plan.findall("geometry")[0]
        assert float(first_elem.attrib["s"]) == 10.0
