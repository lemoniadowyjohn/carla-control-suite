from pathlib import Path

from carla_map_quality_toolkit.io import parse_opendrive
from carla_map_quality_toolkit.topology import validate_topology

FIXTURES = Path(__file__).parent / "fixtures"


def test_valid_topology_fixture() -> None:
    data = parse_opendrive(FIXTURES / "minimal_valid.xodr")
    assert validate_topology(data) == []


def test_invalid_lane_links_are_reported() -> None:
    data = parse_opendrive(FIXTURES / "invalid_lane_link.xodr")
    issues = validate_topology(data)
    codes = {issue.code for issue in issues}
    assert codes == {"INVALID_FROM_LANE", "INVALID_TO_LANE"}


def test_missing_reciprocal_road_link_is_reported() -> None:
    data = parse_opendrive(FIXTURES / "road_chain_invalid.xodr")
    codes = {issue.code for issue in validate_topology(data)}
    assert "MISSING_RECIPROCAL_ROAD_LINK" in codes
