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
        """A road whose ONLY geometry is zero-length must not end up with an
        empty <planView> -- the single segment is repaired to the minimum
        valid length instead of being deleted outright (see
        test_sole_zero_length_geometry_is_repaired_not_deleted for the XML
        assertion). The report status reflects a successful repair, not a
        deletion.
        """
        geoms = [(0, 0.0001, 0)]
        root, _ = _make_road(1, geoms)
        report = GeometryValidator.validate(root)
        assert report["roads"]["1"]["status"] == "ok"
        assert any(
            issue.startswith("repaired_degenerate_planview_to_min_length_at_s=")
            for issue in report["roads"]["1"]["issues"]
        )

    def test_sole_zero_length_geometry_is_repaired_not_deleted(self):
        """Regression test for a real production crash: a ~0.1m junction
        connector road (SUMO ':132_1', XODR id 54601, junction 117) whose
        single planView <geometry> had length=0.00000008 (effectively zero)
        was DELETED entirely by GeometryValidator, leaving <planView> with
        zero <geometry> children. That empty planView later crashed
        xodr_junction_links.py::_road_endpoints() with
        "road id=54601 has empty planView" during the junction link
        integrity gate. planView must never be left empty; the degenerate
        geometry must be repaired (length bumped to the minimum valid
        segment length) and kept in the XML instead.
        """
        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(
            root, "road", name=":132_1", id="54601", junction="117", length="0.10000000"
        )
        plan = ET.SubElement(road, "planView")
        geom = ET.SubElement(
            plan, "geometry", s="0.00000000", x="842522.97377508",
            y="5461822.76775999", hdg="3.02938984", length="0.00000008",
        )
        ET.SubElement(geom, "line")

        report = GeometryValidator.validate(root)

        geoms_after = plan.findall("geometry")
        assert len(geoms_after) == 1, (
            f"planView must never end up empty, got {len(geoms_after)} geometries"
        )
        assert float(geoms_after[0].get("length")) >= GeometryValidator.MIN_SEG_LEN
        assert report["roads"]["54601"]["status"] == "ok"

    def test_multiple_degenerate_geometries_repair_one_remove_rest(self):
        """When a road has several zero-length geometries and no real ones,
        exactly one survives (repaired to the minimum length) and the
        others are removed -- planView still ends up with real content, not
        duplicated near-zero-length stubs.
        """
        geoms = [(0, 0.0, 0), (0.0001, 0.0, 0), (0.0002, -1.0, 0)]
        root, road = _make_road(1, geoms)
        report = GeometryValidator.validate(root)
        plan = road.find("./planView")
        geoms_after = plan.findall("geometry")
        assert len(geoms_after) == 1
        assert float(geoms_after[0].get("length")) >= GeometryValidator.MIN_SEG_LEN
        assert report["roads"]["1"]["status"] == "ok"

    def test_xml_reorder_not_just_list_sort(self):
        geoms = [(30, 5, 0), (10, 5, 0), (20, 5, 0)]
        root, road = _make_road(1, geoms)
        GeometryValidator.validate(root)
        plan = road.find("./planView")
        s_vals = [float(g.attrib["s"]) for g in plan.findall("geometry")]
        assert s_vals == [10.0, 20.0, 30.0], f"XML not reordered: {s_vals}"
        first_elem = plan.findall("geometry")[0]
        assert float(first_elem.attrib["s"]) == 10.0
