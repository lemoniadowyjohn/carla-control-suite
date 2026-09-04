"""RQ1 local registration: crop the auto map to the manual map's geographic footprint
so structural gaps measure a LOCAL comparison, not whole-map scope artifacts.

The auto map (Osm2Odr) uses a bare `+proj=tmerc` + a header offset (local frame); the
manual Grid0828 uses UTM-32N. Registration = manual footprint -> lat/lon -> auto bare-tmerc
-> minus auto offset -> auto-local, then crop auto roads to that polygon.
"""
import xml.etree.ElementTree as ET

import pytest
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
                        num_buildings=993, num_traffic_lights=0)
    ca = SimpleNamespace(total_road_length=240842.0, num_junctions=720, num_roads=6079,
                         num_buildings=812, num_traffic_lights=3920)
    gap = SimpleNamespace(
        lane_width_gap=0.0415,
        curvature_gap=0.2239,
        curvature_wasserstein_gap=0.0642,
        building_density_gap=0.31,
    )
    res = LocalRegistrationResult(
        local_gap=gap, manual_stats=m, cropped_auto_stats=ca,
        full_auto_road_count=32297, cropped_auto_road_count=6079,
        footprint_local_bounds=(0, 0, 1, 1), provenance={})
    s = local_structural_summary(res)
    rn = s["road_network_structural"]
    assert abs(rn["road_length_ratio_auto_over_manual"] - 4.5) < 0.1
    assert abs(rn["junction_ratio_auto_over_manual"] - 6.05) < 0.2
    assert rn["lane_width_gap"] == 0.0415
    assert rn["curvature_wasserstein_gap"] == 0.0642
    # buildings are now cropped in-footprint and compared as a real density, not excluded
    bld = s["building_density_comparison"]
    assert bld["cropped_auto_buildings"] == 812
    assert bld["manual_buildings"] == 993
    assert bld["building_density_gap"] == 0.31
    # traffic lights and construction differences are separated out, not folded into the structural gap
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


# ------------------------------------------------------------------ Part 1: convex-hull footprint

def test_manual_geometry_convex_hull_returns_hull_vertices():
    """A synthetic manual map whose planView points form an octagon-ish shape (with points
    that lie strictly inside the bbox 'corners') should yield a convex hull whose area is
    strictly smaller than the bbox area — the whole point of tightening the footprint."""
    from ultimate_pipeline.domain_gap.local_registration import (
        manual_geometry_bbox, manual_geometry_convex_hull)
    from shapely.geometry import MultiPoint

    # Diamond of points: bbox is [0,10]x[0,10] (area 100), convex hull is a diamond (area 50).
    pts = [(5, 0), (10, 5), (5, 10), (0, 5)]
    root = ET.fromstring("<OpenDRIVE/>")
    road = ET.SubElement(root, "road", id="1", junction="-1")
    pv = ET.SubElement(road, "planView")
    for (x, y) in pts:
        ET.SubElement(pv, "geometry", s="0", x=str(x), y=str(y), hdg="0", length="1")

    bbox = manual_geometry_bbox(root)
    assert bbox == (0.0, 0.0, 10.0, 10.0)

    hull_pts = manual_geometry_convex_hull(root)
    hull_poly = MultiPoint(hull_pts).convex_hull
    bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    assert hull_poly.area < bbox_area
    assert abs(hull_poly.area - 50.0) < 1e-6


def test_transform_manual_points_to_auto_local_identity_projection():
    """With identical proj4 (no-op transform) and zero offset, the auto-local polygon should
    equal the convex hull of the input points (order/closure aside)."""
    from ultimate_pipeline.domain_gap.local_registration import transform_manual_points_to_auto_local
    proj = "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs"
    pts = [(500100.0, 5400000.0), (500200.0, 5400050.0), (500150.0, 5400120.0), (500080.0, 5400060.0)]
    poly = transform_manual_points_to_auto_local(
        pts, manual_proj4=proj, auto_proj4=proj, auto_offset=(0.0, 0.0))
    assert isinstance(poly, Polygon)
    # Round-trip through the same CRS twice (manual->ll->auto) should reproduce the same
    # points (up to numerical noise), since manual_proj4 == auto_proj4.
    from shapely.geometry import MultiPoint
    expected = MultiPoint(pts).convex_hull
    assert abs(poly.convex_hull.area - expected.area) < 1.0


