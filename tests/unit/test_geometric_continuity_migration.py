from __future__ import annotations

import math
from typing import Any, Dict

import pytest

from ultimate_pipeline.quality.check_geometric_continuity import (
    Geometry,
    Pose,
    _pose_line,
    _pose_arc,
    _pose_spiral_numeric,
    _pose_poly3,
    _pose_param_poly3,
    _pose_for_geometry,
    check_geometric_continuity,
    check_planview_internal_seams,
)


def _approx(a: float, b: float, rel: float = 1e-12, abs_tol: float = 1e-12) -> bool:
    return abs(a - b) < max(rel * max(abs(a), abs(b)), abs_tol)


def _line_geom(x0=0, y0=0, hdg0=0, length=10) -> Geometry:
    return Geometry(s0=0, x0=x0, y0=y0, hdg0=hdg0, length=length, kind="line")


def _arc_geom(curvature=0.1, x0=0, y0=0, hdg0=0, length=10) -> Geometry:
    return Geometry(s0=0, x0=x0, y0=y0, hdg0=hdg0, length=length, kind="arc", curvature=curvature)


def _spiral_geom(curv_start=0, curv_end=0.1, x0=0, y0=0, hdg0=0, length=10) -> Geometry:
    return Geometry(s0=0, x0=x0, y0=y0, hdg0=hdg0, length=length, kind="spiral", curv_start=curv_start, curv_end=curv_end)


def _poly3_geom(a=0, b=0, c=0, d=0, x0=0, y0=0, hdg0=0, length=10) -> Geometry:
    return Geometry(s0=0, x0=x0, y0=y0, hdg0=hdg0, length=length, kind="poly3", poly_a=a, poly_b=b, poly_c=c, poly_d=d)


def _param_poly3_geom(aU=0, bU=1, cU=0, dU=0, aV=0, bV=0, cV=0, dV=0, pRange="normalized", x0=0, y0=0, hdg0=0, length=10) -> Geometry:
    return Geometry(s0=0, x0=x0, y0=y0, hdg0=hdg0, length=length, kind="paramPoly3",
                    param_a_u=aU, param_b_u=bU, param_c_u=cU, param_d_u=dU,
                    param_a_v=aV, param_b_v=bV, param_c_v=cV, param_d_v=dV,
                    param_p_range=pRange)


class TestLineArcMigration:
    def test_line_start_pose(self):
        g = _line_geom(x0=10, y0=20, hdg0=0.5, length=100)
        p = _pose_line(g, 0)
        assert _approx(p.x, 10) and _approx(p.y, 20) and _approx(p.hdg, 0.5)

    def test_line_end_pose(self):
        g = _line_geom(x0=10, y0=20, hdg0=0.5, length=100)
        p = _pose_line(g, 100)
        assert _approx(p.x, 10 + 100 * math.cos(0.5))
        assert _approx(p.y, 20 + 100 * math.sin(0.5))
        assert _approx(p.hdg, 0.5)

    def test_line_mid_pose(self):
        g = _line_geom(x0=0, y0=0, hdg0=0, length=100)
        p = _pose_line(g, 50)
        assert _approx(p.x, 50) and _approx(p.y, 0) and _approx(p.hdg, 0)

    def test_arc_quarter_left(self):
        g = _arc_geom(curvature=0.1, x0=0, y0=0, hdg0=0, length=math.pi / 0.2)
        p = _pose_arc(g, math.pi / 0.4)
        assert _approx(p.x, 10 * math.sin(math.pi / 4), abs_tol=1e-9)
        assert _approx(p.y, 10 * (1 - math.cos(math.pi / 4)), abs_tol=1e-9)
        assert _approx(p.hdg, math.pi / 4, abs_tol=1e-12)

    def test_arc_negative_curvature(self):
        g = _arc_geom(curvature=-0.05, x0=0, y0=0, hdg0=0, length=100)
        p = _pose_arc(g, 50)
        assert _approx(p.hdg, -0.05 * 50, abs_tol=1e-12)
        R = 1 / 0.05
        assert _approx(p.x, R * math.sin(2.5), abs_tol=1e-9)

    def test_arc_zero_curvature_falls_back_to_line(self):
        g = _arc_geom(curvature=0, x0=5, y0=10, hdg0=0.3, length=100)
        p = _pose_arc(g, 50)
        assert _approx(p.x, 5 + 50 * math.cos(0.3))
        assert _approx(p.y, 10 + 50 * math.sin(0.3))
        assert _approx(p.hdg, 0.3)


