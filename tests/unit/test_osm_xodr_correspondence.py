import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.osm_xodr_correspondence import (
    _road_samples,
    build_correspondence,
    match_osm_way_to_xodr,
)


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


def test_sampling_uses_kernel_for_parampoly3():
    road = ET.fromstring(
        '<road id="p"><planView><geometry s="0" x="0" y="0" hdg="0" length="10">'
        '<paramPoly3 aU="0" bU="1" cU="0" dU="0" aV="0" bV="0" cV="0.02" dV="0" pRange="arcLength"/>'
        '</geometry></planView></road>'
    )
    samples = _road_samples(road, spacing=1.0)
    assert len(samples) > 2
    assert any(abs(y) > 0.01 for _, y in samples)


def test_build_correspondence_uses_cached_grid_candidates():
    root = ET.fromstring('<OpenDRIVE><road id="7" name="Main"><planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView></road><road id="8"><planView><geometry s="0" x="1000" y="0" hdg="0" length="10"><line/></geometry></planView></road></OpenDRIVE>')
    results = build_correspondence([
        {"id": "w1", "name": "Main", "geometry": [(0, 0), (10, 0)]},
        {"id": "w2", "name": "Main", "geometry": [(0, 0), (10, 0)]},
    ], root)
    assert [result.xodr_road_id for result in results] == ["7", "7"]