def test_transform_auto_points_to_manual_local_identity_projection():
    """Mirror of transform_manual_points_to_auto_local, opposite direction. With identical
    proj4 and zero auto offset, round-tripping auto-local points through lat/lon and back
    into "manual's" CRS (the same CRS here) should reproduce the input points."""
    from ultimate_pipeline.domain_gap.local_registration import transform_auto_points_to_manual_local
    proj = "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs"
    pts = [(500100.0, 5400000.0), (500200.0, 5400050.0), (500150.0, 5400120.0)]
    out = transform_auto_points_to_manual_local(
        pts, auto_proj4=proj, auto_offset=(0.0, 0.0), manual_proj4=proj)
    assert len(out) == len(pts)
    for (ox, oy), (ix, iy) in zip(out, pts):
        assert abs(ox - ix) < 1e-3
        assert abs(oy - iy) < 1e-3


def test_transform_auto_points_to_manual_local_applies_auto_offset_before_reprojection():
    """A nonzero auto_offset must be added to the raw auto-local points BEFORE the CRS
    round-trip -- shifting the offset should shift the output by the same amount (same CRS
    on both sides, so the offset survives the round-trip almost exactly)."""
    from ultimate_pipeline.domain_gap.local_registration import transform_auto_points_to_manual_local
    proj = "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs"
    pts = [(100.0, 200.0)]
    no_offset = transform_auto_points_to_manual_local(
        pts, auto_proj4=proj, auto_offset=(0.0, 0.0), manual_proj4=proj)
    with_offset = transform_auto_points_to_manual_local(
        pts, auto_proj4=proj, auto_offset=(50.0, -30.0), manual_proj4=proj)
    assert with_offset[0][0] - no_offset[0][0] == pytest.approx(50.0, abs=1e-3)
    assert with_offset[0][1] - no_offset[0][1] == pytest.approx(-30.0, abs=1e-3)


def test_transform_auto_points_to_manual_local_is_inverse_of_manual_to_auto():
    """Round-tripping a point manual->auto->manual (via the two mirror functions, with
    DIFFERENT real proj4s -- bare tmerc for auto, UTM-32N-style for manual, matching the
    real Ingolstadt auto/manual pair) should recover the original point."""
    from ultimate_pipeline.domain_gap.local_registration import (
        transform_manual_points_to_auto_local,
        transform_auto_points_to_manual_local,
        BARE_TMERC_DEFAULT,
    )
    manual_proj = "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs"
    auto_proj = BARE_TMERC_DEFAULT
    auto_offset = (832671.676, 5458671.104)
    manual_point = (505000.0, 5403000.0)

    # A single-point convex hull degenerates to a shapely Point (no .exterior).
    auto_hull = transform_manual_points_to_auto_local(
        [manual_point], manual_proj4=manual_proj, auto_proj4=auto_proj, auto_offset=auto_offset
    )
    auto_local_point = list(auto_hull.coords)[0]

    back = transform_auto_points_to_manual_local(
        [auto_local_point], auto_proj4=auto_proj, auto_offset=auto_offset, manual_proj4=manual_proj
    )
    assert back[0][0] == pytest.approx(manual_point[0], abs=1e-2)
    assert back[0][1] == pytest.approx(manual_point[1], abs=1e-2)


def test_hull_polygon_is_subset_of_bbox_polygon_never_larger():
    """Structural guarantee: for any point set, the convex hull area is <= the bbox area,
    so a hull-based crop can only shrink (or keep-equal) the kept-road set vs. bbox crop."""
    from ultimate_pipeline.domain_gap.local_registration import (
        manual_geometry_bbox, manual_geometry_convex_hull)
    from shapely.geometry import MultiPoint, box

    pts = [(2, 1), (8, 0), (10, 6), (7, 10), (2, 9), (0, 5), (4, 5), (6, 4)]
    root = ET.fromstring("<OpenDRIVE/>")
    road = ET.SubElement(root, "road", id="1", junction="-1")
    pv = ET.SubElement(road, "planView")
    for (x, y) in pts:
        ET.SubElement(pv, "geometry", s="0", x=str(x), y=str(y), hdg="0", length="1")

    bbox = manual_geometry_bbox(root)
    bbox_poly = box(*bbox)
    hull_poly = MultiPoint(manual_geometry_convex_hull(root)).convex_hull

    assert hull_poly.area <= bbox_poly.area
    assert hull_poly.within(bbox_poly.buffer(1e-9))