class TestOtherPrimitivesUnchanged:
    def test_spiral_endpoint(self):
        g = _spiral_geom(curv_start=0, curv_end=0.01, length=100)
        p = _pose_spiral_numeric(g, 100)
        assert 0 <= p.x <= 100
        assert 0 <= p.y <= 100
        assert p.hdg > 0

    def test_spiral_midpoint(self):
        g = _spiral_geom(curv_start=0, curv_end=0.02, length=200)
        p = _pose_spiral_numeric(g, 100)
        assert p.hdg > 0
        assert p.hdg < 2.0

    def test_spiral_short_segment(self):
        g = _spiral_geom(curv_start=0.1, curv_end=0.1, length=0.5)
        p = _pose_spiral_numeric(g, 0.5)
        assert _approx(p.hdg, 0.1 * 0.5, abs_tol=1e-6)

    def test_poly3_flat(self):
        g = _poly3_geom(a=0, b=0, c=0, d=0, x0=0, y0=0, hdg0=0, length=100)
        p = _pose_poly3(g, 50)
        assert _approx(p.x, 50) and _approx(p.y, 0) and _approx(p.hdg, 0)

    def test_poly3_parabolic(self):
        g = _poly3_geom(a=0, b=0, c=0.01, d=0, x0=0, y0=0, hdg0=0, length=100)
        p = _pose_poly3(g, 50)
        assert _approx(p.y, 0.01 * 50 * 50)
        dvdu = 2 * 0.01 * 50
        assert _approx(p.hdg, math.atan2(dvdu, 1.0), abs_tol=1e-12)

    def test_param_poly3_normalized(self):
        g = _param_poly3_geom(aU=0, bU=100, aV=0, bV=0, pRange="normalized", length=100)
        p = _pose_param_poly3(g, 50)
        assert _approx(p.x, 50)
        assert _approx(p.y, 0)

    def test_param_poly3_arclength(self):
        g = _param_poly3_geom(aU=0, bU=1, aV=0, bV=0, pRange="arcLength", length=100)
        p = _pose_param_poly3(g, 50)
        assert _approx(p.x, 50)
        assert _approx(p.y, 0)

    def test_param_poly3_parabolic(self):
        g = _param_poly3_geom(aU=0, bU=100, aV=0, bV=0, cV=0.001, dV=0, pRange="normalized", length=100)
        p50 = _pose_param_poly3(g, 50)
        assert _approx(p50.x, 50)
        p_at_end = _pose_param_poly3(g, 100)
        assert _approx(p_at_end.x, 100)

    def test_for_geometry_dispatch_line(self):
        g = _line_geom(x0=1, y0=2, hdg0=0.5, length=50)
        p = _pose_for_geometry(g, 25)
        assert _approx(p.x, 1 + 25 * math.cos(0.5))
        assert _approx(p.y, 2 + 25 * math.sin(0.5))

    def test_for_geometry_dispatch_arc(self):
        g = _arc_geom(curvature=0.05, x0=0, y0=0, hdg0=0, length=50)
        p = _pose_for_geometry(g, 25)
        assert _approx(p.hdg, 0.05 * 25, abs_tol=1e-12)

    def test_for_geometry_dispatch_spiral(self):
        g = _spiral_geom(curv_start=0, curv_end=0.02, length=100)
        p_spiral = _pose_for_geometry(g, 50)
        p_direct = _pose_spiral_numeric(g, 50)
        assert _approx(p_spiral.x, p_direct.x, abs_tol=1e-12)
        assert _approx(p_spiral.y, p_direct.y, abs_tol=1e-12)
        assert _approx(p_spiral.hdg, p_direct.hdg, abs_tol=1e-12)

    def test_for_geometry_dispatch_poly3(self):
        g = _poly3_geom(a=0, b=0.5, c=0.01, d=0, x0=0, y0=0, hdg0=0.1, length=100)
        p_dispatch = _pose_for_geometry(g, 50)
        p_direct = _pose_poly3(g, 50)
        assert _approx(p_dispatch.x, p_direct.x, abs_tol=1e-12)
        assert _approx(p_dispatch.y, p_direct.y, abs_tol=1e-12)

    def test_for_geometry_dispatch_param_poly3(self):
        g = _param_poly3_geom(aU=0, bU=100, aV=0, bV=5, cV=0.001, x0=0, y0=0, hdg0=0, length=100)
        p_dispatch = _pose_for_geometry(g, 75)
        p_direct = _pose_param_poly3(g, 75)
        assert _approx(p_dispatch.x, p_direct.x, abs_tol=1e-12)
        assert _approx(p_dispatch.y, p_direct.y, abs_tol=1e-12)


