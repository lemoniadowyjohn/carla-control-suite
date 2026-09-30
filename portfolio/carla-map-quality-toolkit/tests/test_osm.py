from pathlib import Path

import pytest

from carla_map_quality_toolkit.io import parse_osm_highways

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_osm_highways() -> None:
    osm = parse_osm_highways(FIXTURES / "synthetic.osm")
    assert len(osm.nodes) == 3
    assert len(osm.highways) == 1
    assert osm.highways[0].way_id == "100"
    assert osm.highways[0].tags["highway"] == "residential"
    assert osm.highways[0].node_ids == ("1", "2", "3")


def test_parse_osm_highways_rejects_missing_node_reference(tmp_path: Path) -> None:
    path = tmp_path / "broken.osm"
    path.write_text(
        '<osm><node id="1" lat="48" lon="11" />'
        '<way id="9"><nd ref="404"/><tag k="highway" v="service"/></way></osm>',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="references missing nodes"):
        parse_osm_highways(path)
