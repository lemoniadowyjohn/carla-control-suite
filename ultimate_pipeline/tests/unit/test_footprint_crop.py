"""RQ3 auto-map-of-record -> manual Grid0828 footprint crop.

Synthetic fixtures only (no real map bytes) -- see
``ultimate_pipeline/domain_gap/footprint_crop.py`` for the full rule set
(a)-(f) this module implements and tests against.
"""
from __future__ import annotations

import copy
import xml.etree.ElementTree as ET

import pytest
from shapely.geometry import Polygon, box

from ultimate_pipeline.domain_gap.footprint_crop import (
    apply_link_consistency,
    build_footprint_polygon,
    crop_auto_to_manual_footprint,
    find_dangling_references,
    resolve_junction_closure,
    select_non_junction_roads,
)

BARE_TMERC = "+proj=tmerc"


# ------------------------------------------------------------------ fixture builders
def _auto_header(offset=(0.0, 0.0)) -> str:
    return (
        f'<header revMajor="1" revMinor="4" name="" version="1.00">'
        f'<geoReference>{BARE_TMERC}</geoReference>'
        f'<offset x="{offset[0]}" y="{offset[1]}" z="0.0" hdg="0.0"/>'
        f'</header>'
    )


def _manual_header() -> str:
    proj = "+proj=tmerc +lat_0=0 +lon_0=9 +k=0.9996 +x_0=500000 +y_0=0 +datum=WGS84 +units=m +no_defs"
    return f'<header><geoReference><![CDATA[{proj}]]></geoReference></header>'


def _manual_xodr(pts) -> ET.Element:
    """A manual map whose planView anchor points are already given directly
    in UTM-32N (manual's native CRS)."""
    geoms = "".join(
        f'<geometry s="{i}" x="{x}" y="{y}" hdg="0" length="1"><line/></geometry>'
        for i, (x, y) in enumerate(pts)
    )
    xml = f'<OpenDRIVE>{_manual_header()}<road id="1" junction="-1" length="{len(pts)}">' \
          f'<planView>{geoms}</planView></road></OpenDRIVE>'
    return ET.fromstring(xml)


def _line_road(rid, x, y, length, hdg=0.0, junction="-1") -> str:
    return (
        f'<road id="{rid}" junction="{junction}" length="{length}">'
        f'<planView><geometry s="0" x="{x}" y="{y}" hdg="{hdg}" length="{length}"><line/></geometry></planView>'
        f'<lanes><laneSection s="0"><center><lane id="0" type="none" level="true"><link/></lane></center>'
        f'<right><lane id="-1" type="driving" level="true"><link/>'
        f'<width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane></right></laneSection></lanes>'
        f'</road>'
    )


def _param_poly3_road(rid, x, y, hdg, length, bu, cu, cv, junction="-1") -> str:
    """A curved road whose anchor point sits OUTSIDE a target region but whose
    paramPoly3 curve swings through it."""
    return (
        f'<road id="{rid}" junction="{junction}" length="{length}">'
        f'<planView><geometry s="0" x="{x}" y="{y}" hdg="{hdg}" length="{length}">'
        f'<paramPoly3 aU="0" bU="{bu}" cU="{cu}" dU="0" aV="0" bV="0" cV="{cv}" dV="0" pRange="normalized"/>'
        f'</geometry></planView></road>'
    )


def _auto_xodr(
    road_xml: str,
    junction_xml: str = "",
    offset=(0.0, 0.0),
    controller_xml: str = "",
    extra_xml: str = "",
) -> ET.Element:
    xml = (
        f'<OpenDRIVE>{_auto_header(offset)}{road_xml}{junction_xml}'
        f'{controller_xml}{extra_xml}</OpenDRIVE>'
    )
    return ET.fromstring(xml)


def _signal_xml(sid, s=0.0, t=0.0) -> str:
    return (
        f'<signal id="{sid}" s="{s}" t="{t}" dynamic="no" orientation="+" '
        f'zOffset="0" country="OpenDRIVE" type="1000001" subtype="-1" value="-1"/>'
    )


