"""V103-O1 — OSM direction, oneway semantics and directional lane counts.

Registry issues covered: **T01** (oneway total lane count can create phantom
counterflow), **T02** (osm_direction discarded before lane geometry),
**T06** (coverage may report success without useful matches).

Every test imports and executes the *production* implementation.  The
mutation control at the end proves the tests actually bind the one-way
enforcement (replacing the production rule with a no-op makes a test fail).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.enrichment.lane_width_policy import driving_lane_counts
from ultimate_pipeline.enrichment.lane_generator import LaneGenerator
from ultimate_pipeline.enrichment.osm_direction import (
    DIRECTION_KEY,
    MATCH_CLASS_KEY,
    OSM_DIRECTION_CONTRACT_VERSION,
    ORIENTATION_REVERSE,
    OnewayState,
    RoadOSMDirectionalAssociation,
    build_directional_association,
    directional_coverage_report,
    parse_oneway,
    resolve_directional_lane_counts,
    write_direction_contract,
)
from ultimate_pipeline.pipeline_stages.stage_07_lanes import (
    _build_structural_osm_metadata,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _road(road_id: str = "1") -> ET.Element:
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id=road_id, junction="-1", length="100.0")
    ET.SubElement(road, "lanes")
    return road


def _counts(meta: dict) -> tuple[int, int]:
    """Run the production resolver over a plain tag mapping."""
    resolved = resolve_directional_lane_counts(meta)
    return resolved.backward, resolved.forward


# ---------------------------------------------------------------------------
# DIR-01 — one-way road must not gain a counterflow lane (registry T01)
# ---------------------------------------------------------------------------

def test_dir01_oneway_two_lane_road_has_no_phantom_counterflow():
    """``oneway=yes`` + ``lanes=2`` -> 2 forward lanes, 0 backward lanes.

    On the unmodified base this returned ``(1, 1)``: the total was split in
    half, inventing a counterflow driving lane that is not on the map.
    """
    resolved = resolve_directional_lane_counts({"oneway": "yes", "lanes": "2"})

    assert resolved.forward == 2
    assert resolved.backward == 0
    assert resolved.source == "osm:oneway+lanes"
    assert resolved.oneway == OnewayState.FORWARD.value
    assert resolved.state == "ok"
    assert resolved.is_authoritative is True


def test_dir01_oneway_two_lane_road_through_production_lane_counts():
    """The same fact through the production ``driving_lane_counts`` entry point."""
    backward, forward, source, confidence = driving_lane_counts(
        _road(),
        structural_osm_meta={"1": {"oneway": "yes", "lanes": "2"}},
    )

    assert (backward, forward) == (0, 2)
    assert source == "osm:oneway+lanes"
    assert confidence == 1.0


def test_dir01_oneway_true_and_numeric_forms_agree():
    for raw in ("yes", "true", "1"):
        resolved = resolve_directional_lane_counts({"oneway": raw, "lanes": "3"})
        assert (resolved.forward, resolved.backward) == (3, 0), raw


def test_dir01_oneway_reverse_keeps_lanes_in_the_reverse_direction():
    resolved = resolve_directional_lane_counts({"oneway": "-1", "lanes": "1"})

    assert resolved.forward == 0
    assert resolved.backward == 1
    assert resolved.oneway == OnewayState.BACKWARD.value


# ---------------------------------------------------------------------------
# DIR-02 — reversed XODR reference line (registry T02)
# ---------------------------------------------------------------------------

def test_dir02_reversed_xodr_swaps_the_carriageways():
    """A one-way OSM way mapped onto a reversed XODR road keeps its lanes
    on the carriageway the OSM source describes."""
    resolved = resolve_directional_lane_counts(
        {"oneway": "yes", "lanes": "2"},
        osm_direction=ORIENTATION_REVERSE,
    )

    assert resolved.forward == 0
    assert resolved.backward == 2
    assert resolved.orientation == ORIENTATION_REVERSE


def test_dir02_reversed_xodr_through_production_lane_counts():
    backward, forward, _source, _confidence = driving_lane_counts(
        _road(),
        structural_osm_meta={
            "1": {
                "oneway": "yes",
                "lanes": "2",
                DIRECTION_KEY: ORIENTATION_REVERSE,
            }
        },
    )

    assert (backward, forward) == (2, 0)


def test_dir02_aligned_xodr_is_not_swapped():
    resolved = resolve_directional_lane_counts(
        {"oneway": "yes", "lanes": "2"}, osm_direction="forward"
    )

    assert (resolved.forward, resolved.backward) == (2, 0)


# ---------------------------------------------------------------------------
# DIR-03/04 — oneway=-1, roundabout defaults, bicycle contraflow
# ---------------------------------------------------------------------------

def test_dir03_oneway_minus_one_is_the_opposite_osm_node_order():
    resolved = resolve_directional_lane_counts({"oneway": "-1", "lanes": "1"})

    # Driving is against the OSM way's node order.
    assert (resolved.forward, resolved.backward) == (0, 1)


def test_dir03_oneway_reverse_on_reversed_xodr_returns_to_forward():
    resolved = resolve_directional_lane_counts(
        {"oneway": "-1", "lanes": "1"}, osm_direction=ORIENTATION_REVERSE
    )

    assert (resolved.forward, resolved.backward) == (1, 0)


def test_dir04_roundabout_without_oneway_tag_is_implicitly_oneway():
    assert parse_oneway({"junction": "roundabout"}) is OnewayState.FORWARD

    resolved = resolve_directional_lane_counts(
        {"junction": "roundabout", "lanes": "2"}
    )
    assert (resolved.forward, resolved.backward) == (2, 0)


def test_dir04_bicycle_contraflow_does_not_create_a_driving_counterflow():
    """``oneway:bicycle=no`` describes bicycle contraflow only.

    The driving lane count must stay one-way; reading it as ``oneway=no``
    would invent a motor-vehicle counterflow lane.
    """
    resolved = resolve_directional_lane_counts(
        {"oneway": "yes", "oneway:bicycle": "no", "lanes": "2"}
    )

    assert (resolved.forward, resolved.backward) == (2, 0)
    assert resolved.oneway == OnewayState.FORWARD.value


# ---------------------------------------------------------------------------
# DIR-05/06 — both_ways, conflicting tags, undecidable oneway
# ---------------------------------------------------------------------------

def test_dir05_lanes_both_ways_is_not_added_to_either_direction():
    resolved = resolve_directional_lane_counts(
        {"oneway": "yes", "lanes": "2", "lanes:both_ways": "1"}
    )

    assert resolved.forward == 2
    assert resolved.backward == 0
    assert resolved.total == 2
    assert any("both_ways" in note for note in resolved.notes)


def test_dir05_both_ways_lane_does_not_inflate_a_bidirectional_split():
    resolved = resolve_directional_lane_counts(
        {"lanes": "2", "lanes:both_ways": "1"}
    )

    # The total is 2; the shared lane is not part of `lanes`.
    assert resolved.total == 2


def test_dir06_conflicting_total_and_directional_counts_are_flagged():
    resolved = resolve_directional_lane_counts(
        {"lanes": "4", "lanes:forward": "2", "lanes:backward": "1"}
    )

    # The directional tags win, but the disagreement is reported.
    assert (resolved.forward, resolved.backward) == (2, 1)
    assert resolved.state == "conflicting"
    assert any("lanes_total_mismatch" in note for note in resolved.notes)


def test_dir06_conditional_oneway_is_not_decided_statically():
    resolved = resolve_directional_lane_counts(
        {"oneway:conditional": "yes @ (12:00-14:00)", "lanes": "2"}
    )

    assert resolved.state == "unsupported"
    assert resolved.is_authoritative is False
    assert any("oneway_conditional" in note for note in resolved.notes)


def test_dir06_reversible_is_not_decided_statically():
    resolved = resolve_directional_lane_counts(
        {"oneway": "reversible", "lanes": "2"}
    )

    assert resolved.state == "unsupported"
    assert resolved.is_authoritative is False


def test_dir06_directional_tags_are_authoritative_even_with_conditional_oneway():
    """Directional lane tags do not depend on a time context."""
    resolved = resolve_directional_lane_counts(
        {
            "oneway:conditional": "yes @ (12:00-14:00)",
            "lanes:forward": "2",
            "lanes:backward": "1",
        }
    )

    assert (resolved.forward, resolved.backward) == (2, 1)
    assert resolved.state == "ok"


def test_bidirectional_road_still_splits_the_total():
    resolved = resolve_directional_lane_counts({"oneway": "no", "lanes": "4"})

    assert (resolved.forward, resolved.backward) == (2, 2)
    assert resolved.source == "osm:lanes"


def test_no_lane_tags_keeps_the_documented_fallback():
    resolved = resolve_directional_lane_counts({})

    assert (resolved.forward, resolved.backward) == (1, 1)
    assert resolved.source == "fallback"
    assert resolved.state == "incomplete"


# ---------------------------------------------------------------------------
# T02 — orientation must survive the correspondence -> geometry hand-off
# ---------------------------------------------------------------------------

def test_t02_stage07_preserves_osm_orientation(tmp_path, monkeypatch):
    """``_build_structural_osm_metadata`` must not discard ``osm_direction``."""
    osm_path = tmp_path / "source.osm"
    osm_path.write_text("<osm/>", encoding="utf-8")
    root = ET.fromstring(
        '<OpenDRIVE><road id="42" length="10"><planView><geometry '
        's="0" x="0" y="0" hdg="0" length="10"><line/></geometry>'
        '</planView></road></OpenDRIVE>'
    )

    import ultimate_pipeline.enrichment.osm_meta_index as meta_index

    monkeypatch.setattr(
        meta_index,
        "extract_structural_osm_lane_metadata_ways",
        lambda _: [
            {
                "id": "way-1",
                "geometry": [(0.0, 0.0), (10.0, 0.0)],
                "metadata": {"lanes:forward": "2", "lanes:backward": "1"},
            }
        ],
    )
    monkeypatch.setattr(
        meta_index, "project_positioned_osm_metadata_ways", lambda ways, _: ways
    )

    metadata, report = _build_structural_osm_metadata(root, str(osm_path))

    assert metadata["42"][DIRECTION_KEY] == "forward"
    assert metadata["42"][MATCH_CLASS_KEY] in {"EXACT", "HIGH"}
    # The raw OSM tags are preserved verbatim.
    assert metadata["42"]["lanes:forward"] == "2"
    assert metadata["42"]["lanes:backward"] == "1"
    assert report["directional_coverage"]["counts"]["matched"] == 1


def test_t02_reversed_road_puts_turn_lanes_on_the_xodr_backward_carriageway():
    """A reversed XODR road must apply OSM's forward turn pattern to the
    carriageway that actually runs with the OSM way."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="42", junction="-1", length="100.0")
    ET.SubElement(road, "lanes")

    patterns = LaneGenerator._turn_patterns(
        road,
        {
            "42": {
                "turn:lanes:forward": "left|through",
                DIRECTION_KEY: ORIENTATION_REVERSE,
            }
        },
    )

    assert len(patterns) == 1
    direction, cells, source, _confidence = patterns[0]
    # OSM "forward" == XODR "backward" on a reversed road.
    assert direction == "backward"
    assert cells == ["left", "through"]
    assert source == "osm:turn:lanes:forward@xodr-reverse"


