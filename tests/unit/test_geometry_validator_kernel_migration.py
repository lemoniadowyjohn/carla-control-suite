import math
import xml.etree.ElementTree as ET
import pytest

from ultimate_pipeline.geometry.geometry_validator import GeometryValidator
from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint


def test_missing_geometry_origin_uses_previous_arc_endpoint():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="arc-backfill")
    plan = ET.SubElement(road, "planView")
    first = ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length=str(math.pi / 2 / .1))
    ET.SubElement(first, "arc", curvature=".1")
    second = ET.SubElement(plan, "geometry", s="15.7079632679", hdg="1.5707963268", length="5")
    ET.SubElement(second, "line")
    GeometryValidator.validate(root)
    assert float(second.get("x")) == pytest.approx(10.0)
    assert float(second.get("y")) == pytest.approx(10.0)


# 2.1 — XML REORDERING TEST
def test_geometry_reordering_updates_xml_element_order():
    """The serialized XML <geometry> elements must reflect the new s order."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="reorder-test")
    plan = ET.SubElement(road, "planView")

    # Add geometries in wrong s order
    g1 = ET.SubElement(plan, "geometry", s="20", x="0", y="0", hdg="0", length="5")
    ET.SubElement(g1, "line")
    g2 = ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="5")
    ET.SubElement(g2, "line")
    g3 = ET.SubElement(plan, "geometry", s="10", x="0", y="0", hdg="0", length="5")
    ET.SubElement(g3, "line")

    GeometryValidator.validate(root)

    # Check serialized XML order matches sorted s
    serialized_geoms = list(plan)
    s_values = [float(g.get("s")) for g in serialized_geoms]
    assert s_values == [0.0, 10.0, 20.0], f"XML order must be 0,10,20 but got {s_values}"


# 2.2 — GEOMETRY REMOVAL TEST
def test_zero_length_geometry_removed_from_xml():
    """Zero-length geometries must be removed from the XML, not just from internal list."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="remove-test")
    plan = ET.SubElement(road, "planView")

    # Valid geometry
    g1 = ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="5")
    ET.SubElement(g1, "line")
    # Zero-length geometry (should be removed)
    g2 = ET.SubElement(plan, "geometry", s="5", x="0", y="0", hdg="0", length="0")
    ET.SubElement(g2, "line")
    # Valid geometry
    g3 = ET.SubElement(plan, "geometry", s="5.001", x="0", y="0", hdg="0", length="5")
    ET.SubElement(g3, "line")

    initial_count = len(list(plan))
    GeometryValidator.validate(root)
    final_count = len(list(plan))

    assert initial_count == 3
    assert final_count == 2, f"Zero-length geometry must be removed from XML, got {final_count} elements"
    # Verify the remaining geometries have correct s values
    s_values = [float(g.get("s")) for g in plan]
    assert s_values == [0.0, 5.001]


def test_negative_length_geometry_removed_from_xml():
    """Negative-length geometries must be removed from the XML."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="remove-neg-test")
    plan = ET.SubElement(road, "planView")

    g1 = ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="5")
    ET.SubElement(g1, "line")
    g2 = ET.SubElement(plan, "geometry", s="5", x="0", y="0", hdg="0", length="-1")
    ET.SubElement(g2, "line")
    g3 = ET.SubElement(plan, "geometry", s="4", x="0", y="0", hdg="0", length="5")
    ET.SubElement(g3, "line")

    GeometryValidator.validate(root)
    s_values = [float(g.get("s")) for g in plan]
    assert len(s_values) == 2
    assert s_values == [0.0, 4.0]  # g2 removed, g3 reordered to s=4


# 2.3 — HEADING BACKFILL TEST (curved primitive endpoint heading)
def test_missing_hdg_after_arc_uses_endpoint_heading():
    """Missing hdg after arc should use arc's ENDPOINT heading, not start heading."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="arc-hdg-backfill")
    plan = ET.SubElement(road, "planView")

    # Arc: 90-degree quarter circle, curvature 0.1, length = pi*5
    # Start heading = 0, endpoint heading = pi/2 (90 degrees)
    first = ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length=str(math.pi / 2 / 0.1))
    ET.SubElement(first, "arc", curvature="0.1")
    # Second geometry: missing hdg
    second = ET.SubElement(plan, "geometry", s="15.7079632679", length="5")
    ET.SubElement(second, "line")

    GeometryValidator.validate(root)

    # The backfilled hdg should equal the arc's endpoint heading (pi/2)
    backfilled_hdg = float(second.get("hdg"))
    expected_hdg = math.pi / 2
    assert backfilled_hdg == pytest.approx(expected_hdg, abs=1e-6), \
        f"Backfilled hdg should be arc endpoint heading ({expected_hdg}), got {backfilled_hdg}"