def _line_road_with_signals(rid, x, y, length, signal_ids, junction="-1") -> str:
    signals_xml = "".join(_signal_xml(sid) for sid in signal_ids)
    return (
        f'<road id="{rid}" junction="{junction}" length="{length}">'
        f'<planView><geometry s="0" x="{x}" y="{y}" hdg="0" length="{length}"><line/></geometry></planView>'
        f'<signals>{signals_xml}</signals>'
        f'</road>'
    )


def _controller_xml(cid, control_signal_ids) -> str:
    controls = "".join(f'<control signalId="{sid}" type="1"/>' for sid in control_signal_ids)
    return f'<controller id="{cid}" name="{cid}" sequence="0">{controls}</controller>'


# Degenerate convex hull guard: tests build manual maps from >=3 non-collinear
# points so the footprint is a real polygon, not a degenerate line/point.
MANUAL_SQUARE_PTS = [(500000.0, 5400000.0), (500100.0, 5400000.0), (500100.0, 5400100.0), (500000.0, 5400100.0)]


def _footprint_polygon_for_square() -> Polygon:
    manual_root = _manual_xodr(MANUAL_SQUARE_PTS)
    auto_root = _auto_xodr(_line_road(1, 0, 0, 1))
    return build_footprint_polygon(auto_root, manual_root)


# ------------------------------------------------------------------ polygon construction
def test_build_footprint_polygon_rejects_negative_buffer():
    manual_root = _manual_xodr(MANUAL_SQUARE_PTS)
    auto_root = _auto_xodr(_line_road(1, 0, 0, 1))
    with pytest.raises(ValueError):
        build_footprint_polygon(auto_root, manual_root, buffer_m=-1.0)


def test_build_footprint_polygon_buffer_grows_the_area():
    manual_root = _manual_xodr(MANUAL_SQUARE_PTS)
    auto_root = _auto_xodr(_line_road(1, 0, 0, 1))
    poly0 = build_footprint_polygon(auto_root, manual_root, buffer_m=0.0)
    poly10 = build_footprint_polygon(auto_root, manual_root, buffer_m=10.0)
    assert poly10.area > poly0.area
    assert poly0.within(poly10.buffer(1e-6))


# ------------------------------------------------------------------ rule (b): road selection
def test_any_point_selection_keeps_straight_road_whose_anchor_is_inside():
    poly = _footprint_polygon_for_square()
    cx, cy = poly.centroid.x, poly.centroid.y
    auto_root = _auto_xodr(_line_road(1, cx, cy, 1.0))
    kept, _ = select_non_junction_roads(auto_root, poly, selection="any_point")
    assert [r.get("id") for r in kept] == ["1"]


def test_any_point_selection_drops_road_whose_anchor_and_length_cannot_reach_polygon():
    poly = _footprint_polygon_for_square()
    minx, miny, maxx, maxy = poly.bounds
    far_x, far_y = minx - 1_000_000.0, miny - 1_000_000.0
    auto_root = _auto_xodr(_line_road(1, far_x, far_y, 1.0))
    kept, _ = select_non_junction_roads(auto_root, poly, selection="any_point")
    assert kept == []


