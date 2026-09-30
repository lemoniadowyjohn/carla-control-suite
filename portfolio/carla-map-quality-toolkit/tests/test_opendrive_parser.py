from pathlib import Path

from carla_map_quality_toolkit.io import parse_opendrive

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_minimal_opendrive() -> None:
    data = parse_opendrive(FIXTURES / "minimal_valid.xodr")
    assert set(data.roads) == {"1", "2"}
    assert "10" in data.junctions
    assert data.geo_reference and "+proj=utm" in data.geo_reference
    assert data.roads["1"].lane_ids == {-1, 0, 1}
