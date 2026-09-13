"""ultimate_pipeline/geometry/mesh_continuity_repairer.py -- endpoint()
paramPoly3 blind spot.

MeshContinuityRepairer.endpoint() only computed a real curved endpoint for
<arc>; every other primitive -- including paramPoly3, this pipeline's
dominant real geometry type -- fell through to a straight-line
extrapolation. This is live and default-on (SETTINGS.CONTINUITY_MODE ==
"moderate"), invoked unconditionally from stage_06_links.py, and
moderate_fix() actually mutates x/y/hdg based on the (wrongly-computed)
gap. Verified on the pinned map-of-record: 6803/6807 multi-geometry roads
have a non-final paramPoly3 segment, and 16 real roads were flagged as
needing a fix purely because of this miscalculation -- one example (road
45552) reported an 8.9m "gap" where the true, kernel-computed gap is
~1 micrometer. moderate_fix() would then blend the following geometry's
position 25% toward the wrong point on every pipeline run, corrupting
otherwise-correct chains.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.geometry.mesh_continuity_repairer import MeshContinuityRepairer


def _road_with_curved_parampoly3_then_continuation() -> ET.Element:
    """geometry 1: paramPoly3 curving from (0,0), hdg=0, length=10, bU=10,
    cV=5 -- true endpoint is (10, 5) with heading atan2(10,10)=0.785rad (see
    structure_scanner.py's own regression test for the same verified
    values). geometry 2 is correctly placed at that TRUE endpoint, so a
    correct continuity check must find zero gap."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length="20.0")
    plan = ET.SubElement(road, "planView")
    g1 = ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="10.0")
    ET.SubElement(
        g1, "paramPoly3",
        aU="0", bU="10", cU="0", dU="0",
        aV="0", bV="0", cV="5", dV="0",
        pRange="normalized",
    )
    true_hdg = math.atan2(10.0, 10.0)
    ET.SubElement(
        plan, "geometry", s="10", x="10.0", y="5.0", hdg=f"{true_hdg}", length="10.0",
    )
    ET.SubElement(plan.find("geometry"), "line")  # keep g1 a pure paramPoly3
    return root


def test_scan_roads_advances_prev_element_across_a_three_geometry_chain():
    """Real-map regression, found while verifying the paramPoly3 fix above:
    scan_roads()'s loop tracked prev_x/prev_y/prev_h/prev_len as scalars
    but never reassigned `prev` (the element) to `geo` -- so endpoint() was
    always given geoms[0] as geo_elem, not the actual previous geometry in
    the pair. This was invisible under the old arc-only endpoint() (which
    only used geo_elem to check its primitive TAG, always fell through to
    the line formula for a non-arc geoms[0], and computed position from the
    correctly-tracked scalar args regardless of which element was passed).
    It stopped being invisible once endpoint() needed geo_elem's own
    x/y/hdg/length for paramPoly3 math: on the pinned map-of-record, road
    45552 flipped from a false 8.9m gap (the original bug) to a false
    ~440m gap (this second, previously-masked bug) when only the paramPoly3
    fix was applied without this one. A 3-geometry chain (line, paramPoly3,
    line) is the minimal case that can distinguish "always geoms[0]" from
    "the actual previous geometry" -- geoms[0] is a line, so the bug would
    silently keep evaluating the WRONG (first) geometry as if it were the
    predecessor of the THIRD geometry too.
    """
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length="30.0")
    plan = ET.SubElement(road, "planView")
    g0 = ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="10.0")
    ET.SubElement(g0, "line")
    g1 = ET.SubElement(plan, "geometry", s="10", x="10", y="0", hdg="0", length="10.0")
    ET.SubElement(
        g1, "paramPoly3",
        aU="0", bU="10", cU="0", dU="0",
        aV="0", bV="0", cV="5", dV="0",
        pRange="normalized",
    )
    true_hdg = math.atan2(10.0, 10.0)
    ET.SubElement(plan, "geometry", s="20", x="20.0", y="5.0", hdg=f"{true_hdg}", length="10.0")
    ET.SubElement(plan[2], "line")

    xodr = _write_road_to_tmp(root)
    repairer = MeshContinuityRepairer(str(xodr))
    scan = repairer.scan_roads()

    # If `prev` stayed stuck on g0 (a line), the g1->g2 pair would be
    # evaluated using g0's straight-line endpoint (10,0,0) instead of g1's
    # real paramPoly3 endpoint (20,5,0.785) -- a large, wrong gap.
    assert scan["1"]["max_gap"] == pytest.approx(0.0, abs=1e-6)