def test_any_point_selection_curved_road_enters_polygon_only_along_its_curve():
    """A paramPoly3 road whose ANCHOR point is outside the polygon, and whose
    local-frame straight-line endpoint is also outside, but whose curved body
    (sampled by the canonical kernel) swings through the polygon, must still
    be kept under "any_point" -- this is exactly the curve-awareness this
    selection rule exists for."""
    poly = box(0.0, 0.0, 20.0, 20.0)
    # Anchor at (-5, 10), heading 0 (along +x). A paramPoly3 with aU=0,bU=30 (so the
    # curve travels ~30 units of local-u to u=30 at p=1, i.e. x from -5 to 25 over the
    # arc) and a nonzero cV bows the path in +v (local y) by `cV` at the midpoint,
    # then back towards aV=0 at the end (since dV=0, v(p)=cV*p^2 -- not zero at p=1,
    # but the midpoint v(0.5)=cV*0.25 is well inside [0,20] while endpoints can still
    # sit outside x in [0,20] depending on bU). Choose bU so x crosses into [0,20]
    # near the middle of the curve while the straight anchor-to-endpoint chord's
    # perpendicular bulge is what actually enters the box.
    auto_root = _auto_xodr(_param_poly3_road(1, x=-5.0, y=25.0, hdg=0.0, length=30.0, bu=30.0, cu=0.0, cv=-10.0))
    kept, _ = select_non_junction_roads(auto_root, box(0, 0, 20, 20), selection="any_point", sample_spacing_m=0.5)
    # Sanity: the stored anchor (-5,25) and the straight endpoint (25,25) are BOTH
    # outside the box -- only the curve's dip into y~15 (25 + cV*p^2, p up to 1,
    # cV=-10 => min y = 15 at p=1) combined with x in [0,20] over the swing proves
    # curve-awareness, not anchor/endpoint luck.
    assert ET.tostring(auto_root.find(".//geometry"))  # fixture sanity
    anchor_in_box = box(0, 0, 20, 20).contains(Point := __import__("shapely.geometry", fromlist=["Point"]).Point(-5.0, 25.0))
    assert anchor_in_box is False
    assert kept and kept[0].get("id") == "1"


def test_centroid_selection_matches_local_registration_road_centroid_rule():
    poly = box(0.0, 0.0, 10.0, 10.0)
    inside = _auto_xodr(_line_road(1, 4.0, 4.0, 2.0)).find("road")  # anchor (4,4) only point -> centroid (4,4)
    outside = _auto_xodr(_line_road(2, 40.0, 40.0, 2.0)).find("road")
    auto_root = ET.fromstring(f'<OpenDRIVE>{_auto_header()}</OpenDRIVE>')
    auto_root.append(inside)
    auto_root.append(outside)
    kept, _ = select_non_junction_roads(auto_root, poly, selection="centroid")
    assert [r.get("id") for r in kept] == ["1"]


def test_road_selection_skips_junction_member_roads_entirely():
    poly = box(0.0, 0.0, 10.0, 10.0)
    road_xml = _line_road(1, 4.0, 4.0, 1.0) + _line_road(9001, 4.0, 4.0, 1.0, junction="1")
    auto_root = _auto_xodr(road_xml)
    kept, _ = select_non_junction_roads(auto_root, poly, selection="any_point")
    assert [r.get("id") for r in kept] == ["1"]


# ------------------------------------------------------------------ rule (c): junction closure
def _junction_xml(jid, connections) -> str:
    conns = "".join(
        f'<connection id="{i}" incomingRoad="{inc}" connectingRoad="{conn}" contactPoint="start">'
        f'<laneLink from="-1" to="-1"/></connection>'
        for i, (inc, conn) in enumerate(connections)
    )
    return f'<junction id="{jid}" name="{jid}">{conns}</junction>'


def test_junction_kept_when_all_incoming_roads_kept():
    road_xml = (
        _line_road(1, 0, 0, 1) + _line_road(2, 0, 0, 1)
        + _line_road(9001, 0, 0, 1, junction="100") + _line_road(9002, 0, 0, 1, junction="100")
    )
    junction_xml = _junction_xml("100", [("1", "9001"), ("2", "9002")])
    auto_root = _auto_xodr(road_xml, junction_xml)
    kept_j, connecting, reasons, _ = resolve_junction_closure(auto_root, {"1", "2"})
    assert kept_j == {"100"}
    assert connecting == {"9001", "9002"}
    assert reasons == {}