class TestMixedChain:
    def test_line_arc_spiral_chain(self):
        road_xodr = (
            '<road id="1" length="30" junction="-1">'
            '  <planView>'
            '    <geometry s="0" x="0" y="0" hdg="0" length="10">'
            '      <line/>'
            '    </geometry>'
            '    <geometry s="10" x="10" y="0" hdg="0" length="10">'
            '      <arc curvature="0.1"/>'
            '    </geometry>'
            '    <geometry s="20" x="19.5" y="5" hdg="1" length="10">'
            '      <spiral curvStart="0.1" curvEnd="0.0"/>'
            '    </geometry>'
            '  </planView>'
            '</road>'
        )
        import xml.etree.ElementTree as ET
        root = ET.fromstring(road_xodr)
        from ultimate_pipeline.quality.check_geometric_continuity import _parse_geometries
        geoms, warns = _parse_geometries(root)
        assert len(geoms) == 3
        assert geoms[0].kind == "line"
        assert geoms[1].kind == "arc"
        assert geoms[2].kind == "spiral"

    def test_mixed_chain_continuity_check_does_not_crash(self):
        xodr = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<OpenDRIVE>'
            '  <header>'
            '    <geoReference>+proj=utm +zone=32 +ellps=WGS84 +datum=WGS84 +units=m +no_defs</geoReference>'
            '  </header>'
            '  <road id="1" length="20" junction="-1">'
            '    <planView>'
            '      <geometry s="0" x="0" y="0" hdg="0" length="10">'
            '        <line/>'
            '      </geometry>'
            '      <geometry s="10" x="10" y="0" hdg="0" length="10">'
            '        <arc curvature="0.05"/>'
            '      </geometry>'
            '    </planView>'
            '    <link>'
            '      <successor elementType="road" elementId="2"/>'
            '    </link>'
            '  </road>'
            '  <road id="2" length="10" junction="-1">'
            '    <planView>'
            '      <geometry s="0" x="19.5" y="5" hdg="1.0" length="10">'
            '        <spiral curvStart="0.05" curvEnd="0.0"/>'
            '      </geometry>'
            '    </planView>'
            '    <link>'
            '      <predecessor elementType="road" elementId="1"/>'
            '    </link>'
            '  </road>'
            '</OpenDRIVE>'
        )
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".xodr", mode="w", delete=False, encoding="utf-8") as f:
            f.write(xodr)
            tmp = f.name
        try:
            report = check_geometric_continuity(tmp)
            assert "issues" in report
        finally:
            os.unlink(tmp)

    def test_mixed_chain_internal_seams(self):
        xodr = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<OpenDRIVE>'
            '  <header>'
            '    <geoReference>+proj=utm +zone=32 +ellps=WGS84 +datum=WGS84 +units=m +no_defs</geoReference>'
            '  </header>'
            '  <road id="1" length="30" junction="-1">'
            '    <planView>'
            '      <geometry s="0" x="0" y="0" hdg="0" length="10">'
            '        <line/>'
            '      </geometry>'
            '      <geometry s="10" x="10" y="0" hdg="0" length="10">'
            '        <arc curvature="0.1"/>'
            '      </geometry>'
            '      <geometry s="20" x="19.5" y="5" hdg="1.0" length="10">'
            '        <spiral curvStart="0.1" curvEnd="0.0"/>'
            '      </geometry>'
            '    </planView>'
            '  </road>'
            '</OpenDRIVE>'
        )
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".xodr", mode="w", delete=False, encoding="utf-8") as f:
            f.write(xodr)
            tmp = f.name
        try:
            report = check_planview_internal_seams(tmp)
            assert "seams" in report
            assert "num_seams" in report
        finally:
            os.unlink(tmp)


class TestContainmentFlags:
    def test_flags_default_false(self):
        from ultimate_pipeline.config.settings import SETTINGS
        assert getattr(SETTINGS, "ENABLE_UNSAFE_SHORT_SEGMENT_MERGE", None) is not None
        assert getattr(SETTINGS, "ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING", None) is not None
        assert getattr(SETTINGS, "ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK", None) is not None
        assert not SETTINGS.ENABLE_UNSAFE_SHORT_SEGMENT_MERGE
        assert not SETTINGS.ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING
        assert not SETTINGS.ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK

    def test_release_profile_rejects_unsafe_flags(self):
        from ultimate_pipeline.config.settings import SETTINGS
        for pname, profile in SETTINGS.RELEASE_PROFILES.items():
            if pname == "DEVELOPMENT":
                continue
            for unsafe_key in (
                "ENABLE_UNSAFE_SHORT_SEGMENT_MERGE",
                "ENABLE_UNSAFE_HEADING_ONLY_SMOOTHING",
                "ENABLE_STRAIGHT_CHORD_CONNECTOR_FALLBACK",
            ):
                assert profile.get(unsafe_key) is None or not profile[unsafe_key], (
                    f"{pname} should not enable {unsafe_key}"
                )
