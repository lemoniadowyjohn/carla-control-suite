"""Cross-oracle agreement between the two independent OpenDRIVE geometry
implementations that exist in this repository:

  * ``ultimate_pipeline.geometry.opendrive_geometry_kernel`` -- the kernel
    named as canonical for P1 work package F (RK4 clothoid integration,
    ~30 active production callers as of 2026-09-18).
  * ``opendrive_geometry.primitives`` -- the older root-level package
    (adaptive-Simpson clothoid integration, STRICT/CLAMP/EXTRAPOLATE range
    policies, ~8 active production callers), already used as the oracle
    for ``tests/opendrive_geometry/test_existing_implementations.py``.

These two packages were built independently and do not import from each
other. This module exists to give genuine two-implementation numerical
agreement evidence for spiral/poly3/paramPoly3 -- primitives the existing
``adapters.py`` harness does not cover at all (it only registers
line/arc adapters). Line/arc agreement is already covered there.

This does NOT resolve the architectural duplication between the two
packages (see the P1F handback report) -- it only proves that, for the
curved primitives, both give the same answer to high precision.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s
from opendrive_geometry.primitives import (
    evaluate_spiral,
    evaluate_poly3,
    evaluate_param_poly3,
)


def _geom(kind: str, length: float, **attrs) -> ET.Element:
    g = ET.Element("geometry", {"x": "0", "y": "0", "hdg": "0", "length": str(length)})
    ET.SubElement(g, kind, {k: str(v) for k, v in attrs.items()})
    return g


@pytest.mark.parametrize("s", [0.0, 2.5, 5.0, 7.5, 10.0])
def test_spiral_agrees_with_independent_oracle(s):
    g = _geom("spiral", 10.0, curvStart=0.0, curvEnd=0.2)
    kernel_pose = pose_at_s(g, s)
    oracle_pose = evaluate_spiral(0.0, 0.0, 0.0, 10.0, 0.0, 0.2, s)
    assert kernel_pose.x == pytest.approx(oracle_pose.x, abs=1e-6)
    assert kernel_pose.y == pytest.approx(oracle_pose.y, abs=1e-6)
    assert kernel_pose.heading == pytest.approx(oracle_pose.hdg, abs=1e-6)


@pytest.mark.parametrize("s", [0.0, 1.0, 2.0, 3.0])
def test_poly3_agrees_with_independent_oracle(s):
    g = _geom("poly3", 3.0, a=0.1, b=0.5, c=0.02, d=-0.01)
    kernel_pose = pose_at_s(g, s)
    oracle_pose = evaluate_poly3(0.0, 0.0, 0.0, 3.0, 0.1, 0.5, 0.02, -0.01, s)
    assert kernel_pose.x == pytest.approx(oracle_pose.x, abs=1e-9)
    assert kernel_pose.y == pytest.approx(oracle_pose.y, abs=1e-9)
    assert kernel_pose.heading == pytest.approx(oracle_pose.hdg, abs=1e-9)


@pytest.mark.parametrize("p_range", ["normalized", "arcLength"])
@pytest.mark.parametrize("s", [0.0, 2.5, 5.0, 10.0])
def test_parampoly3_agrees_with_independent_oracle(p_range, s):
    g = _geom(
        "paramPoly3", 10.0, pRange=p_range,
        aU=0, bU=1, cU=0.05, dU=-0.002,
        aV=0, bV=0.1, cV=0.01, dV=0.0,
    )
    kernel_pose = pose_at_s(g, s)
    oracle_pose = evaluate_param_poly3(
        0.0, 0.0, 0.0, 10.0,
        0, 1, 0.05, -0.002,
        0, 0.1, 0.01, 0.0,
        p_range, s,
    )
    assert kernel_pose.x == pytest.approx(oracle_pose.x, abs=1e-9)
    assert kernel_pose.y == pytest.approx(oracle_pose.y, abs=1e-9)
    assert kernel_pose.heading == pytest.approx(oracle_pose.hdg, abs=1e-9)