def test_junction_dropped_when_one_incoming_road_not_kept():
    road_xml = (
        _line_road(1, 0, 0, 1) + _line_road(2, 0, 0, 1)
        + _line_road(9001, 0, 0, 1, junction="100") + _line_road(9002, 0, 0, 1, junction="100")
    )
    junction_xml = _junction_xml("100", [("1", "9001"), ("2", "9002")])
    auto_root = _auto_xodr(road_xml, junction_xml)
    # road "2" (incoming of the 2nd connection) is NOT kept -> whole junction drops
    kept_j, connecting, reasons, _ = resolve_junction_closure(auto_root, {"1"})
    assert kept_j == set()
    assert connecting == set()
    assert reasons == {"100": "incoming_road_not_in_footprint"}


def test_connecting_road_never_kept_without_its_dropped_junction():
    """Direct assertion of the 'never keep a connecting road without its
    junction' rule: a connecting road id must not appear in the final kept
    set when its junction is dropped."""
    road_xml = (
        _line_road(1, 0, 0, 1)
        + _line_road(9001, 0, 0, 1, junction="100")
    )
    junction_xml = _junction_xml("100", [("1", "9999_MISSING")])
    auto_root = _auto_xodr(road_xml, junction_xml)
    kept_j, connecting, reasons, dangling = resolve_junction_closure(auto_root, {"1"})
    assert kept_j == set()
    assert "9001" not in connecting
    assert reasons["100"] == "zero_valid_connections_after_dangling_removal"
    assert dangling == 1


def test_nested_junction_closure_converges_via_fixed_point():
    """Junction B's incoming road is a connecting-road member of junction A.
    B must be kept only once A is resolved first -- the fixed-point loop
    must handle this regardless of junction document order."""
    road_xml = (
        _line_road(1, 0, 0, 1)
        + _line_road(9001, 0, 0, 1, junction="100")  # A's connecting road
        + _line_road(9002, 0, 0, 1, junction="200")  # B's connecting road
    )
    # B declared BEFORE A in the document, with B.incomingRoad = A's connecting road 9001.
    junction_xml = _junction_xml("200", [("9001", "9002")]) + _junction_xml("100", [("1", "9001")])
    auto_root = _auto_xodr(road_xml, junction_xml)
    kept_j, connecting, reasons, _ = resolve_junction_closure(auto_root, {"1"})
    assert kept_j == {"100", "200"}
    assert connecting == {"9001", "9002"}


# ------------------------------------------------------------------ rule (d): dangling-link removal
def test_road_level_dangling_predecessor_removed():
    road = ET.fromstring(
        '<road id="1" junction="-1" length="1">'
        '<link><predecessor elementType="road" elementId="999" contactPoint="end"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="1"><line/></geometry></planView>'
        '</road>'
    )
    counts = apply_link_consistency([road], kept_road_ids={"1"}, kept_junction_ids=set())
    assert road.find("link/predecessor") is None
    assert counts["road_link_predecessor_removed"] == 1


def test_road_level_link_to_dropped_junction_removed():
    road = ET.fromstring(
        '<road id="1" junction="-1" length="1">'
        '<link><successor elementType="junction" elementId="42"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="1"><line/></geometry></planView>'
        '</road>'
    )
    counts = apply_link_consistency([road], kept_road_ids={"1"}, kept_junction_ids=set())
    assert road.find("link/successor") is None
    assert counts["road_link_successor_removed"] == 1


def test_boundary_lane_link_removed_when_road_level_link_removed():
    road = ET.fromstring(
        '<road id="1" junction="-1" length="1">'
        '<link><predecessor elementType="road" elementId="999" contactPoint="end"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="1"><line/></geometry></planView>'
        '<lanes><laneSection s="0"><right><lane id="-1" type="driving" level="true">'
        '<link><predecessor id="-1"/></link></lane></right></laneSection></lanes>'
        '</road>'
    )
    apply_link_consistency([road], kept_road_ids={"1"}, kept_junction_ids=set())
    lane_link = road.find(".//lane[@id='-1']/link")
    assert lane_link.find("predecessor") is None


