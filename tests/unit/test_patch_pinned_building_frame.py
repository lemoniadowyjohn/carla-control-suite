"""C29 remediation option (b): surgical patch of an already-pinned XODR's building
cornerGlobal points, which were written in the pre-fix buggy projection frame and were
never rebased (see C29_building_frame_root_cause.md). The correction is a single (dx, dy)
translation -- ultimate_pipeline.domain_gap.local_registration.building_frame_shift_to_auto_local,
already used and validated for reading (not writing) buildings in the correct local frame --
applied directly to each cornerGlobal x/y (z untouched). Nothing else in the file should change.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from scripts.patch_pinned_building_frame import (
    patch_building_corner_global,
    compute_shift_for_pinned_map,
)


def _xodr_with_road_and_building() -> ET.Element:
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header")
    ET.SubElement(header, "offset", x="832671.676", y="5458671.104", z="0.0", hdg="0.0")
    geo = ET.SubElement(header, "geoReference")
    geo.text = "+proj=tmerc +datum=WGS84 +units=m +no_defs"

    road = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
    plan = ET.SubElement(road, "planView")
    ET.SubElement(plan, "geometry", s="0", x="100.0", y="200.0", hdg="0", length="10.0")

    building = ET.SubElement(road, "objects")
    obj = ET.SubElement(building, "object", id="b1", type="building", s="0", t="0")
    outline = ET.SubElement(obj, "outline")
    ET.SubElement(outline, "cornerGlobal", x="10.0", y="20.0", z="365.0")
    ET.SubElement(outline, "cornerGlobal", x="11.0", y="21.0", z="365.0")

    return root


def test_patch_shifts_building_cornerglobal_xy_only():
    root = _xodr_with_road_and_building()
    n = patch_building_corner_global(root, dx=5.0, dy=-3.0)
    assert n == 2
    corners = root.findall(".//object[@type='building']/outline/cornerGlobal")
    assert corners[0].get("x") == "15.000000"
    assert corners[0].get("y") == "17.000000"
    assert corners[0].get("z") == "365.0"  # untouched
    assert corners[1].get("x") == "16.000000"
    assert corners[1].get("y") == "18.000000"


def test_patch_does_not_touch_road_geometry():
    root = _xodr_with_road_and_building()
    patch_building_corner_global(root, dx=5.0, dy=-3.0)
    geom = root.find(".//planView/geometry")
    assert geom.get("x") == "100.0"
    assert geom.get("y") == "200.0"


def test_patch_ignores_non_building_objects():
    root = _xodr_with_road_and_building()
    road = root.find("road")
    objs = road.find("objects")
    other = ET.SubElement(objs, "object", id="c1", type="crosswalk", s="0", t="0")
    outline = ET.SubElement(other, "outline")
    ET.SubElement(outline, "cornerLocal", u="1.0", v="2.0", z="0.0")

    n = patch_building_corner_global(root, dx=5.0, dy=-3.0)
    assert n == 2  # only the 2 building corners, crosswalk's cornerLocal untouched
    corner_local = other.find("outline/cornerLocal")
    assert corner_local.get("u") == "1.0"


def test_patch_returns_zero_when_no_buildings_present():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length="10.0", junction="-1")
    plan = ET.SubElement(road, "planView")
    ET.SubElement(plan, "geometry", s="0", x="0.0", y="0.0", hdg="0", length="10.0")
    n = patch_building_corner_global(root, dx=5.0, dy=-3.0)
    assert n == 0


def test_compute_shift_matches_building_frame_shift_to_auto_local():
    root = _xodr_with_road_and_building()
    dx, dy = compute_shift_for_pinned_map(
        root, osm_lat_min=48.74935649548228, osm_lon_min=11.422268084715878
    )
    # Cross-check against the underlying, already-validated function directly.
    from ultimate_pipeline.domain_gap.local_registration import building_frame_shift_to_auto_local

    expected_dx, expected_dy = building_frame_shift_to_auto_local(
        osm_lat_min=48.74935649548228,
        osm_lon_min=11.422268084715878,
        auto_proj4="+proj=tmerc +datum=WGS84 +units=m +no_defs",
        auto_offset=(832671.676, 5458671.104),
    )
    assert abs(dx - expected_dx) < 1e-6
    assert abs(dy - expected_dy) < 1e-6
    # Sanity: matches the real pinned map's known magnitude (~6547/6369), not zero/garbage.
    assert 6000.0 < dx < 7000.0
    assert 6000.0 < dy < 7000.0
