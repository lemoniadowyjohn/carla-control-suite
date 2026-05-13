from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from ultimate_pipeline.diagnostics.xodr_cropper_gps import XODRCropperGPS


def _build_parampoly3_road(
    *,
    road_id: str,
    x0: float,
    y0: float,
    length: float,
    b_u: float,
    b_v: float,
    c_v: float,
) -> ET.Element:
    road = ET.Element("road", id=road_id, length=str(length), junction="-1")
    plan = ET.SubElement(road, "planView")
    geom = ET.SubElement(
        plan,
        "geometry",
        s="0.0",
        x=str(x0),
        y=str(y0),
        hdg="0.0",
        length=str(length),
    )
    ET.SubElement(
        geom,
        "paramPoly3",
        aU="0.0",
        bU=str(b_u),
        cU="0.0",
        dU="0.0",
        aV="0.0",
        bV=str(b_v),
        cV=str(c_v),
        dV="0.0",
        pRange="arcLength",
    )
    return road


def _build_line_road(*, road_id: str, x0: float, y0: float, length: float) -> ET.Element:
    road = ET.Element("road", id=road_id, length=str(length), junction="-1")
    plan = ET.SubElement(road, "planView")
    geom = ET.SubElement(
        plan,
        "geometry",
        s="0.0",
        x=str(x0),
        y=str(y0),
        hdg="0.0",
        length=str(length),
    )
    ET.SubElement(geom, "line")
    return road


def test_road_in_radius_includes_parampoly3_midpoint_and_excludes_fully_outside() -> None:
    effective_offset = {"x": 0.0, "y": 0.0, "z": 0.0, "hdg": 0.0}

    curved_inside = _build_parampoly3_road(
        road_id="inside",
        x0=-200.0,
        y0=100.0,
        length=400.0,
        b_u=1.0,
        b_v=-1.0,
        c_v=0.0025,
    )
    fully_outside = _build_line_road(
        road_id="outside",
        x0=200.0,
        y0=200.0,
        length=50.0,
    )

    # The start point is 200m left and 100m above the crop center, so start-only
    # inclusion would reject this road even though the curve dips through the center.
    assert math.hypot(-200.0, 100.0) > 30.0

    assert (
        XODRCropperGPS._road_in_radius(
            curved_inside,
            cx=0.0,
            cy=0.0,
            radius_m=30.0,
            effective_offset=effective_offset,
        )
        is True
    )
    assert (
        XODRCropperGPS._road_in_radius(
            fully_outside,
            cx=0.0,
            cy=0.0,
            radius_m=30.0,
            effective_offset=effective_offset,
        )
        is False
    )