def test_intra_road_lane_link_not_touched_by_link_consistency():
    """Lane links between a road's OWN laneSections (never cross-road) must
    survive untouched even when the road-level predecessor is removed."""
    road = ET.fromstring(
        '<road id="1" junction="-1" length="2">'
        '<link><predecessor elementType="road" elementId="999" contactPoint="end"/></link>'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="2"><line/></geometry></planView>'
        '<lanes>'
        '<laneSection s="0"><right><lane id="-1" type="driving" level="true">'
        '<link><predecessor id="-1"/><successor id="-1"/></link></lane></right></laneSection>'
        '<laneSection s="1"><right><lane id="-1" type="driving" level="true">'
        '<link><predecessor id="-1"/></link></lane></right></laneSection>'
        '</lanes></road>'
    )
    apply_link_consistency([road], kept_road_ids={"1"}, kept_junction_ids=set())
    # First laneSection's predecessor is a boundary link -> removed (road-level predecessor dropped).
    first_link = road.findall(".//laneSection")[0].find(".//lane[@id='-1']/link")
    assert first_link.find("predecessor") is None
    assert first_link.find("successor") is not None  # successor is intra-road -> untouched
    # Second laneSection's predecessor is intra-road (links back to first section) -> untouched.
    second_link = road.findall(".//laneSection")[1].find(".//lane[@id='-1']/link")
    assert second_link.find("predecessor") is not None


def test_find_dangling_references_detects_road_and_junction_and_connection():
    cropped = ET.fromstring(
        '<OpenDRIVE>'
        '<road id="1" junction="-1" length="1">'
        '<link><successor elementType="road" elementId="999"/></link>'
        '</road>'
        '<junction id="5"><connection id="0" incomingRoad="1" connectingRoad="888"/></junction>'
        '</OpenDRIVE>'
    )
    dangling = find_dangling_references(cropped)
    assert len(dangling["road_link"]) == 1
    assert len(dangling["junction_connection"]) == 1


# ------------------------------------------------------------------ end-to-end crop()
def _e2e_fixture():
    manual_root = _manual_xodr(MANUAL_SQUARE_PTS)
    poly = _footprint_polygon_for_square()
    cx, cy = poly.centroid.x, poly.centroid.y
    far_x, far_y = poly.bounds[0] - 1_000_000.0, poly.bounds[1] - 1_000_000.0
    road_xml = (
        _line_road(1, cx, cy, 1.0)                 # inside -> kept
        + _line_road(2, far_x, far_y, 1.0)          # far away -> dropped
        + _line_road(9001, cx, cy, 1.0, junction="100")   # connecting road of junction 100
        + _line_road(9002, far_x, far_y, 1.0, junction="200")  # connecting road of DROPPED junction 200
    )
    junction_xml = (
        _junction_xml("100", [("1", "9001")])
        + _junction_xml("200", [("2", "9002")])  # incoming road "2" is dropped -> junction 200 dropped
    )
    auto_root = _auto_xodr(road_xml, junction_xml)
    return auto_root, manual_root


def test_crop_end_to_end_keeps_inside_drops_outside_and_respects_junction_closure():
    auto_root, manual_root = _e2e_fixture()
    cropped, report = crop_auto_to_manual_footprint(auto_root, manual_root, selection="any_point")
    kept_ids = {r.get("id") for r in cropped.findall("road")}
    assert kept_ids == {"1", "9001"}
    assert {j.get("id") for j in cropped.findall("junction")} == {"100"}
    assert report["counts"]["dangling_references_found"] == 0
    assert report["counts"]["roads_kept_total"] == 2
    assert report["counts"]["junctions_kept"] == 1
    assert report["junctions_dropped_reasons"] == {"200": "incoming_road_not_in_footprint"}


def test_crop_header_is_byte_identical_deep_copy():
    auto_root, manual_root = _e2e_fixture()
    original_header_bytes = ET.tostring(auto_root.find("header"), encoding="unicode")
    cropped, _ = crop_auto_to_manual_footprint(auto_root, manual_root)
    cropped_header_bytes = ET.tostring(cropped.find("header"), encoding="unicode")
    assert cropped_header_bytes == original_header_bytes
    # Source tree itself must be untouched (no in-place mutation).
    assert ET.tostring(auto_root.find("header"), encoding="unicode") == original_header_bytes


