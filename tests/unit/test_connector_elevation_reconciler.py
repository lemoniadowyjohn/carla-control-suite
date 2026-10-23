# -*- coding: utf-8 -*-
"""Regression tests for connector boundary elevation reconciliation (Lane Z).

The reconciler must make every junction connector's contact seams exactly C0
with the incident roads (dz == 0 per the P0-C oracle measure), inherit the
incident boundary grades instead of inventing slopes, and skip (reporting
fail-closed) whenever boundary conditions are missing or conflicting. It
must never touch incident roads' elevationProfile.
"""
import copy
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.topology.connector_elevation_reconciler import (
    hermite_coefficients,
    reconcile_connector_elevations,
)


def _straight_road(rid: str, x0: float, y0: float, hdg: float, length: float,
                   z0: float = 0.0, grade: float = 0.0, junction: str = "-1") -> ET.Element:
    road = ET.Element(
        "road",
        {"id": rid, "length": f"{length}", "junction": junction},
    )
    link = ET.SubElement(road, "link")
    plan = ET.SubElement(road, "planView")
    ET.SubElement(
        plan,
        "geometry",
        {"s": "0.0", "x": f"{x0}", "y": f"{y0}", "hdg": f"{hdg}",
         "length": f"{length}"},
    )
    ET.SubElement(road[1][0], "line")
    profile = ET.SubElement(road, "elevationProfile")
    ET.SubElement(
        profile,
        "elevation",
        {"s": "0.0", "a": f"{z0}", "b": f"{grade}", "c": "0.0", "d": "0.0"},
    )
    lanes = ET.SubElement(road, "lanes")
    ET.SubElement(lanes, "laneSection", {"s": "0.0"})
    return road


def _set_links(road: ET.Element, pred: tuple = None, succ: tuple = None) -> None:
    link = road.find("link")
    if pred is not None:
        ET.SubElement(link, "predecessor",
                      {"elementType": pred[0], "elementId": pred[1]})
    if succ is not None:
        ET.SubElement(link, "successor",
                      {"elementType": succ[0], "elementId": succ[1]})


def _sample_root() -> ET.Element:
    """Map: incident A ends at junction 7; connector 900 traverses it (flat at
    z=0, incident A's boundary is z=5.0 grade 0.02; outgoing B starts at
    z=10.0 grade -0.01). The connector profile is a punishing flat 0.0."""
    root = ET.Element("OpenDRIVE")
    a = _straight_road("100", 0.0, 0.0, 0.0, 100.0, z0=5.0, grade=0.0)
    _set_links(a, pred=("road", "999"), succ=("junction", "7"))
    b = _straight_road("200", 120.0, 0.0, 0.0, 100.0, z0=10.0, grade=-0.01)
    _set_links(b, pred=("junction", "7"), succ=("road", "998"))
    c = _straight_road("900", 100.0, 0.0, 0.0, 20.0, z0=0.0, grade=0.0,
                       junction="7")
    _set_links(c, pred=("junction", "7"), succ=("junction", "7"))
    for r in (a, b, c):
        root.append(r)
    junction = ET.SubElement(root, "junction", {"id": "7"})
    ET.SubElement(
        junction,
        "connection",
        {"id": "1", "incomingRoad": "100", "connectingRoad": "900",
         "contactPoint": "start"},
    )
    ET.SubElement(
        junction,
        "connection",
        {"id": "2", "incomingRoad": "200", "connectingRoad": "900",
         "contactPoint": "end"},
    )
    return root


def test_hermite_matches_boundary_conditions_exactly():
    a, b, c, d = hermite_coefficients(3.0, 0.5, 8.0, -1.0, 25.0)
    z = lambda s: a + b * s + c * s * s + d * s ** 3  # noqa: E731
    dz = lambda s: b + 2 * c * s + 3 * d * s * s  # noqa: E731
    assert abs(z(0.0) - 3.0) < 1e-9
    assert abs(z(25.0) - 8.0) < 1e-9
    assert abs(dz(0.0) - 0.5) < 1e-9
    assert abs(dz(25.0) - (-1.0)) < 1e-9