def _write_road_to_tmp(root: ET.Element):
    import tempfile

    tmp_dir = Path(tempfile.mkdtemp())
    xodr = tmp_dir / "map.xodr"
    ET.ElementTree(root).write(str(xodr), encoding="utf-8", xml_declaration=True)
    return xodr


def test_endpoint_computes_real_parampoly3_curve_not_straight_line():
    g1 = ET.Element("geometry", s="0", x="0", y="0", hdg="0", length="10")
    ET.SubElement(
        g1, "paramPoly3",
        aU="0", bU="10", cU="0", dU="0",
        aV="0", bV="0", cV="5", dV="0",
        pRange="normalized",
    )

    x, y, hdg = MeshContinuityRepairer.endpoint(0.0, 0.0, 0.0, 10.0, g1)

    assert x == pytest.approx(10.0)
    assert y == pytest.approx(5.0)
    assert hdg == pytest.approx(math.atan2(10.0, 10.0))


def test_scan_roads_reports_zero_gap_for_correctly_continued_parampoly3(tmp_path: Path):
    root = _road_with_curved_parampoly3_then_continuation()
    xodr = tmp_path / "map.xodr"
    ET.ElementTree(root).write(str(xodr), encoding="utf-8", xml_declaration=True)

    repairer = MeshContinuityRepairer(str(xodr))
    scan = repairer.scan_roads()

    assert scan["1"]["max_gap"] == pytest.approx(0.0, abs=1e-6)


def test_moderate_fix_does_not_corrupt_a_correctly_continued_parampoly3_road(
    tmp_path: Path, monkeypatch
):
    """moderate_fix() only blends a segment pair when its computed gap is
    BELOW gap_threshold (3.0m default) -- a gap ABOVE threshold gets the
    road selected for review but is left untouched by the blend step
    itself. cV=2 here (true endpoint (10, 2), old buggy straight-line
    endpoint (10, 0)) keeps the wrong gap at 2.0m, inside the "small enough
    to auto-blend" zone -- the exact real-world corruption case, unlike
    cV=5's 5.0m wrong-gap which happens to land above threshold and
    reproduces regardless of this fix."""
    from ultimate_pipeline.config.settings import SETTINGS

    monkeypatch.setattr(SETTINGS, "CONTINUITY_MODE", "moderate", raising=False)
    monkeypatch.setattr(SETTINGS, "STRICT_PASS_THROUGH", True, raising=False)

    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length="20.0")
    plan = ET.SubElement(road, "planView")
    g1 = ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="10.0")
    ET.SubElement(
        g1, "paramPoly3",
        aU="0", bU="10", cU="0", dU="0",
        aV="0", bV="0", cV="2", dV="0",
        pRange="normalized",
    )
    true_hdg = math.atan2(4.0, 10.0)
    ET.SubElement(plan, "geometry", s="10", x="10.0", y="2.0", hdg=f"{true_hdg}", length="10.0")
    ET.SubElement(plan[1], "line")

    xodr_in = tmp_path / "in.xodr"
    xodr_out = tmp_path / "out.xodr"
    ET.ElementTree(root).write(str(xodr_in), encoding="utf-8", xml_declaration=True)

    MeshContinuityRepairer.run(str(xodr_in), str(xodr_out))

    out_root = ET.parse(str(xodr_out)).getroot()
    geoms = out_root.findall(".//geometry")
    second = geoms[1]
    # Must be untouched: the road was already correctly continuous, so
    # STRICT_PASS_THROUGH's "no roads exceed thresholds -> copy unchanged"
    # path must trigger, not a spurious 25%-blended mutation toward the old
    # wrongly-computed straight-line endpoint (10.0, 0.0).
    assert float(second.get("y")) == pytest.approx(2.0, abs=1e-6)