def test_crop_is_deterministic_across_repeated_runs():
    auto_root, manual_root = _e2e_fixture()
    out1, _ = crop_auto_to_manual_footprint(copy.deepcopy(auto_root), copy.deepcopy(manual_root))
    out2, _ = crop_auto_to_manual_footprint(copy.deepcopy(auto_root), copy.deepcopy(manual_root))
    assert ET.tostring(out1, encoding="unicode") == ET.tostring(out2, encoding="unicode")


def test_crop_never_mutates_source_roots():
    auto_root, manual_root = _e2e_fixture()
    auto_before = ET.tostring(auto_root, encoding="unicode")
    manual_before = ET.tostring(manual_root, encoding="unicode")
    crop_auto_to_manual_footprint(auto_root, manual_root)
    assert ET.tostring(auto_root, encoding="unicode") == auto_before
    assert ET.tostring(manual_root, encoding="unicode") == manual_before


def test_crop_rejects_invalid_selection_mode():
    auto_root, manual_root = _e2e_fixture()
    with pytest.raises(ValueError):
        crop_auto_to_manual_footprint(auto_root, manual_root, selection="bogus")


# ------------------------------------------------------------------ rule (e): controllers
def test_controller_with_signal_on_kept_road_is_preserved():
    """A controller whose <control signalId=...> resolves to a signal on a
    road that survives the crop must be copied through byte-faithfully."""
    manual_root = _manual_xodr(MANUAL_SQUARE_PTS)
    poly = _footprint_polygon_for_square()
    cx, cy = poly.centroid.x, poly.centroid.y
    road_xml = _line_road_with_signals(1, cx, cy, 1.0, ["501"])
    controller_xml = _controller_xml("10", ["501"])
    auto_root = _auto_xodr(road_xml, controller_xml=controller_xml)
    cropped, report = crop_auto_to_manual_footprint(auto_root, manual_root)
    controllers = cropped.findall("controller")
    assert [c.get("id") for c in controllers] == ["10"]
    assert [ctl.get("signalId") for ctl in controllers[0].findall("control")] == ["501"]
    assert report["counts"]["controllers_total"] == 1
    assert report["counts"]["controllers_kept"] == 1
    assert report["counts"]["controller_controls_removed"] == 0
    assert report["counts"]["controllers_dropped_zero_controls"] == 0
    assert report["counts"]["unresolved_controller_references_found"] == 0


def test_controller_control_on_dropped_road_removed_and_controller_dropped_when_now_empty():
    """A <control signalId=...> whose signal's owning road is dropped by the
    crop must itself be removed; if that empties the controller (and it
    originally had >=1 control), the controller is dropped entirely."""
    manual_root = _manual_xodr(MANUAL_SQUARE_PTS)
    poly = _footprint_polygon_for_square()
    far_x, far_y = poly.bounds[0] - 1_000_000.0, poly.bounds[1] - 1_000_000.0
    road_xml = _line_road_with_signals(1, far_x, far_y, 1.0, ["501"])  # dropped -> signal gone
    controller_xml = _controller_xml("10", ["501"])
    auto_root = _auto_xodr(road_xml, controller_xml=controller_xml)
    cropped, report = crop_auto_to_manual_footprint(auto_root, manual_root)
    assert cropped.findall("controller") == []
    assert report["counts"]["controller_controls_removed"] == 1
    assert report["counts"]["controllers_dropped_zero_controls"] == 1
    assert report["counts"]["controllers_empty_preserved"] == 0
    assert report["counts"]["unresolved_controller_references_found"] == 0