def test_t02_aligned_road_keeps_turn_lanes_on_the_forward_carriageway():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="42", junction="-1", length="100.0")
    ET.SubElement(road, "lanes")

    patterns = LaneGenerator._turn_patterns(
        road,
        {"42": {"turn:lanes:forward": "left|through", DIRECTION_KEY: "forward"}},
    )

    direction, cells, source, _confidence = patterns[0]
    assert direction == "forward"
    assert cells == ["left", "through"]
    assert source == "osm:turn:lanes:forward"


# ---------------------------------------------------------------------------
# T06 — coverage reporting
# ---------------------------------------------------------------------------

def test_t06_missing_osm_source_is_blocked_input():
    report = directional_coverage_report({}, source_available=False, reason="osm_missing")

    assert report["status"] == "BLOCKED_INPUT"
    assert report["counts"]["matched"] == 0


def test_t06_zero_matched_roads_is_never_a_pass():
    report = directional_coverage_report({}, source_available=True)

    assert report["status"] == "BLOCKED_INPUT"
    assert report["release_required"] is True


def test_t06_coverage_counts_matched_reversed_and_not_assessable():
    report = directional_coverage_report(
        {
            "1": {DIRECTION_KEY: "forward", MATCH_CLASS_KEY: "EXACT"},
            "2": {DIRECTION_KEY: ORIENTATION_REVERSE, MATCH_CLASS_KEY: "EXACT"},
            "3": {DIRECTION_KEY: "unknown", MATCH_CLASS_KEY: "HIGH"},
        },
        source_available=True,
    )

    assert report["status"] == "PASS"
    assert report["counts"]["matched"] == 3
    assert report["counts"]["forward"] == 1
    assert report["counts"]["reversed"] == 1
    assert report["counts"]["not_assessable"] == 1


