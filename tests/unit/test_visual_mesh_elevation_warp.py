import math
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.tools.visual_mesh_elevation_warp import (
    ObjOrigin,
    decompose_xodr_dem_elevation_residuals,
    structure_bucket_for_class,
    local_obj_to_lonlat,
    summarize_abs_residuals,
    warp_obj_lines,
)


def test_local_obj_to_lonlat_uses_osm2world_east_up_south_frame():
    origin = ObjOrigin(lat=48.75, lon=11.43, ele=0.0)

    east_lon, east_lat = local_obj_to_lonlat(origin, x_east_m=100.0, z_south_m=0.0)
    south_lon, south_lat = local_obj_to_lonlat(origin, x_east_m=0.0, z_south_m=100.0)
    north_lon, north_lat = local_obj_to_lonlat(origin, x_east_m=0.0, z_south_m=-100.0)

    assert east_lon > origin.lon
    assert east_lat == pytest.approx(origin.lat)
    assert south_lat < origin.lat
    assert north_lat > origin.lat
    assert math.isclose(south_lon, origin.lon)


def test_warp_obj_lines_adds_dem_height_and_preserves_object_height():
    origin = ObjOrigin(lat=48.75, lon=11.43, ele=0.0)
    lines = [
        "# header\n",
        "v 10.0 4.0 -20.0\n",
        "vn 0.0 1.0 0.0\n",
        "f 1//1 2//1 3//1\n",
    ]

    warped, stats = warp_obj_lines(lines, origin=origin, sample_dem=lambda lon, lat: 370.25)

    assert warped[0] == lines[0]
    assert warped[1] == "v 10.000000 374.250000 -20.000000\n"
    assert warped[2:] == lines[2:]
    assert stats.vertices_total == 1
    assert stats.vertices_warped == 1
    assert stats.dem_missing == 0
    assert stats.dem_height_min == pytest.approx(370.25)
    assert stats.y_warped_after_min == pytest.approx(374.25)
    assert stats.y_before_min == pytest.approx(4.0)
    assert stats.y_after_min == pytest.approx(374.25)


def test_warp_obj_lines_keeps_vertex_when_dem_is_missing():
    origin = ObjOrigin(lat=48.75, lon=11.43, ele=0.0)
    lines = ["v 10.0 4.0 -20.0\n"]

    warped, stats = warp_obj_lines(lines, origin=origin, sample_dem=lambda lon, lat: None)

    assert warped == lines
    assert stats.vertices_total == 1
    assert stats.vertices_warped == 0
    assert stats.dem_missing == 1
    assert stats.y_before_min == pytest.approx(4.0)
    assert stats.y_after_min == pytest.approx(4.0)


def test_summarize_abs_residuals_reports_p95_and_max():
    summary = summarize_abs_residuals([0.0, 1.0, 2.0, 10.0, 20.0])

    assert summary["count"] == 5
    assert summary["mean_abs_m"] == pytest.approx(6.6)
    assert summary["median_abs_m"] == pytest.approx(2.0)
    assert summary["p95_abs_m"] == pytest.approx(10.0)
    assert summary["max_abs_m"] == pytest.approx(20.0)


def test_structure_bucket_for_class_separates_grade_separated_from_at_grade():
    assert structure_bucket_for_class("bridge") == "grade_separated"
    assert structure_bucket_for_class("deck_linear") == "grade_separated"
    assert structure_bucket_for_class("elevated") == "grade_separated"
    assert structure_bucket_for_class("tunnel") == "grade_separated"
    assert structure_bucket_for_class("terrain_following") == "at_grade"
    assert structure_bucket_for_class("unknown") == "unknown_fail_closed"


def test_decompose_residuals_buckets_grade_separated_tail(tmp_path):
    xodr = tmp_path / "tiny.xodr"
    root = ET.Element("OpenDRIVE")
    road_a = ET.SubElement(root, "road", id="1", length="10.0")
    pv_a = ET.SubElement(road_a, "planView")
    ET.SubElement(pv_a, "geometry", s="0.0", x="1.0", y="2.0", hdg="0.0", length="10.0")
    ep_a = ET.SubElement(road_a, "elevationProfile")
    ET.SubElement(ep_a, "elevation", s="0.0", a="100.25", b="0", c="0", d="0")

    road_b = ET.SubElement(root, "road", id="2", length="10.0")
    pv_b = ET.SubElement(road_b, "planView")
    ET.SubElement(pv_b, "geometry", s="0.0", x="3.0", y="4.0", hdg="0.0", length="10.0")
    ep_b = ET.SubElement(road_b, "elevationProfile")
    ET.SubElement(ep_b, "elevation", s="0.0", a="108.0", b="0", c="0", d="0")
    ET.ElementTree(root).write(xodr, encoding="utf-8", xml_declaration=True)

    report = decompose_xodr_dem_elevation_residuals(
        xodr,
        sample_dem=lambda lon, lat: 100.0,
        road_class_by_id={"1": "terrain_following", "2": "bridge"},
        xodr_to_lonlat=lambda x, y: (x, y),
        sample_limit=0,
        at_grade_max_threshold_m=10.0,
    )

    assert report["verdict"] == "PASS"
    assert report["buckets"]["at_grade"]["residual_summary"]["max_abs_m"] == pytest.approx(0.25)
    assert report["buckets"]["grade_separated"]["residual_summary"]["max_abs_m"] == pytest.approx(8.0)
    assert report["tail_interpretation"]["largest_residual_bucket"] == "grade_separated"


def test_decompose_residuals_marks_large_at_grade_max_for_review(tmp_path):
    xodr = tmp_path / "tiny_at_grade_tail.xodr"
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length="10.0")
    pv = ET.SubElement(road, "planView")
    ET.SubElement(pv, "geometry", s="0.0", x="1.0", y="2.0", hdg="0.0", length="10.0")
    ep = ET.SubElement(road, "elevationProfile")
    ET.SubElement(ep, "elevation", s="0.0", a="112.0", b="0", c="0", d="0")
    ET.ElementTree(root).write(xodr, encoding="utf-8", xml_declaration=True)

    report = decompose_xodr_dem_elevation_residuals(
        xodr,
        sample_dem=lambda lon, lat: 100.0,
        road_class_by_id={"1": "terrain_following"},
        xodr_to_lonlat=lambda x, y: (x, y),
        sample_limit=0,
        at_grade_p95_threshold_m=5.0,
        at_grade_max_threshold_m=10.0,
    )

    assert report["verdict"] == "PARTIAL_REVIEW_REQUIRED"
    assert report["tail_interpretation"]["at_grade_max_ok"] is False
