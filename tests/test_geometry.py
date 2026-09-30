import math
from pathlib import Path

import numpy as np

from carla_map_quality_toolkit.geometry import lane_centerline, sample_reference_line
from carla_map_quality_toolkit.io import parse_opendrive
from carla_map_quality_toolkit.io.opendrive import GeometrySegment, Road

FIXTURES = Path(__file__).parent / "fixtures"


def test_straight_reference_and_lane_center() -> None:
    road = parse_opendrive(FIXTURES / "minimal_valid.xodr").roads["1"]
    s, ref, heading = sample_reference_line(road, step=5.0)
    assert np.allclose(ref[:, 1], 0.0)
    assert np.allclose(heading, 0.0)
    assert s[-1] == 20.0
    right = lane_centerline(road, -1, step=5.0)
    assert np.allclose(right[:, 1], -1.75)


def test_arc_sampling_matches_quarter_circle() -> None:
    radius = 10.0
    road = Road(
        road_id="arc",
        length=math.pi * radius / 2,
        junction_id="-1",
        geometries=(
            GeometrySegment(0.0, 0.0, 0.0, 0.0, math.pi * radius / 2, "arc", 1 / radius),
        ),
        lane_offsets=(),
        lane_sections=(),
    )
    _, points, headings = sample_reference_line(road, step=2.0)
    assert np.allclose(points[-1], [10.0, 10.0], atol=1e-9)
    assert abs(headings[-1] - math.pi / 2) < 1e-9