def test_controller_originally_empty_is_preserved():
    """A controller with ZERO <control> children in the SOURCE document is a
    legal (if unusual) document; rule (e) only removes dangling references,
    so this controller must survive untouched, not be dropped as if it had
    been emptied by pruning."""
    manual_root = _manual_xodr(MANUAL_SQUARE_PTS)
    poly = _footprint_polygon_for_square()
    cx, cy = poly.centroid.x, poly.centroid.y
    road_xml = _line_road(1, cx, cy, 1.0)
    controller_xml = '<controller id="20" name="20" sequence="0"/>'
    auto_root = _auto_xodr(road_xml, controller_xml=controller_xml)
    cropped, report = crop_auto_to_manual_footprint(auto_root, manual_root)
    controllers = cropped.findall("controller")
    assert [c.get("id") for c in controllers] == ["20"]
    assert report["counts"]["controllers_empty_preserved"] == 1
    assert report["counts"]["controllers_dropped_zero_controls"] == 0


def test_junction_controller_ref_to_dropped_controller_is_removed():
    """A <junction><controller id=.../> grouping reference naming a
    top-level controller that the crop dropped (because its only control
    dangled) must itself be removed from the surviving junction."""
    manual_root = _manual_xodr(MANUAL_SQUARE_PTS)
    poly = _footprint_polygon_for_square()
    cx, cy = poly.centroid.x, poly.centroid.y
    far_x, far_y = poly.bounds[0] - 1_000_000.0, poly.bounds[1] - 1_000_000.0
    road_xml = (
        _line_road(1, cx, cy, 1.0)
        + _line_road_with_signals(2, far_x, far_y, 1.0, ["501"])  # dropped; owns the signal
        + _line_road(9001, cx, cy, 1.0, junction="100")
    )
    junction_xml = (
        '<junction id="100" name="100">'
        '<connection id="0" incomingRoad="1" connectingRoad="9001" contactPoint="start">'
        '<laneLink from="-1" to="-1"/></connection>'
        '<controller id="10" type="default"/>'
        '</junction>'
    )
    controller_xml = _controller_xml("10", ["501"])
    auto_root = _auto_xodr(road_xml, junction_xml, controller_xml=controller_xml)
    cropped, report = crop_auto_to_manual_footprint(auto_root, manual_root)
    assert cropped.findall("controller") == []  # controller 10 dropped (its only control dangled)
    kept_junction = cropped.find("junction")
    assert kept_junction is not None and kept_junction.get("id") == "100"
    assert kept_junction.findall("controller") == []  # dangling ref removed, not left dangling
    assert report["counts"]["junction_controller_ref_removed"] == 1
    assert report["counts"]["unresolved_controller_references_found"] == 0


def test_unknown_top_level_element_is_preserved():
    """A top-level OpenDRIVE child kind this module has no dedicated rule
    for (e.g. <station>) must be preserved byte-faithfully, never silently
    dropped -- rule (g)."""
    manual_root = _manual_xodr(MANUAL_SQUARE_PTS)
    poly = _footprint_polygon_for_square()
    cx, cy = poly.centroid.x, poly.centroid.y
    road_xml = _line_road(1, cx, cy, 1.0)
    extra_xml = '<station id="99" name="demo"/>'
    auto_root = _auto_xodr(road_xml, extra_xml=extra_xml)
    cropped, report = crop_auto_to_manual_footprint(auto_root, manual_root)
    stations = cropped.findall("station")
    assert len(stations) == 1 and stations[0].get("id") == "99"
    assert report["top_level_accounting"]["station"] == {
        "input_count": 1,
        "kept_count": 1,
        "dropped_count": 0,
    }


def test_crop_is_deterministic_with_controllers_across_repeated_runs():
    """Determinism (rule f) must hold even with controllers/top-level
    pruning in play: two runs over identical inputs produce byte-identical
    output."""
    manual_root = _manual_xodr(MANUAL_SQUARE_PTS)
    poly = _footprint_polygon_for_square()
    cx, cy = poly.centroid.x, poly.centroid.y
    road_xml = _line_road_with_signals(1, cx, cy, 1.0, ["501"])
    controller_xml = _controller_xml("10", ["501"])
    auto_root = _auto_xodr(road_xml, controller_xml=controller_xml)
    out1, _ = crop_auto_to_manual_footprint(copy.deepcopy(auto_root), copy.deepcopy(manual_root))
    out2, _ = crop_auto_to_manual_footprint(copy.deepcopy(auto_root), copy.deepcopy(manual_root))
    assert ET.tostring(out1, encoding="unicode") == ET.tostring(out2, encoding="unicode")


