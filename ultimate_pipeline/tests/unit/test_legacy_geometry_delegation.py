#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression tests for legacy geometry kernel delegation (OC-02).

Verifies that GeometryCalculator delegates spiral and paramPoly3
to the canonical opendrive_geometry_kernel, and that all primitive
types produce results matching the kernel.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.geometry.geometry_math import GeometryCalculator
from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint as kernel_endpoint


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_geom(tag: str, length: float = 10.0, **attrs) -> ET.Element:
    """Create a <geometry> element wrapping the given primitive."""
    geom = ET.Element("geometry", attrib={
        "x": "0.0", "y": "0.0", "hdg": "0.0", "s": "0.0",
        "length": str(length),
    })
    ET.SubElement(geom, tag, attrib=attrs)
    return geom


def _world_frame(x0, y0, hdg0, local_x, local_y, local_hdg):
    """Transform local-frame result to world frame."""
    cos_h = math.cos(hdg0)
    sin_h = math.sin(hdg0)
    x_new = x0 + cos_h * local_x - sin_h * local_y
    y_new = y0 + sin_h * local_x + cos_h * local_y
    hdg_new = hdg0 + local_hdg
    return x_new, y_new, hdg_new


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLineDelegate:
    """Line endpoint via GeometryCalculator matches kernel."""

    def test_line_matches_kernel(self):
        geom = _make_geom("line", length=5.0)
        x0, y0, hdg = 1.0, 2.0, 0.3
        calc_result = GeometryCalculator.get_endpoint(x0, y0, hdg, 5.0, geom)
        kp = kernel_endpoint(geom)
        expected = _world_frame(x0, y0, hdg, kp.x, kp.y, kp.heading)
        for a, b in zip(calc_result, expected):
            assert a == pytest.approx(b, abs=1e-9)


class TestArcDelegate:
    """Arc endpoint via GeometryCalculator matches kernel."""

    def test_arc_matches_kernel(self):
        geom = _make_geom("arc", length=10.0, curvature="0.1")
        x0, y0, hdg = 0.5, -1.0, 0.0
        calc_result = GeometryCalculator.get_endpoint(x0, y0, hdg, 10.0, geom)
        kp = kernel_endpoint(geom)
        expected = _world_frame(x0, y0, hdg, kp.x, kp.y, kp.heading)
        for a, b in zip(calc_result, expected):
            assert a == pytest.approx(b, abs=1e-9)


class TestSpiralDelegate:
    """Spiral endpoint via GeometryCalculator matches kernel RK4 integration."""

    def test_spiral_matches_kernel(self):
        geom = _make_geom("spiral", length=20.0, curvStart="0.0", curvEnd="0.1")
        x0, y0, hdg = 0.0, 0.0, 0.0
        calc_result = GeometryCalculator.get_endpoint(x0, y0, hdg, 20.0, geom)
        kp = kernel_endpoint(geom)
        expected = _world_frame(x0, y0, hdg, kp.x, kp.y, kp.heading)
        for a, b in zip(calc_result, expected):
            assert a == pytest.approx(b, abs=1e-6)

    def test_spiral_nonzero_heading(self):
        geom = _make_geom("spiral", length=15.0, curvStart="0.01", curvEnd="0.05")
        x0, y0, hdg = 10.0, 20.0, 0.5
        calc_result = GeometryCalculator.get_endpoint(x0, y0, hdg, 15.0, geom)
        kp = kernel_endpoint(geom)
        expected = _world_frame(x0, y0, hdg, kp.x, kp.y, kp.heading)
        for a, b in zip(calc_result, expected):
            assert a == pytest.approx(b, abs=1e-6)


class TestParamPoly3Delegate:
    """paramPoly3 endpoint via GeometryCalculator matches kernel."""

    def test_normalized_matches_kernel(self):
        geom = _make_geom("paramPoly3", length=8.0, pRange="normalized",
                          aU="0", bU="1", cU="0", dU="0",
                          aV="0", bV="0", cV="0.5", dV="0")
        x0, y0, hdg = 0.0, 0.0, 0.0
        calc_result = GeometryCalculator.get_endpoint(x0, y0, hdg, 8.0, geom)
        kp = kernel_endpoint(geom)
        expected = _world_frame(x0, y0, hdg, kp.x, kp.y, kp.heading)
        for a, b in zip(calc_result, expected):
            assert a == pytest.approx(b, abs=1e-9)

    def test_arc_length_matches_kernel(self):
        geom = _make_geom("paramPoly3", length=12.0, pRange="arcLength",
                          aU="0", bU="1", cU="0.1", dU="0",
                          aV="0", bV="0", cV="0", dV="0.01")
        x0, y0, hdg = 5.0, 3.0, 1.0
        calc_result = GeometryCalculator.get_endpoint(x0, y0, hdg, 12.0, geom)
        kp = kernel_endpoint(geom)
        expected = _world_frame(x0, y0, hdg, kp.x, kp.y, kp.heading)
        for a, b in zip(calc_result, expected):
            assert a == pytest.approx(b, abs=1e-9)

    def test_with_offset_heading(self):
        geom = _make_geom("paramPoly3", length=10.0, pRange="normalized",
                          aU="0", bU="1", cU="0", dU="0",
                          aV="0", bV="0", cV="0", dV="0")
        x0, y0, hdg = 100.0, 200.0, math.pi / 4
        calc_result = GeometryCalculator.get_endpoint(x0, y0, hdg, 10.0, geom)
        kp = kernel_endpoint(geom)
        expected = _world_frame(x0, y0, hdg, kp.x, kp.y, kp.heading)
        for a, b in zip(calc_result, expected):
            assert a == pytest.approx(b, abs=1e-9)


class TestInvalidInput:
    """Malformed or unsupported input must fail closed."""

    def test_invalid_pRange(self):
        geom = _make_geom("paramPoly3", length=5.0, pRange="invalid",
                          aU="0", bU="1", cU="0", dU="0",
                          aV="0", bV="0", cV="0", dV="0")
        with pytest.raises(ValueError, match="unsupported pRange"):
            GeometryCalculator.get_endpoint(0.0, 0.0, 0.0, 5.0, geom)

    def test_nonfinite_coefficient(self):
        geom = _make_geom("paramPoly3", length=5.0, pRange="normalized",
                          aU="inf", bU="1", cU="0", dU="0",
                          aV="0", bV="0", cV="0", dV="0")
        with pytest.raises((ValueError, Exception)):
            GeometryCalculator.get_endpoint(0.0, 0.0, 0.0, 5.0, geom)

    def test_unsupported_geometry_tag(self):
        geom = _make_geom("unknown_tag", length=5.0)
        with pytest.raises(ValueError, match="Unsupported geometry type"):
            GeometryCalculator.get_endpoint(0.0, 0.0, 0.0, 5.0, geom)