def test_hull_crop_keeps_fewer_or_equal_roads_than_bbox_crop():
    """End-to-end synthetic check: roads that sit in the bbox 'corner' region (outside the
    hull) must be dropped by a hull crop but kept by a bbox crop."""
    from ultimate_pipeline.domain_gap.local_registration import crop_roads_to_polygon
    from shapely.geometry import box, MultiPoint

    # Diamond hull inscribed in a 10x10 bbox square.
    hull_pts = [(5, 0), (10, 5), (5, 10), (0, 5)]
    bbox_poly = box(0, 0, 10, 10)
    hull_poly = MultiPoint(hull_pts).convex_hull

    corner_road = _road(1, [(1, 1), (1.5, 1.5)])   # centroid (1.25,1.25): in bbox, outside hull
    center_road = _road(2, [(4, 4), (6, 6)])       # centroid (5,5): in both

    bbox_kept = crop_roads_to_polygon([corner_road, center_road], bbox_poly)
    hull_kept = crop_roads_to_polygon([corner_road, center_road], hull_poly)

    assert sorted(r.get("id") for r in bbox_kept) == ["1", "2"]
    assert sorted(r.get("id") for r in hull_kept) == ["2"]
    assert len(hull_kept) <= len(bbox_kept)


# ------------------------------------------------------------------ Part 2: building cropping

def _building_object(oid, corners, s="0", t="0"):
    obj = ET.Element(
        "object", id=str(oid), type="building", s=s, t=t, zOffset="0.0",
        orientation="absolute", height="10.0", hdg="0.0", length="0.0", width="0.0",
    )
    outline = ET.SubElement(obj, "outline", id="0", fillType="concrete")
    for (x, y) in corners:
        ET.SubElement(outline, "cornerGlobal", x=str(x), y=str(y), z="0.0")
    return obj


def test_building_global_centroid_from_corner_global_points():
    from ultimate_pipeline.domain_gap.local_registration import building_global_centroid
    obj = _building_object(1, [(0, 0), (10, 0), (10, 10), (0, 10)])
    c = building_global_centroid(obj)
    assert c is not None
    assert abs(c[0] - 5.0) < 1e-6 and abs(c[1] - 5.0) < 1e-6


def test_building_global_centroid_applies_optional_frame_shift():
    """`cornerGlobal` coordinates are written by the OSM building enrichment step in a tmerc
    frame anchored at (lat_min, lon_min) of the OSM extraction bbox -- a DIFFERENT local
    origin than the road network's frame (bare tmerc + header <offset>). A `shift` param
    lets callers align building centroids into the road/auto-local frame before cropping."""
    from ultimate_pipeline.domain_gap.local_registration import building_global_centroid
    obj = _building_object(1, [(0, 0), (10, 0), (10, 10), (0, 10)])
    c = building_global_centroid(obj, shift=(1000.0, -500.0))
    assert abs(c[0] - 1005.0) < 1e-6 and abs(c[1] - (-495.0)) < 1e-6


def test_building_global_centroid_none_when_no_corner_global():
    from ultimate_pipeline.domain_gap.local_registration import building_global_centroid
    obj = ET.Element("object", id="1", type="building", s="0", t="0")
    outline = ET.SubElement(obj, "outline", id="0")
    ET.SubElement(outline, "cornerLocal", u="0", v="0", z="0")  # road-relative, not global
    assert building_global_centroid(obj) is None


def test_collect_building_objects_from_all_roads():
    """Buildings should be collected map-wide (not per-kept-road), since the auto map's
    buildings all sit on a single non-representative container road."""
    from ultimate_pipeline.domain_gap.local_registration import collect_building_objects
    root = ET.fromstring("<OpenDRIVE/>")
    container = ET.SubElement(root, "road", id="999", junction="-1")
    objs = ET.SubElement(container, "objects")
    objs.append(_building_object(1, [(0, 0), (2, 0), (2, 2), (0, 2)]))
    objs.append(_building_object(2, [(10, 10), (12, 10), (12, 12), (10, 12)]))
    found = collect_building_objects(root)
    assert len(found) == 2