def test_t06_all_not_assessable_is_incomplete_for_release():
    report = directional_coverage_report(
        {"1": {DIRECTION_KEY: "unknown", MATCH_CLASS_KEY: "HIGH"}},
        source_available=True,
        release_required=True,
    )

    assert report["status"] == "INCOMPLETE"


# ---------------------------------------------------------------------------
# Versioned association contract
# ---------------------------------------------------------------------------

def test_association_contract_is_versioned_and_explicit_about_unknowns():
    association = build_directional_association(
        xodr_road_id="42",
        osm_way_id="way-1",
        osm_direction=None,
        match_class="HIGH",
        confidence=0.8,
        source_sha256="deadbeef",
        span=(0.0, 10.0),
        contact_points=("start", "end"),
        tags={"lanes": "2"},
    )

    assert association.schema == OSM_DIRECTION_CONTRACT_VERSION
    assert association.osm_direction == "unknown"
    assert association.is_oriented is False
    assert association.is_trustworthy is False
    assert association.state == "incomplete"
    payload = association.to_dict()
    assert payload["span"] == [0.0, 10.0]
    assert payload["contact_points"] == ["start", "end"]


def test_association_contract_is_trustworthy_when_fully_resolved():
    association = build_directional_association(
        xodr_road_id="42",
        osm_way_id="way-1",
        osm_direction="forward",
        match_class="EXACT",
        confidence=1.0,
    )

    assert association.is_oriented is True
    assert association.is_trustworthy is True
    assert isinstance(association, RoadOSMDirectionalAssociation)