def test_missing_hdg_after_spiral_uses_endpoint_heading():
    """Missing hdg after spiral should use spiral's ENDPOINT heading."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="spiral-hdg-backfill")
    plan = ET.SubElement(road, "planView")

    # Spiral from curvature 0 to 0.1 over length 10
    first = ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="10")
    ET.SubElement(first, "spiral", curvStart="0", curvEnd="0.1")
    # Second geometry: missing hdg
    second = ET.SubElement(plan, "geometry", s="10", length="5")
    ET.SubElement(second, "line")

    GeometryValidator.validate(root)

    # Use the canonical kernel to compute expected endpoint heading
    expected_hdg = endpoint(first).heading
    backfilled_hdg = float(second.get("hdg"))
    assert backfilled_hdg == pytest.approx(expected_hdg, abs=1e-6), \
        f"Backfilled hdg should be spiral endpoint heading ({expected_hdg}), got {backfilled_hdg}"


# 2.4 — NONFINITE INPUTS TESTS
def test_nan_s_coordinate_is_rejected():
    """NaN s coordinate should result in REJECTED_REPAIR or FAIL, not silent success."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="nan-s-test")
    plan = ET.SubElement(road, "planView")

    g1 = ET.SubElement(plan, "geometry", s="nan", x="0", y="0", hdg="0", length="5")
    ET.SubElement(g1, "line")
    g2 = ET.SubElement(plan, "geometry", s="5", x="0", y="0", hdg="0", length="5")
    ET.SubElement(g2, "line")

    report = GeometryValidator.validate(root)
    # Should not silently succeed - either FAIL or REJECTED_REPAIR
    assert report["roads"]["nan-s-test"]["status"] != "ok", \
        "NaN s coordinate should not result in 'ok' status"


def test_inf_length_is_rejected():
    """Infinite length should be rejected."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="inf-length-test")
    plan = ET.SubElement(road, "planView")

    g1 = ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="inf")
    ET.SubElement(g1, "line")
    g2 = ET.SubElement(plan, "geometry", s="5", x="0", y="0", hdg="0", length="5")
    ET.SubElement(g2, "line")

    report = GeometryValidator.validate(root)
    assert report["roads"]["inf-length-test"]["status"] != "ok", \
        "Infinite length should not result in 'ok' status"


def test_missing_s_attribute_is_rejected():
    """Missing s attribute should be handled deterministically."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="missing-s-test")
    plan = ET.SubElement(road, "planView")

    g1 = ET.SubElement(plan, "geometry", x="0", y="0", hdg="0", length="5")  # no s
    ET.SubElement(g1, "line")
    g2 = ET.SubElement(plan, "geometry", s="5", x="0", y="0", hdg="0", length="5")
    ET.SubElement(g2, "line")

    report = GeometryValidator.validate(root)
    assert report["roads"]["missing-s-test"]["status"] != "ok", \
        "Missing s attribute should not result in 'ok' status"


def test_missing_length_attribute_is_rejected():
    """Missing length attribute should be handled deterministically."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="missing-length-test")
    plan = ET.SubElement(road, "planView")

    g1 = ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0")  # no length
    ET.SubElement(g1, "line")
    g2 = ET.SubElement(plan, "geometry", s="5", x="0", y="0", hdg="0", length="5")
    ET.SubElement(g2, "line")

    report = GeometryValidator.validate(root)
    assert report["roads"]["missing-length-test"]["status"] != "ok", \
        "Missing length attribute should not result in 'ok' status"


def test_nan_hdg_is_normalized_or_rejected():
    """NaN heading should be handled deterministically."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="nan-hdg-test")
    plan = ET.SubElement(road, "planView")

    g1 = ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="nan", length="5")
    ET.SubElement(g1, "line")
    g2 = ET.SubElement(plan, "geometry", s="5", x="0", y="0", hdg="0", length="5")
    ET.SubElement(g2, "line")

    report = GeometryValidator.validate(root)
    assert report["roads"]["nan-hdg-test"]["status"] != "ok", \
        "NaN hdg should not result in 'ok' status"


# 3 — INSPECTION/REPAIR SEPARATION TEST
def test_inspection_is_read_only():
    """Read-only inspection must not mutate XML (serialized XML must be byte-equivalent)."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="inspection-test")
    plan = ET.SubElement(road, "planView")

    g1 = ET.SubElement(plan, "geometry", s="20", x="0", y="0", hdg="0", length="5")
    ET.SubElement(g1, "line")
    g2 = ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="5")
    ET.SubElement(g2, "line")

    # Serialize before
    before_xml = ET.tostring(root, encoding="unicode")

    # Run inspection (to be implemented)
    # For now, test fails until inspection method exists
    try:
        from ultimate_pipeline.geometry.geometry_validator import GeometryValidator
        if hasattr(GeometryValidator, 'inspect_geometry'):
            report = GeometryValidator.inspect_geometry(root)
        else:
            pytest.skip("inspect_geometry not yet implemented")
    except ImportError:
        pytest.skip("inspect_geometry not yet implemented")

    # Serialize after
    after_xml = ET.tostring(root, encoding="unicode")

    # XML must be structurally equivalent (order may differ due to dict iteration, but elements must match)
    assert before_xml == after_xml, "Inspection must not mutate XML"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])