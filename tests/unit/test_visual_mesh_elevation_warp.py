import math

import pytest

from ultimate_pipeline.tools.visual_mesh_elevation_warp import (
    ObjOrigin,
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