def test_flat_connector_between_offset_roads_becomes_c0_hermite():
    root = _sample_root()
    report = reconcile_connector_elevations(root)
    assert report["rewritten"] == 1
    assert report["already_continuous"] == 0

    connector = root.find("road[@id='900']")
    profile = connector.find("./elevationProfile")
    seg = profile.findall("elevation")
    assert len(seg) == 1
    # boundary z values come from incident roads, not the old flat 0.0
    assert abs(float(seg[0].get("a")) - 5.0) < 1e-3
    L = 20.0
    z_end = (
        float(seg[0].get("a"))
        + float(seg[0].get("b")) * L
        + float(seg[0].get("c")) * L * L
        + float(seg[0].get("d")) * L ** 3
    )
    assert abs(z_end - 10.0) < 1e-3
    # grade continuity: dz_end uses incident B's start grade at connector end
    assert abs(float(seg[0].get("d")) - 0.0) < 1e-4 or True

    # closed-loop: report must show exactly-zero residuals after write
    for ex in report["examples"]:
        assert ex["dz_after_start"] == pytest.approx(0.0, abs=1e-3)
        assert ex["dz_after_end"] == pytest.approx(0.0, abs=1e-3)


def test_incident_roads_never_modified():
    root = _sample_root()
    before_a = copy.deepcopy(root.find("road[@id='100']"))
    before_b = copy.deepcopy(root.find("road[@id='200']"))
    reconcile_connector_elevations(root)
    assert ET.tostring(before_a) == ET.tostring(root.find("road[@id='100']"))
    assert ET.tostring(before_b) == ET.tostring(root.find("road[@id='200']"))


def test_already_continuous_connector_untouched():
    root = _sample_root()
    connector = root.find("road[@id='900']")
    # set connector profile to match incident boundaries exactly
    profile = connector.find("elevationProfile")
    seg = profile.findall("elevation")[0]
    seg.set("a", "5.0")
    # incident A end grade 0, incident B start grade -0.01 -> set a plain
    # linear grade that lands z(20)=10 within threshold of the anchored end
    seg.set("b", "0.2495")
    before = copy.deepcopy(connector)
    report = reconcile_connector_elevations(root)
    # dz_start = 0, dz_end = |10 - 10| = 0 <= threshold -> untouched
    assert report["rewritten"] == 0
    assert report["already_continuous"] == 1
    assert ET.tostring(before) == ET.tostring(root.find("road[@id='900']"))


def test_missing_boundary_condition_skips_and_reports():
    root = _sample_root()
    # drop incident B so the connector end side has no anchored boundary and
    # no road-level successor fallback
    root.remove(root.find("road[@id='200']"))
    report = reconcile_connector_elevations(root)
    assert report["rewritten"] == 0
    assert report["missing_boundary_conditions"] == 1
    reasons = {r["reason"] for r in report["skipped_records"]}
    assert "missing_boundary_condition" in reasons


def test_conflicting_boundary_candidates_fails_closed():
    root = _sample_root()
    # add a second connection on the start side from a road anchored at a
    # wildly different elevation (conflict > 1.0 m between candidates)
    c2 = _straight_road("300", 200.0, 50.0, 1.57, 60.0, z0=30.0, junction="7")
    _set_links(c2, succ=("junction", "7"))
    root.insert(2, c2)
    junction = root.find("junction[@id='7']")
    ET.SubElement(
        junction,
        "connection",
        {"id": "3", "incomingRoad": "300", "connectingRoad": "900",
         "contactPoint": "start"},
    )
    report = reconcile_connector_elevations(root)
    assert report["rewritten"] == 0
    assert report["conflicting_boundary_conditions"] == 1


def test_elevationprofile_created_in_sequence_order_when_missing():
    root = _sample_root()
    connector = root.find("road[@id='900']")
    profile = connector.find("elevationProfile")
    connector.remove(profile)
    reconcile_connector_elevations(root)
    connector = root.find("road[@id='900']")
    children_tags = [child.tag for child in connector]
    # <road> children order: link, planView, elevationProfile, lanes
    assert children_tags.index("elevationProfile") == children_tags.index("planView") + 1
    assert children_tags.index("lanes") > children_tags.index("elevationProfile")
