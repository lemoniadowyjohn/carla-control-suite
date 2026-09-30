from pathlib import Path

from carla_map_quality_toolkit.io import parse_osm_highways

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_highway_ways_only() -> None:
    data = parse_osm_highways(FIXTURES / "synthetic.osm")
    assert len(data.nodes) == 3
    assert len(data.highways) == 1
    assert data.highways[0].tags["highway"] == "residential"