def test_direction_contract_artifact_is_written(tmp_path):
    path = write_direction_contract(
        tmp_path / "OSM_XODR_DIRECTION_CONTRACT.json",
        coverage=directional_coverage_report({}, source_available=False),
    )
    payload = json.loads(open(path, encoding="utf-8").read())

    assert payload["contract_version"] == OSM_DIRECTION_CONTRACT_VERSION
    assert "oneway" in payload["resolution_order"][1]
    assert payload["coverage"]["status"] == "BLOCKED_INPUT"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_resolution_is_deterministic_under_tag_order_permutation():
    tags = {"oneway": "yes", "lanes": "2", "highway": "primary", "name": "x"}
    first = resolve_directional_lane_counts(tags)
    second = resolve_directional_lane_counts(dict(reversed(list(tags.items()))))

    assert first == second


# ---------------------------------------------------------------------------
# Independent-review follow-ups (V103-O1 review round 1)
# ---------------------------------------------------------------------------

def test_cycleway_sides_swap_on_a_reversed_xodr_reference():
    """OSM ``cycleway:left``/``right`` are OSM-way-relative."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="42", junction="-1", length="100.0")
    ET.SubElement(road, "lanes")

    LaneGenerator.ensure_lanes(
        root,
        verbose=False,
        structural_osm_meta={
            "42": {
                "cycleway:right": "lane",
                DIRECTION_KEY: ORIENTATION_REVERSE,
            }
        },
    )

    lane_sections = road.findall("./lanes/laneSection")
    assert lane_sections
    # The OSM right side of a reversed way is the XODR left carriageway.
    left_bike = lane_sections[0].findall("./left/lane[@type='biking']")
    right_bike = lane_sections[0].findall("./right/lane[@type='biking']")
    assert len(left_bike) == 1
    assert right_bike == []
    provenance = lane_sections[0].find(
        "./left/lane/userData/vector[@key='cycle_lane_source']"
    )
    assert provenance is not None
    assert provenance.get("value") == "osm:cycleway:right@xodr-reverse"


def test_cycleway_sides_do_not_swap_on_an_aligned_xodr_reference():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="42", junction="-1", length="100.0")
    ET.SubElement(road, "lanes")

    LaneGenerator.ensure_lanes(
        root,
        verbose=False,
        structural_osm_meta={
            "42": {"cycleway:right": "lane", DIRECTION_KEY: "forward"}
        },
    )

    lane_sections = road.findall("./lanes/laneSection")
    assert len(lane_sections[0].findall("./right/lane[@type='biking']")) == 1
    assert lane_sections[0].findall("./left/lane[@type='biking']") == []
    provenance = lane_sections[0].find(
        "./right/lane/userData/vector[@key='cycle_lane_source']"
    )
    assert provenance is not None
    assert provenance.get("value") == "osm:cycleway:right"


def test_coverage_is_incomplete_when_every_matched_road_conflicts():
    report = directional_coverage_report(
        {
            "1": {
                DIRECTION_KEY: "forward",
                MATCH_CLASS_KEY: "EXACT",
                "lanes": "4",
                "lanes:forward": "2",
                "lanes:backward": "1",
            }
        },
        source_available=True,
    )

    assert report["status"] == "INCOMPLETE"
    assert report["counts"]["conflicting"] == 1
    assert report["counts"]["authoritative"] == 0


def test_coverage_is_incomplete_when_every_matched_road_is_ambiguous():
    report = directional_coverage_report(
        {"1": {DIRECTION_KEY: "forward", MATCH_CLASS_KEY: "AMBIGUOUS"}},
        source_available=True,
    )

    assert report["status"] == "INCOMPLETE"
    assert report["counts"]["ambiguous"] == 1
    assert report["counts"]["authoritative"] == 0


def test_reversible_oneway_records_the_note():
    resolved = resolve_directional_lane_counts({"oneway": "reversible", "lanes": "2"})

    assert resolved.state == "unsupported"
    assert "reversible_oneway" in resolved.notes


def test_reserved_direction_keys_are_not_shadowed_by_xodr_provenance():
    """An XODR attribute/vector must never override the reserved keys."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(
        root,
        "road",
        id="1",
        junction="-1",
        length="100.0",
        **{"_osm_direction": "forward"},
    )
    user_data = ET.SubElement(road, "userData")
    ET.SubElement(user_data, "vector", key="_osm_direction", value="reverse")
    ET.SubElement(road, "lanes")

    backward, forward, _source, _confidence = driving_lane_counts(
        road,
        structural_osm_meta={
            "1": {"oneway": "yes", "lanes": "2", DIRECTION_KEY: ORIENTATION_REVERSE}
        },
    )

    # The reserved key survives: the reversed mapping still applies.
    assert (backward, forward) == (2, 0)