# ------------------------------------------------------------------ CLI: out-dir safety refusals
def test_cli_refuses_out_dir_inside_campaigns(tmp_path):
    from tools.rq3_crop_auto_to_manual_footprint import _assert_safe_out_dir, OutDirUnsafeError

    repo_root = tmp_path / "repo"
    (repo_root / "campaigns" / "sub").mkdir(parents=True)
    with pytest.raises(OutDirUnsafeError):
        _assert_safe_out_dir(repo_root / "campaigns" / "sub", repo_root, overwrite_scratch=False)


def test_cli_refuses_out_dir_colliding_with_registry_pinned_path(tmp_path, monkeypatch):
    from tools.rq3_crop_auto_to_manual_footprint import _assert_safe_out_dir, OutDirUnsafeError
    import tools.rq3_crop_auto_to_manual_footprint as cli_mod

    repo_root = tmp_path / "repo"
    pinned_dir = repo_root / "campaigns" / "x" / "candidate"
    pinned_dir.mkdir(parents=True)
    fake_registry = {"auto_map_of_record": {"path": "campaigns/x/candidate/map.xodr"}}
    monkeypatch.setattr(cli_mod, "PINNED_MAP_REGISTRY", fake_registry)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    with pytest.raises(OutDirUnsafeError):
        _assert_safe_out_dir(pinned_dir, repo_root, overwrite_scratch=False)


def test_cli_refuses_nonempty_out_dir_without_overwrite_flag(tmp_path):
    from tools.rq3_crop_auto_to_manual_footprint import _assert_safe_out_dir, OutDirUnsafeError

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    out_dir = tmp_path / "scratch_out"
    out_dir.mkdir()
    (out_dir / "leftover.txt").write_text("x", encoding="utf-8")
    with pytest.raises(OutDirUnsafeError):
        _assert_safe_out_dir(out_dir, repo_root, overwrite_scratch=False)
    # Explicit override permits it.
    _assert_safe_out_dir(out_dir, repo_root, overwrite_scratch=True)


def test_cli_allows_empty_or_fresh_scratch_out_dir(tmp_path):
    from tools.rq3_crop_auto_to_manual_footprint import _assert_safe_out_dir

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    out_dir = tmp_path / "scratch_fresh"
    # Does not exist yet -- must be allowed without --overwrite-scratch.
    _assert_safe_out_dir(out_dir, repo_root, overwrite_scratch=False)


# ------------------------------------------------------------------ registry: input hash mismatch -> fail closed
def test_registry_verify_pinned_map_fails_closed_on_content_drift(tmp_path):
    from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map, MapRegistryDriftError

    bad_file = tmp_path / "map.xodr"
    bad_file.write_bytes(b"not the pinned content")
    fake_registry = {
        "auto_map_of_record": {
            "path": "map.xodr",
            "sha256": "0" * 64,  # deliberately wrong vs. the real file's content
            "bytes": bad_file.stat().st_size,
            "role": "auto",
            "frame": "test",
        }
    }
    with pytest.raises(MapRegistryDriftError):
        verify_pinned_map("auto_map_of_record", base_dir=tmp_path, registry=fake_registry)


def test_registry_verify_pinned_map_fails_closed_on_missing_file(tmp_path):
    from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map, MapRegistryDriftError

    fake_registry = {
        "manual_grid0828": {
            "path": "does_not_exist.xodr",
            "sha256": "1" * 64,
            "bytes": 123,
            "role": "manual",
            "frame": "test",
        }
    }
    with pytest.raises(MapRegistryDriftError):
        verify_pinned_map("manual_grid0828", base_dir=tmp_path, registry=fake_registry)
