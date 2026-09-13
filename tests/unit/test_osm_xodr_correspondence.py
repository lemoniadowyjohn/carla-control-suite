import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.osm_xodr_correspondence import (
    _osm_direction,
    _road_samples,
    build_correspondence,
    build_metadata_associations,
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


def test_osm_direction_forward_when_way_and_road_run_the_same_way():
    # both run +x: same net direction
    assert _osm_direction([(0, 0), (10, 0)], [(0, 0), (10, 0)]) == "forward"


def test_osm_direction_reverse_when_way_runs_opposite_the_road():
    # way runs -x while road runs +x: opposite net direction
    assert _osm_direction([(10, 0), (0, 0)], [(0, 0), (10, 0)]) == "reverse"


def test_osm_direction_robust_to_curvature_not_just_local_heading():
    # way's local heading at its start bends away from +x, but its NET
    # start-to-end displacement still runs +x -- must use net displacement,
    # not a single local heading sample, to classify this as forward.
    curved_way = [(0, 0), (2, 3), (5, -2), (10, 0.1)]
    assert _osm_direction(curved_way, [(0, 0), (10, 0)]) == "forward"


def test_osm_direction_none_for_degenerate_inputs():
    assert _osm_direction([(0, 0)], [(0, 0), (10, 0)]) is None
    assert _osm_direction([(0, 0), (10, 0)], [(0, 0)]) is None
    assert _osm_direction([(0, 0), (0, 0)], [(0, 0), (10, 0)]) is None


def test_build_metadata_associations_includes_osm_direction():
    root = ET.fromstring(
        '<OpenDRIVE><road id="7" name="Main">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        "</road></OpenDRIVE>"
    )
    associations, report = build_metadata_associations(
        [{
            "id": "w1",
            "name": "Main",
            "geometry": [(0, 0), (10, 0)],
            "metadata": {"maxspeed": "50"},
        }],
        root,
    )
    assert report["eligible_road_count"] == 1
    assert associations["7"]["osm_direction"] == "forward"