# ---------------------------------------------------------------------------
# Mutation control — proves the tests really bind the one-way rule
# ---------------------------------------------------------------------------

def test_mutation_control_removing_oneway_enforcement_makes_dir01_fail(monkeypatch):
    """Neutralize the production one-way rule; DIR-01 must then fail.

    This proves the DIR-01 test is not vacuously green: with the one-way
    enforcement removed the resolver invents a counterflow lane and the
    DIR-01 assertion no longer holds.
    """
    import ultimate_pipeline.enrichment.osm_direction as osm_direction

    original_parse = osm_direction.parse_oneway
    monkeypatch.setattr(
        osm_direction, "parse_oneway", lambda tags: OnewayState.BIDIRECTIONAL
    )

    mutated = osm_direction.resolve_directional_lane_counts(
        {"oneway": "yes", "lanes": "2"}
    )
    # The DIR-01 assertion does NOT hold under the mutant.
    assert not (mutated.forward == 2 and mutated.backward == 0)
    assert (mutated.forward, mutated.backward) == (1, 1)

    # ... and it does hold for the unmutated production rule.
    monkeypatch.setattr(osm_direction, "parse_oneway", original_parse)
    real = osm_direction.resolve_directional_lane_counts(
        {"oneway": "yes", "lanes": "2"}
    )
    assert (real.forward, real.backward) == (2, 0)
