"""check_geometric_continuity.py::recompute_geometry_starts_chained_inplace --
zero prior test coverage (confirmed via search). Round-5 WS-B: this function
mishandles paramPoly3 geometries whose declared `length` doesn't match their
polynomial's actual parametric arc length when pRange="arcLength" -- a known
OpenDRIVE-authoring gotcha from OSM/SUMO conversion, already documented in
reports/post_audit_hardening/C33_HEADING_SMOOTHING_V2_RECOMPUTE_STILL_UNSAFE.md
(96% of residual seams involved paramPoly3 as the preceding segment).

Confirmed NOT live: this function is only reachable behind
ENABLE_UNSAFE_GEOMETRY_START_RECOMPUTE (default False, only enabled under
RELEASE_PROFILE=EXPERIMENTAL_UNSAFE) -- the actual map-of-record regen
(PERCEPTION_RELEASE profile) never calls it. This is a defense-in-depth fix,
not a live-blocking one.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.quality.check_geometric_continuity import (
    recompute_geometry_starts_chained_inplace,
)


def _road_with_geoms(*geom_specs) -> ET.Element:
    road = ET.Element("road", id="1", junction="-1")
    pv = ET.SubElement(road, "planView")
    for spec in geom_specs:
        geom = ET.SubElement(
            pv, "geometry",
            s=str(spec["s"]), x=str(spec["x"]), y=str(spec["y"]),
            hdg=str(spec["hdg"]), length=str(spec["length"]),
        )
        if spec["kind"] == "line":
            ET.SubElement(geom, "line")
        elif spec["kind"] == "paramPoly3":
            ET.SubElement(
                geom, "paramPoly3",
                aU=str(spec.get("aU", 0.0)), bU=str(spec.get("bU", 0.0)),
                cU=str(spec.get("cU", 0.0)), dU=str(spec.get("dU", 0.0)),
                aV=str(spec.get("aV", 0.0)), bV=str(spec.get("bV", 0.0)),
                cV=str(spec.get("cV", 0.0)), dV=str(spec.get("dV", 0.0)),
                pRange=spec.get("pRange", "normalized"),
            )
    return road


def _root_with_road(road: ET.Element) -> ET.Element:
    root = ET.Element("OpenDRIVE")
    root.append(road)
    return root


def test_recompute_chains_line_to_line_normally():
    """Baseline: ordinary line-to-line geometry gets chained to the exact
    end pose of the previous segment (established, unguarded behavior)."""
    road = _road_with_geoms(
        {"kind": "line", "s": 0, "x": 0, "y": 0, "hdg": 0, "length": 10},
        # Authored with a small (0.1m, within the 0.5m anchor-preserve
        # threshold) deliberate offset from the correct chained (10, 0, 0)
        # -- recompute must fix it, not treat it as an intentional anchor.
        {"kind": "line", "s": 10, "x": 10.0, "y": 0.1, "hdg": 0, "length": 5},
    )
    root = _root_with_road(road)

    updated = recompute_geometry_starts_chained_inplace(root)

    geoms = road.find("planView").findall("geometry")
    assert updated == 1
    assert abs(float(geoms[1].get("x")) - 10.0) < 1e-9
    assert abs(float(geoms[1].get("y")) - 0.0) < 1e-9


def test_recompute_chains_paramPoly3_normalized_range_normally():
    """A paramPoly3 with pRange="normalized" (p in [0,1], the well-formed
    case) is unaffected by the new arcLength guard -- still recomputed."""
    # u(p) = 10*p (normalized p in [0,1]) -> true endpoint at p=1: u=10, v=0.
    road = _road_with_geoms(
        {"kind": "paramPoly3", "s": 0, "x": 0, "y": 0, "hdg": 0, "length": 10,
         "bU": 10.0, "pRange": "normalized"},
        {"kind": "line", "s": 10, "x": 10.0, "y": 0.1, "hdg": 0, "length": 5},
    )
    root = _root_with_road(road)

    updated = recompute_geometry_starts_chained_inplace(root)

    geoms = road.find("planView").findall("geometry")
    assert updated == 1
    assert abs(float(geoms[1].get("x")) - 10.0) < 1e-9
    assert abs(float(geoms[1].get("y")) - 0.0) < 1e-9


def test_recompute_skips_paramPoly3_arclength_with_mismatched_declared_length():
    """The bug fixture: pRange="arcLength" with bU=0.98 means u(p)=0.98*p, a
    small-but-real mismatch between the naive p=declared_length=10
    evaluation (u=9.8) and the physically correct 10m-arc-length endpoint
    (u=10.0, since v=0 makes arc length == u exactly). The 0.2m discrepancy
    is deliberately kept BELOW this function's separate, pre-existing
    _ANCHOR_PRESERVE_GAP_M=0.5 spatial-anchor guard, so this test actually
    exercises the NEW paramPoly3+arcLength guard, not the old distance-based
    one (a larger discrepancy would be masked by the old guard already
    skipping the rewrite for an unrelated reason -- confirmed by direct
    experimentation before finalizing this fixture). The next geometry is
    authored at the TRUE endpoint (10.0, 0, 0); without the new guard this
    function would corrupt it to the naive (9.8, 0, 0)."""
    road = _road_with_geoms(
        {"kind": "paramPoly3", "s": 0, "x": 0, "y": 0, "hdg": 0, "length": 10,
         "bU": 0.98, "pRange": "arcLength"},
        {"kind": "line", "s": 10, "x": 10.0, "y": 0.0, "hdg": 0, "length": 5},
    )
    root = _root_with_road(road)

    updated = recompute_geometry_starts_chained_inplace(root)

    geoms = road.find("planView").findall("geometry")
    assert updated == 0, "paramPoly3+arcLength must not trigger a rewrite"
    assert float(geoms[1].get("x")) == 10.0
    assert float(geoms[1].get("y")) == 0.0
    assert float(geoms[1].get("hdg")) == 0.0


def test_regression_guard_demonstrates_the_bug_would_corrupt_without_the_guard():
    """Same fixture as above, but manually reproducing the OLD (unguarded)
    evaluation path to prove the guard is actually preventing real
    corruption, not a no-op for an already-impossible scenario."""
    from ultimate_pipeline.quality.check_geometric_continuity import (
        _geometry_from_element,
        _pose_for_geometry,
    )

    road = _road_with_geoms(
        {"kind": "paramPoly3", "s": 0, "x": 0, "y": 0, "hdg": 0, "length": 10,
         "bU": 0.98, "pRange": "arcLength"},
    )
    geom_el = road.find("planView").find("geometry")
    model = _geometry_from_element(geom_el)

    naive_endpoint = _pose_for_geometry(model, max(float(model.length), 0.0))

    # The naive (buggy) evaluation lands at u=0.98*10=9.8, NOT the
    # physically correct 10.0m-arc-length endpoint -- confirming this
    # fixture reproduces the documented "declared length != parametric arc
    # length" mismatch (small enough to stay under the unrelated 0.5m
    # anchor-preserve threshold, so the new guard is what's actually tested).
    assert abs(naive_endpoint.x - 9.8) < 1e-9
    assert abs(naive_endpoint.x - 10.0) > 0.1