def test_crop_buildings_to_polygon_keeps_only_inside_centroids():
    from ultimate_pipeline.domain_gap.local_registration import crop_buildings_to_polygon
    poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    inside = _building_object(1, [(2, 2), (4, 2), (4, 4), (2, 4)])      # centroid (3,3) inside
    outside = _building_object(2, [(20, 20), (22, 20), (22, 22), (20, 22)])  # outside
    kept = crop_buildings_to_polygon([inside, outside], poly)
    assert [o.get("id") for o in kept] == ["1"]


def test_crop_buildings_to_polygon_applies_frame_shift_before_containment_test():
    """A building whose raw cornerGlobal centroid is OUTSIDE the polygon must be kept if the
    frame shift moves it inside -- this is the exact bug found on the real Ingolstadt pair
    (building cornerGlobal values are in a tmerc frame anchored at the OSM bbox's
    (lat_min, lon_min), not the road network's bare-tmerc + offset frame)."""
    from ultimate_pipeline.domain_gap.local_registration import crop_buildings_to_polygon
    poly = Polygon([(1000, 1000), (1010, 1000), (1010, 1010), (1000, 1010)])
    # Raw centroid (3,3) is nowhere near the polygon; shifted by (+1000,+1000) -> (1003,1003) inside.
    far_but_shiftable = _building_object(1, [(2, 2), (4, 2), (4, 4), (2, 4)])
    kept = crop_buildings_to_polygon([far_but_shiftable], poly, shift=(1000.0, 1000.0))
    assert [o.get("id") for o in kept] == ["1"]
    # Without the shift, it must NOT be kept.
    kept_noshift = crop_buildings_to_polygon([far_but_shiftable], poly)
    assert kept_noshift == []


def test_building_frame_shift_to_auto_local_uses_osm_bbox_origin():
    """The building enrichment step (osm_polygon_loader.py) projects OSM lon/lat into a tmerc
    frame anchored at (lat_min, lon_min) with x_0=y_0=0 -- NOT the road network's bare-tmerc
    (lat_0=lon_0=0) + header <offset> frame. `building_frame_shift_to_auto_local` must
    recover the (dx, dy) needed to align cornerGlobal building points into auto-local space:
    project (lon_min, lat_min) through the auto map's own bare-tmerc+offset pipeline."""
    from ultimate_pipeline.domain_gap.local_registration import building_frame_shift_to_auto_local
    auto_proj = "+proj=tmerc +datum=WGS84 +units=m +no_defs"
    # Use a small, round-number GPS bbox and auto_offset so the expected shift is computable
    # independently via a direct pyproj call in this test (no hidden magic numbers).
    from pyproj import CRS, Transformer
    lat_min, lon_min = 48.75, 11.42
    auto_offset = (832671.676, 5458671.104)
    to_auto_global = Transformer.from_crs("EPSG:4326", CRS.from_proj4(auto_proj), always_xy=True)
    gx, gy = to_auto_global.transform(lon_min, lat_min)
    expected = (gx - auto_offset[0], gy - auto_offset[1])

    shift = building_frame_shift_to_auto_local(
        osm_lat_min=lat_min, osm_lon_min=lon_min,
        auto_proj4=auto_proj, auto_offset=auto_offset)
    assert abs(shift[0] - expected[0]) < 1e-6
    assert abs(shift[1] - expected[1]) < 1e-6


