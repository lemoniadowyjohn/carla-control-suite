import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.osm_xodr_correspondence import match_osm_way_to_xodr


def _road(rid, x=0, name="Main"):
    return ET.fromstring(
        f'<road id="{rid}" name="{name}"><planView><geometry s="0" x="{x}" y="0" hdg="0" length="10"><line/></geometry></planView></road>'
    )


def test_spatial_match_returns_high_confidence_result():
    result = match_osm_way_to_xodr(
        {"id": "way-1", "name": "Main", "geometry": [(0, 0), (10, 0)]},
        [_road("7")],
    )
    assert result.xodr_road_id == "7"
    assert result.match_class == "HIGH"
    assert result.confidence > 0.65


def test_ambiguous_parallel_candidates_fail_closed():
    result = match_osm_way_to_xodr(
        {"id": "way-1", "geometry": [(0, 0), (10, 0)]},
        [_road("7", 0, ""), _road("8", 0.1, "")],
    )
    assert result.match_class == "AMBIGUOUS"
    assert result.xodr_road_id is None


def test_missing_geometry_is_unmatched():
    result = match_osm_way_to_xodr({"id": "way-1"}, [_road("7")])
    assert result.match_class == "UNMATCHED"
    assert result.xodr_road_id is None
