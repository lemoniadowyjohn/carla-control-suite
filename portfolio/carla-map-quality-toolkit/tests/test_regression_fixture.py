from pathlib import Path

from carla_map_quality_toolkit.geometry import lane_centerline
from carla_map_quality_toolkit.io import parse_opendrive

FIXTURES = Path(__file__).parent / "fixtures"


def test_synthetic_fixture_regression_signature() -> None:
    data = parse_opendrive(FIXTURES / "minimal_valid.xodr")
    points = lane_centerline(data.roads["1"], -1, step=2.0)
    signature = (
        len(points),
        round(float(points[:, 0].sum()), 6),
        round(float(points[:, 1].sum()), 6),
    )
    assert signature == (11, 110.0, -19.25)