def test_compute_local_registration_recovers_and_crops_buildings(tmp_path):
    """End-to-end: buildings recoverable via cornerGlobal should be counted in the cropped
    stats (not silently dropped to 0 just because their container road is excluded)."""
    from ultimate_pipeline.domain_gap.local_registration import compute_local_registration

    def _write_xodr(path, roads_xml, offset=(0.0, 0.0), bare=True, objects_xml=""):
        proj = "+proj=tmerc" if bare else (
            "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs"
        )
        path.write_text(f"""<?xml version="1.0"?>
<OpenDRIVE>
  <header>
    <offset x="{offset[0]}" y="{offset[1]}"/>
    <geoReference><![CDATA[{proj}]]></geoReference>
  </header>
  {roads_xml}
  {objects_xml}
</OpenDRIVE>""", encoding="utf-8")

    # Manual map: single small road near origin (UTM-32N), 4 non-collinear points so the
    # convex hull is a REAL polygon with area, not a degenerate 2-point line. (The original
    # 2-point version made transform_manual_points_to_auto_local's convex_hull degenerate to
    # a zero-area LineString, and placing the "inside" building at the exact bbox midpoint
    # then hinged on a point sitting EXACTLY on that zero-width line -- a floating-point
    # coincidence in GEOS's collinearity predicate that happened to resolve True on this
    # machine's bundled GEOS build but False on CI's, since shapely vendors GEOS separately
    # per-platform wheel even for the identical shapely version. Confirmed by direct
    # reproduction: poly.geom_type was "LineString", poly.area was 0.0, distance from the
    # "inside" point to the line was 0.0. A real quadrilateral gives the bbox-center point
    # many meters of margin from every edge, immune to that class of platform difference.)
    manual_path = tmp_path / "manual.xodr"
    _write_xodr(
        manual_path,
        roads_xml=(
            '<road id="1" junction="-1" length="10">'
            '<planView>'
            '<geometry s="0" x="500000" y="5400000" hdg="0" length="10"/>'
            '<geometry s="10" x="500010" y="5400000" hdg="0" length="10"/>'
            '<geometry s="20" x="500010" y="5400010" hdg="0" length="10"/>'
            '<geometry s="30" x="500000" y="5400010" hdg="0" length="10"/>'
            '</planView></road>'
        ),
        bare=False,
    )

    # Auto map: bare tmerc + zero offset so manual UTM point (500000,5400000) with lon_0=9
    # projects near local-frame coordinates we can predict; simplest is auto_offset=(0,0)
    # and just verify the building nearest the manual road's local footprint survives while
    # a distant one is dropped. Use compute_local_registration's own transform to find the
    # in-footprint location deterministically via a two-pass approach in the test body below.
    auto_road_xml = (
        '<road id="999" junction="-1" length="1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="1"/></planView>'
        '<objects>{buildings}</objects>'
        '</road>'
    )

    # First, run registration with NO buildings to discover the footprint bounds in
    # auto-local space, so we can place synthetic buildings deterministically in/out.
    # building_frame_shift=(0,0): this test places cornerGlobal points directly in
    # auto-local coordinates (via the probed footprint bounds), so no frame correction is
    # wanted here -- the real-world shift value has its own dedicated test
    # (test_building_frame_shift_to_auto_local_uses_osm_bbox_origin).
    auto_path = tmp_path / "auto.xodr"
    _write_xodr(auto_path, roads_xml=auto_road_xml.format(buildings=""))
    probe = compute_local_registration(str(auto_path), str(manual_path), building_frame_shift=(0.0, 0.0))
    minx, miny, maxx, maxy = probe.footprint_local_bounds
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0

    inside_building = (
        f'<object id="b_in" type="building" s="0" t="0" zOffset="0" orientation="absolute" '
        f'height="10" hdg="0" length="0" width="0">'
        f'<outline id="0"><cornerGlobal x="{cx-1}" y="{cy-1}" z="0"/>'
        f'<cornerGlobal x="{cx+1}" y="{cy-1}" z="0"/>'
        f'<cornerGlobal x="{cx+1}" y="{cy+1}" z="0"/>'
        f'<cornerGlobal x="{cx-1}" y="{cy+1}" z="0"/></outline></object>'
    )
    far_x, far_y = minx - 100000, miny - 100000
    outside_building = (
        f'<object id="b_out" type="building" s="0" t="0" zOffset="0" orientation="absolute" '
        f'height="10" hdg="0" length="0" width="0">'
        f'<outline id="0"><cornerGlobal x="{far_x-1}" y="{far_y-1}" z="0"/>'
        f'<cornerGlobal x="{far_x+1}" y="{far_y-1}" z="0"/>'
        f'<cornerGlobal x="{far_x+1}" y="{far_y+1}" z="0"/>'
        f'<cornerGlobal x="{far_x-1}" y="{far_y+1}" z="0"/></outline></object>'
    )

    auto_path2 = tmp_path / "auto2.xodr"
    _write_xodr(
        auto_path2,
        roads_xml=auto_road_xml.format(buildings=inside_building + outside_building),
    )
    result = compute_local_registration(str(auto_path2), str(manual_path), building_frame_shift=(0.0, 0.0))
    assert result.cropped_auto_stats.num_buildings == 1
