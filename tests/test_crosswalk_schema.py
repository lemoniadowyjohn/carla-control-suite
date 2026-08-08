#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R06 — CARLA 0.9.16 crosswalk schema tests (offline, no CARLA runtime).

Gates:
- codec round trip: carla_local_corners -> carla_world_corners == original
  world outline, exact inverse, for every planView primitive and random
  (s, t, hdg)
- documented axis semantics of the CARLA 0.9.16 "Unreal Y hack" (v -> -v)
- reference_pose_at_s: analytic ground truth for line/arc/paramPoly3
- XML emission contract: <object type="crosswalk"><outline><cornerLocal u v z>
  only, closed, no cornerGlobal (R05 lemma)
- candidate artifact: every crosswalk object decodes to a closed polygon
"""
from __future__ import annotations

import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
R = REPO / "reports" / "post_audit_hardening" / "20260807T000000Z"

from ultimate_pipeline.enrichment.crosswalk_schema import (  # noqa: E402
    carla_local_corners,
    carla_world_corners,
    reference_pose_at_s,
)
from ultimate_pipeline.enrichment.object_injector import (  # noqa: E402
    CrosswalkInjector,
    CrosswalkSpec,
)
from phase_q.common import strip_xml_namespaces  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures: minimal XODR roads per planView primitive
# ---------------------------------------------------------------------------

def _road(length: float, geom_body: str, x=0.0, y=0.0, hdg=0.0, gs=0.0) -> ET.Element:
    return ET.fromstring(
        f'<road id="1" length="{length}"><planView>'
        f'<geometry s="{gs}" x="{x}" y="{y}" hdg="{hdg}" length="{length}">'
        f"{geom_body}</geometry></planView></road>"
    )


LINE_ROAD = _road(100.0, "<line/>", x=5.0, y=7.0, hdg=0.5)
EAST_ROAD = _road(100.0, "<line/>", hdg=0.0)
ARC_ROAD = _road(200.0, '<arc curvature="0.01"/>', hdg=0.0)
PARAM_ROAD = _road(20.0, '<paramPoly3 aU="0" bU="20" cU="0" dU="0" '
                          'aV="0" bV="0" cV="0" dV="0" pRange="normalized"/>',
                   hdg=0.3)
PARAM_ROAD_ARCLEN = _road(20.0, '<paramPoly3 aU="0" bU="1" cU="0" dU="0" '
                                'aV="0" bV="0" cV="0" dV="0"/>', hdg=0.0)
SPIRAL_ROAD = _road(100.0, '<spiral curvStart="0.0" curvEnd="0.02"/>', hdg=0.1)
POLY3_ROAD = _road(50.0, '<poly3 a="0" b="0.1" c="0" d="0"/>', hdg=0.2)


# ---------------------------------------------------------------------------
# Codec round trip
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("road", [LINE_ROAD, ARC_ROAD, PARAM_ROAD,
                                  PARAM_ROAD_ARCLEN, SPIRAL_ROAD, POLY3_ROAD])
@pytest.mark.parametrize("t", [-1.5, 0.0, 2.25])
@pytest.mark.parametrize("hdg", [0.0, math.pi / 6, -1.1])
def test_codec_round_trip(road, t, hdg):
    length = float(road.get("length"))
    for s in (length * 0.15, length * 0.5, length * 0.9):
        pose = reference_pose_at_s(road, s)
        assert pose is not None
        outline = [
            (pose.x + 4.0, pose.y - 3.0, 0.0),
            (pose.x - 4.0, pose.y - 3.0, 0.0),
            (pose.x - 4.0, pose.y + 3.0, 0.0),
            (pose.x + 4.0, pose.y + 3.0, 0.0),
            (pose.x + 4.0, pose.y - 3.0, 0.0),
        ]
        local = carla_local_corners(outline, pose, t, hdg)
        back = carla_world_corners(local, pose, t, hdg)
        for (ax, ay, az), (bx, by, bz) in zip(outline, back):
            assert (ax - bx) ** 2 + (ay - by) ** 2 < 1e-18
            assert az == bz == 0.0


def test_codec_axis_semantics_unreal_y_hack():
    """Documented CARLA 0.9.16 convention (v -> -v).

    Eastbound straight road (theta=0), t=0, hdg=0: the world point
    (bx + du, by - dv) encodes to (u, v) = (du, dv); positive v therefore
    points in -Y, the direction CARLA negates before TransformPoint.
    """
    pose = reference_pose_at_s(EAST_ROAD, 30.0)  # (30, 0, 0)
    bx, by = pose.x, pose.y
    local = carla_local_corners([(bx + 3.0, by - 2.0, 0.0)], pose, 0.0, 0.0)
    assert local[0][0] == pytest.approx(3.0, abs=1e-12)
    assert local[0][1] == pytest.approx(2.0, abs=1e-12)
    assert local[0][2] == 0.0


def test_codec_pivot_lateral_offset():
    """t shifts the pivot perpendicular to the reference line (R05)."""
    pose = reference_pose_at_s(EAST_ROAD, 30.0)
    local = carla_local_corners([(pose.x, pose.y + 1.0, 0.0)], pose, t=2.0, hdg=0.0)
    back = carla_world_corners(local, pose, t=2.0, hdg=0.0)
    assert back[0][0] == pytest.approx(pose.x, abs=1e-12)
    assert back[0][1] == pytest.approx(pose.y + 1.0, abs=1e-12)


# ---------------------------------------------------------------------------
# reference_pose_at_s analytic ground truth
# ---------------------------------------------------------------------------

def test_pose_line():
    pose = reference_pose_at_s(LINE_ROAD, 20.0)
    assert pose.x == pytest.approx(5.0 + 20.0 * math.cos(0.5), abs=1e-9)
    assert pose.y == pytest.approx(7.0 + 20.0 * math.sin(0.5), abs=1e-9)
    assert pose.hdg == pytest.approx(0.5, abs=1e-12)


def test_pose_arc_quarter():
    pose = reference_pose_at_s(ARC_ROAD, math.pi / (2.0 * 0.01) / 2.0)
    s = math.pi / (2.0 * 0.01) / 2.0
    h = 0.01 * s
    assert pose.hdg == pytest.approx(h, abs=1e-12)
    assert pose.x == pytest.approx(100.0 * math.sin(h), abs=1e-9)
    assert pose.y == pytest.approx(100.0 * (1.0 - math.cos(h)), abs=1e-9)


def test_pose_param_poly3_normalized():
    pose = reference_pose_at_s(PARAM_ROAD, 10.0)
    # p = s/length = 0.5; u = bU*p = 10; v = 0
    assert pose.x == pytest.approx(10.0 * math.cos(0.3), abs=1e-9)
    assert pose.y == pytest.approx(10.0 * math.sin(0.3), abs=1e-9)


def test_pose_param_poly3_missing_prange_is_arclength():
    pose = reference_pose_at_s(PARAM_ROAD_ARCLEN, 10.0)
    # pRange absent -> arcLength (CARLA default): u = bU * s = 10
    assert pose.x == pytest.approx(10.0, abs=1e-9)
    assert pose.y == pytest.approx(0.0, abs=1e-9)


def test_pose_out_of_road_clamped():
    pose = reference_pose_at_s(LINE_ROAD, 500.0)
    assert pose is not None  # clamped to road length, evaluated at end


# ---------------------------------------------------------------------------
# XML emission contract
# ---------------------------------------------------------------------------

MINI_XODR = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<OpenDRIVE><header revMajor="1" revMinor="0"/>'
    '<road id="1" length="50"><planView>'
    '<geometry s="0" x="0" y="0" hdg="0" length="50"><line/></geometry>'
    '</planView></road></OpenDRIVE>'
)


def test_injector_emits_corner_local_only():
    root = ET.fromstring(strip_xml_namespaces(MINI_XODR))
    spec = CrosswalkSpec(
        osm_id="t1", crossing_type="zebra",
        start_m=(5.0, -4.0), end_m=(5.0, 4.0),
        road_id="1", s=5.0, t=0.0,
    )
    stats = CrosswalkInjector.inject(root, [spec])
    assert stats["written"] == 1
    obj = root.find(".//object[@id='crosswalk_t1']")
    assert obj is not None
    assert obj.get("type") == "crosswalk"
    assert obj.get("name") == "crosswalk_zebra"
    ol = obj.find("outline")
    assert ol is not None
    corners = ol.findall("cornerLocal")
    assert len(corners) == 5
    assert ol.findall("cornerGlobal") == []
    pts = [(float(c.get("u")), float(c.get("v")), float(c.get("z"))) for c in corners]
    assert pts[0] == pts[-1]
    pose = reference_pose_at_s(root.find("road"), 5.0)
    world = carla_world_corners(pts, pose, t=0.0, hdg=float(obj.get("hdg")))
    # matches the OSM quad built by _crosswalk_outline
    assert world[0] == pytest.approx((7.0, -4.0, 0.0), abs=1e-3)
    assert world[2] == pytest.approx((3.0, 4.0, 0.0), abs=1e-3)


def test_injector_skips_when_no_geometry():
    bare = ET.fromstring(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<OpenDRIVE><road id="9" length="50"></road></OpenDRIVE>')
    spec = CrosswalkSpec(
        osm_id="t2", crossing_type="zebra",
        start_m=(0.0, 0.0), end_m=(0.0, 4.0),
        road_id="9", s=1.0, t=0.0,
    )
    stats = CrosswalkInjector.inject(bare, [spec])
    assert stats["written"] == 0
    assert stats["skipped_no_geometry"] == 1


# ---------------------------------------------------------------------------
# Candidate artifact gate (runs against the regenerated candidate)
# ---------------------------------------------------------------------------

def test_candidate_all_crosswalks_decode_to_closed_polygons():
    text = (R / "candidate_crosswalk_enriched.xodr").read_text(
        encoding="utf-8", errors="replace")
    root = ET.fromstring(strip_xml_namespaces(text))
    for road in root.findall("road"):
        objs = road.find("objects")
        if objs is None:
            continue
        for o in objs.findall("object"):
            if (o.get("type") or "").lower() != "crosswalk":
                continue
            ol = o.find("outline")
            assert ol is not None, o.get("id")
            corners = [(float(c.get("u", "0")), float(c.get("v", "0")),
                        float(c.get("z", "0"))) for c in ol.findall("cornerLocal")]
            assert len(corners) >= 4, o.get("id")
            s = float(o.get("s", "0") or "0")
            pose = reference_pose_at_s(road, s)
            assert pose is not None, o.get("id")
            world = carla_world_corners(
                corners, pose, t=float(o.get("t", "0") or "0"),
                hdg=float(o.get("hdg", "0") or "0"))
            assert len(world) >= 4
            assert world[0][0] == world[-1][0] and world[0][1] == world[-1][1]
            area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(world, world[1:]))
            assert abs(area) / 2.0 > 1e-6, o.get("id")


def test_n17_no_invalid_polygons():
    n17 = json.loads((R / "N17_FINAL_SEMANTIC_INTEGRITY.json").read_text())
    assert n17["bad_polygons"] == []
    assert n17["bad_s"] == []
    assert n17["checks"]["no_invalid_polygons"] is True
