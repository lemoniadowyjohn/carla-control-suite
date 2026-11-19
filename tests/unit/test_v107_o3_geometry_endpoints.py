"""V107 O3: reconciliation uses canonical OpenDRIVE primitive endpoints."""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.topology.orphan_road_repair import (
    _closest_gap,
    _reconcile_road_points,
)


def _road(x: float, y: float, primitive: str, *, length=100.0, elevation=None):
    if elevation is None:
        elevation = "<elevation s='0' a='0' b='0' c='0' d='0'/>"
    return ET.fromstring(
        f"<road id='1' length='{length}'>"
        f"<planView><geometry s='0' x='{x}' y='{y}' hdg='0' length='{length}'>"
        f"{primitive}</geometry></planView>"
        f"<elevationProfile>{elevation}</elevationProfile>"
        "</road>"
    )


def test_true_arc_endpoint_connects_to_next_road():
    curvature = 0.01
    length = 100.0
    x_end = math.sin(curvature * length) / curvature
    y_end = (1 - math.cos(curvature * length)) / curvature
    first = _road(0, 0, "<arc curvature='0.01'/>")
    second = _road(x_end, y_end, "<line/>", length=10)
    gap, _ = _closest_gap(
        _reconcile_road_points(first), _reconcile_road_points(second)
    )
    assert gap == pytest.approx(0.0, abs=1e-6)


def test_normalized_parampoly3_endpoint_is_not_straight_projected():
    primitive = (
        "<paramPoly3 aU='0' bU='100' cU='0' dU='0' "
        "aV='0' bV='20' cV='0' dV='0' pRange='normalized'/>"
    )
    first = _road(0, 0, primitive)
    second = _road(100, 20, "<line/>", length=10)
    gap, _ = _closest_gap(
        _reconcile_road_points(first), _reconcile_road_points(second)
    )
    assert gap == pytest.approx(0.0, abs=1e-6)


def test_elevation_at_geometry_end_is_not_first_record_constant():
    first = _road(
        0, 0, "<line/>",
        elevation="<elevation s='0' a='2' b='0.1' c='0' d='0'/>",
    )
    points = _reconcile_road_points(first)
    assert len(points) == 2
    assert points[0][2] == pytest.approx(2.0)
    assert points[1][2] == pytest.approx(12.0)


def test_unsupported_geometry_does_not_invent_straight_endpoint():
    first = _road(0, 0, "<unsupported/>")
    assert _reconcile_road_points(first) == []
