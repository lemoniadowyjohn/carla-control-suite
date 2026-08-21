"""RQ1 local registration: crop the auto map to the manual map's geographic footprint
so structural gaps measure a LOCAL comparison, not whole-map scope artifacts.

The auto map (Osm2Odr) uses a bare `+proj=tmerc` + a header offset (local frame); the
manual Grid0828 uses UTM-32N. Registration = manual footprint -> lat/lon -> auto bare-tmerc
-> minus auto offset -> auto-local, then crop auto roads to that polygon.
"""
import xml.etree.ElementTree as ET

from shapely.geometry import Polygon


def _road(rid, pts, junction="-1"):
    r = ET.Element("road", id=str(rid), junction=str(junction))
    pv = ET.SubElement(r, "planView")
    for (x, y) in pts:
        ET.SubElement(pv, "geometry", s="0", x=str(x), y=str(y), hdg="0", length="1")
    return r


def test_read_georef_bare_tmerc_expands_to_usable_default():
    from ultimate_pipeline.domain_gap.local_registration import read_georef_proj4
    root = ET.fromstring('<OpenDRIVE><header><geoReference>+proj=tmerc</geoReference></header></OpenDRIVE>')
    proj = read_georef_proj4(root)
    assert "+proj=tmerc" in proj
    assert "+datum" in proj or "+ellps" in proj  # expanded so pyproj can use it


def test_read_georef_full_proj_passes_through():
    from ultimate_pipeline.domain_gap.local_registration import read_georef_proj4
    root = ET.fromstring(
        '<OpenDRIVE><header><geoReference><![CDATA[+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 '
        '+x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs]]></geoReference></header></OpenDRIVE>')
    proj = read_georef_proj4(root)
    assert "+lon_0=9" in proj and "+x_0=500000" in proj


def test_read_offset():
    from ultimate_pipeline.domain_gap.local_registration import read_offset
    root = ET.fromstring('<OpenDRIVE><header><offset x="832671.676" y="5458671.104"/></header></OpenDRIVE>')
    ox, oy = read_offset(root)
    assert abs(ox - 832671.676) < 1e-3 and abs(oy - 5458671.104) < 1e-3


def test_crop_keeps_roads_with_centroid_inside_polygon():
    from ultimate_pipeline.domain_gap.local_registration import crop_roads_to_polygon
    poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    inside = _road(1, [(2, 2), (4, 4)])       # centroid (3,3) inside
    straddle_in = _road(2, [(1, 1), (3, 3)])  # centroid (2,2) inside
    outside = _road(3, [(20, 20), (22, 22)])  # centroid (21,21) outside
    kept = crop_roads_to_polygon([inside, straddle_in, outside], poly)
    assert sorted(r.get("id") for r in kept) == ["1", "2"]


def test_crop_junction_ids_from_kept_roads():
    from ultimate_pipeline.domain_gap.local_registration import kept_junction_ids
    roads = [_road(1, [(1, 1)], junction="7"), _road(2, [(2, 2)], junction="-1"),
             _road(3, [(3, 3)], junction="7")]
    assert kept_junction_ids(roads) == {"7"}


def test_local_structural_summary_reports_ratios_and_excludes_construction():
    from types import SimpleNamespace
    from ultimate_pipeline.domain_gap.local_registration import (
        LocalRegistrationResult, local_structural_summary)
    m = SimpleNamespace(total_road_length=53525.0, num_junctions=119, num_roads=993,
                        num_buildings=0, num_traffic_lights=0)
    ca = SimpleNamespace(total_road_length=240842.0, num_junctions=720, num_roads=6079,
                         num_buildings=0, num_traffic_lights=3920)
    gap = SimpleNamespace(lane_width_gap=0.0415, curvature_gap=0.2239)
    res = LocalRegistrationResult(
        local_gap=gap, manual_stats=m, cropped_auto_stats=ca,
        full_auto_road_count=32297, cropped_auto_road_count=6079,
        footprint_local_bounds=(0, 0, 1, 1), provenance={})
    s = local_structural_summary(res)
    rn = s["road_network_structural"]
    assert abs(rn["road_length_ratio_auto_over_manual"] - 4.5) < 0.1
    assert abs(rn["junction_ratio_auto_over_manual"] - 6.05) < 0.2
    assert rn["lane_width_gap"] == 0.0415
    # construction differences are separated out, not folded into the structural gap
    assert s["construction_differences_excluded"]["cropped_auto_traffic_lights"] == 3920


def test_transform_manual_bbox_to_auto_local_matches_registration():
    # Grid0828 UTM-32N footprint -> auto-local; pinned to independently-verified values
    # (SW~(6505,6424) NE~(10572,9876) => bbox x[~6155..10922] y[~6424..9876]).
    from ultimate_pipeline.domain_gap.local_registration import transform_manual_bbox_to_auto_local
    manual_proj = ("+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 "
                   "+datum=WGS84 +units=m +no_defs")
    auto_proj = "+proj=tmerc +datum=WGS84 +units=m +no_defs"
    poly = transform_manual_bbox_to_auto_local(
        manual_bbox=(678016.0, 5402483.0, 682426.0, 5405403.0),
        manual_proj4=manual_proj, auto_proj4=auto_proj,
        auto_offset=(832671.676, 5458671.104))
    assert isinstance(poly, Polygon)
    minx, miny, maxx, maxy = poly.bounds
    assert 6100 < minx < 6210 and 6390 < miny < 6470
    assert 10870 < maxx < 10980 and 9820 < maxy < 9930
