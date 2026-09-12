"""Regression coverage for the SUMO-emitted road 45622 tangent reversal."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint, pose_at_s
from ultimate_pipeline.geometry.parampoly3_tangent_repair import (
    find_parampoly3_tangent_reversals,
    repair_parampoly3_tangent_reversals,
)


def _road_45622_fixture() -> ET.Element:
    """Minimized exact geometry records 59--62 from the pinned map of record."""
    return ET.fromstring(
        """
        <OpenDRIVE>
          <road id="45622" length="253.41800876" junction="-1">
            <planView>
              <geometry s="223.66822449" x="10266.710029" y="10055.466286" hdg="2.91838953" length="3.27430471">
                <paramPoly3 aU="0.00000000" bU="2.44776498" cU="2.24738881" dU="-1.49964058" aV="-0.00000000" bV="-0.00000000" cV="-2.13313067" dV="1.46954514" pRange="normalized" />
              </geometry>
              <geometry s="226.9425292" x="10263.740673" y="10056.820752" hdg="2.97658731" length="1.31472225">
                <paramPoly3 aU="0.00000000" bU="1.85997989" cU="-1.45592098" dU="0.00000000" aV="-0.00000000" bV="0.00000000" cV="0.84832888" dV="0.00000000" pRange="normalized" />
              </geometry>
              <geometry s="228.25725146" x="10263.202758" y="10056.050315" hdg="1.96075872" length="2.11958313">
                <paramPoly3 aU="0.00000000" bU="1.57925479" cU="1.27627779" dU="-0.90384007" aV="-0.00000000" bV="-0.00000000" cV="-1.68072136" dV="0.89030668" pRange="normalized" />
              </geometry>
              <geometry s="230.37683459" x="10263.191888" y="10058.155960" hdg="1.50822469" length="2.90050738">
                <paramPoly3 aU="0.00000000" bU="2.17495498" cU="2.17253876" dU="-1.45105784" aV="0.00000000" bV="0.00000000" cV="-0.24006230" dV="0.09754589" pRange="normalized" />
              </geometry>
            </planView>
          </road>
        </OpenDRIVE>
        """
    )


def _angle_delta(first: float, second: float) -> float:
    return (first - second + math.pi) % (2.0 * math.pi) - math.pi


def test_repair_replaces_exact_road_45622_fold_without_moving_boundaries() -> None:
    root = _road_45622_fixture()
    road = root.find("road")
    assert road is not None
    plan_view = road.find("planView")
    assert plan_view is not None
    original = plan_view.findall("geometry")
    original_start = pose_at_s(original[1], 0.0)
    original_end = endpoint(original[2])
    after_pair_s = float(original[3].get("s", "nan"))

    candidates = find_parampoly3_tangent_reversals(root)

    assert len(candidates) == 1
    assert candidates[0].road_id == "45622"
    assert candidates[0].geometry_index == 1
    assert candidates[0].successor_index == 2
    assert candidates[0].derivative_roots == (0.6387640248167864,)
    assert abs(candidates[0].heading_delta_deg) > 179.999

    report = repair_parampoly3_tangent_reversals(root)

    assert report["detected"] == 1
    assert report["repaired"] == 1
    assert report["preserved"] == 0
    record = report["records"][0]
    assert record["action"] == "REPAIRED_FIVE_PARAMPOLY3_ARC_APPROXIMATIONS"
    assert record["replacement_max_abs_curvature"] < record["source_max_abs_curvature"]
    assert record["endpoint_gap_m"] < 1e-7
    assert record["endpoint_heading_gap_rad"] < 1e-7

    repaired = plan_view.findall("geometry")
    assert len(repaired) == 7
    replacement = repaired[1:6]
    assert all(item.find("paramPoly3") is not None for item in replacement)
    assert math.isclose(float(replacement[0].get("s", "nan")), 226.9425292, abs_tol=1e-9)
    assert math.isclose(
        float(replacement[-1].get("s", "nan")) + float(replacement[-1].get("length", "nan")),
        after_pair_s,
        abs_tol=1e-8,
    )
    repaired_start = pose_at_s(replacement[0], 0.0)
    repaired_end = endpoint(replacement[-1])
    assert math.hypot(repaired_start.x - original_start.x, repaired_start.y - original_start.y) < 1e-8
    assert abs(_angle_delta(repaired_start.heading, original_start.heading)) < 1e-8
    assert math.hypot(repaired_end.x - original_end.x, repaired_end.y - original_end.y) < 1e-7
    assert abs(_angle_delta(repaired_end.heading, original_end.heading)) < 1e-7
    for index, (first, second) in enumerate(zip(repaired, repaired[1:])):
        first_end = endpoint(first)
        second_start = pose_at_s(second, 0.0)
        # The unchanged predecessor is stored at eight decimal places; its
        # historical analytic-endpoint rounding error is 0.79 micrometres.
        tolerance = 1e-6 if index == 0 else 1e-7
        assert math.hypot(first_end.x - second_start.x, first_end.y - second_start.y) < tolerance
        assert abs(_angle_delta(first_end.heading, second_start.heading)) < 1e-7
    assert find_parampoly3_tangent_reversals(root) == []


def test_folded_parampoly_without_near_pi_boundary_reversal_is_preserved() -> None:
    root = _road_45622_fixture()
    road = root.find("road")
    assert road is not None
    successor = road.find("./planView/geometry[@s='228.25725146']")
    assert successor is not None
    successor.set("hdg", "5.10235137500827")

    assert find_parampoly3_tangent_reversals(root) == []
    assert repair_parampoly3_tangent_reversals(root)["repaired"] == 0
