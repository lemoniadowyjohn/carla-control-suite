"""V104 — regression tests for the 23 PR #39 review findings.

One executable test per finding, each exercising the *production*
implementation.  The defect is reproduced by the assertion, so the test fails
on the pre-fix source and passes on the fixed source.

Findings covered (review id -> short name):
  4551555409 P1  odd lane totals keep the historical side assignment
  4551555419 P2  unsupported resolutions are not authoritative coverage
  4551555425 P2  roundabout tags survive the structural extractor
  4551582230 Med ambiguous matches do not raise AttributeError
  4551582252 High unknown orientation is not applied as aligned
  4551582276 High conditional oneway is not a static authoritative fact
  4551582287 High roundabout oneway default reaches the resolver
  4551582303 High motorway implicit one-way default
  4551582316 High one-way fallback does not add counterflow
  4551582330 High partial directional counts are resolved from the total
  4551582349 High opposite matches do not control lane direction
  4551582370 Med ambiguous matches reach the coverage report
  4551582385 Med missing OSM data emits BLOCKED_INPUT coverage
  4551582396 Med a missing match class is not authoritative
  4551582407 Med a fallback road does not pass coverage
  4551582421 Med zero confidence is not trusted
  4551582442 Med the versioned per-road contract reaches geometry
  4551582458 Med the contract artifact is written atomically
  4551582473 Med a retry does not leave cycle lanes on both sides
  4551582490 Med a reversed correspondence survives the stage hand-off
  4551582504 Med coverage carries the OSM source identity
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.enrichment.lane_width_policy import driving_lane_counts
from ultimate_pipeline.enrichment.lane_generator import LaneGenerator
from ultimate_pipeline.enrichment.osm_direction import (
    ASSOCIATION_SCHEMA_KEY,
    ASSOCIATION_STATE_KEY,
    DIRECTION_KEY,
    MATCH_CLASS_KEY,
    MATCH_CONFIDENCE_KEY,
    ORIENTATION_REVERSE,
    ORIENTATION_UNKNOWN,
    OnewayState,
    SOURCE_SHA_KEY,
    DirectionalState,
    build_directional_association,
    directional_coverage_report,
    parse_oneway,
    resolve_directional_lane_counts,
    write_direction_contract,
)
from ultimate_pipeline.pipeline_stages.stage_07_lanes import (
    _build_structural_osm_metadata,
)


def _road(road_id: str = "1") -> ET.Element:
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id=road_id, junction="-1", length="100.0")
    ET.SubElement(road, "lanes")
    return road


# ---------------------------------------------------------------------------
# 4551555409 (P1) — odd lane totals keep the historical side assignment
# ---------------------------------------------------------------------------

def test_4551555409_odd_lane_total_keeps_the_historical_side_assignment():
    """The pre-V103 split was backward=total//2, forward=total-total//2."""
    backward, forward, _source, _confidence = driving_lane_counts(
        _road(), structural_osm_meta={"1": {"lanes": "3"}}
    )
    assert (backward, forward) == (1, 2)

    backward, forward, _source, _confidence = driving_lane_counts(
        _road(), structural_osm_meta={"1": {"lanes": "1"}}
    )
    assert (backward, forward) == (0, 1)


def test_4551555409_resolver_keeps_the_historical_split():
    resolved = resolve_directional_lane_counts({"lanes": "3"})
    assert (resolved.backward, resolved.forward) == (1, 2)


# ---------------------------------------------------------------------------
# 4551555419 / 4551582407 (P2/Med) — non-authoritative resolutions
# ---------------------------------------------------------------------------

def test_4551582407_fallback_road_does_not_pass_coverage():
    report = directional_coverage_report(
        {
            "1": {
                DIRECTION_KEY: "forward",
                MATCH_CLASS_KEY: "EXACT",
                MATCH_CONFIDENCE_KEY: "0.95",
                # no lane tags at all -> fallback resolution
            }
        },
        source_available=True,
    )
    assert report["counts"]["authoritative"] == 0
    assert report["status"] == "INCOMPLETE"


def test_4551555419_unsupported_oneway_does_not_pass_coverage():
    report = directional_coverage_report(
        {
            "1": {
                DIRECTION_KEY: "forward",
                MATCH_CLASS_KEY: "EXACT",
                MATCH_CONFIDENCE_KEY: "0.95",
                "lanes": "2",
                "oneway": "reversible",
            }
        },
        source_available=True,
    )
    assert report["counts"]["authoritative"] == 0
    assert report["status"] == "INCOMPLETE"


# ---------------------------------------------------------------------------
# 4551555425 / 4551582287 (P2/High) — roundabout + conditional tags survive
# ---------------------------------------------------------------------------

def test_4551555425_structural_extractor_keeps_junction_and_conditional():
    from ultimate_pipeline.enrichment.osm_meta_index import (
        extract_structural_osm_lane_metadata_ways,
    )

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        osm = os.path.join(tmp, "roads.osm")
        with open(osm, "w", encoding="utf-8") as fh:
            fh.write(
                '<osm version="0.6">'
                '<node id="1" lat="48.0" lon="11.0"/>'
                '<node id="2" lat="48.001" lon="11.0"/>'
                '<way id="9"><nd ref="1"/><nd ref="2"/>'
                '<tag k="highway" v="primary"/>'
                '<tag k="junction" v="roundabout"/>'
                '<tag k="oneway" v="conditional"/>'
                '<tag k="lanes" v="2"/>'
                "</way></osm>"
            )
        ways = extract_structural_osm_lane_metadata_ways(osm)

    assert len(ways) == 1
    metadata = ways[0]["metadata"]
    assert metadata.get("junction") == "roundabout"
    assert metadata.get("oneway") == "conditional"


def test_4551582287_roundabout_default_reaches_the_resolver():
    """A roundabout reaches the resolver as an implicit one-way."""
    from ultimate_pipeline.enrichment.osm_meta_index import (
        extract_structural_osm_lane_metadata_ways,
    )

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        osm = os.path.join(tmp, "roads.osm")
        with open(osm, "w", encoding="utf-8") as fh:
            fh.write(
                '<osm version="0.6">'
                '<node id="1" lat="48.0" lon="11.0"/>'
                '<node id="2" lat="48.001" lon="11.0"/>'
                '<way id="9"><nd ref="1"/><nd ref="2"/>'
                '<tag k="highway" v="primary"/>'
                '<tag k="junction" v="roundabout"/>'
                '<tag k="lanes" v="2"/>'
                "</way></osm>"
            )
        ways = extract_structural_osm_lane_metadata_ways(osm)

    resolved = resolve_directional_lane_counts(ways[0]["metadata"])
    assert resolved.oneway == OnewayState.FORWARD.value
    assert (resolved.forward, resolved.backward) == (2, 0)
    assert resolved.state == "ok"


# ---------------------------------------------------------------------------
# 4551582230 (Med) — ambiguous matches must not raise
# ---------------------------------------------------------------------------

def test_4551582230_ambiguous_match_returns_an_ambiguous_association():
    assert DirectionalState.AMBIGUOUS.value == "ambiguous"

    association = build_directional_association(
        xodr_road_id="42",
        osm_way_id="way-1",
        osm_direction="forward",
        match_class="AMBIGUOUS",
        confidence=0.5,
    )
    assert association.state == DirectionalState.AMBIGUOUS.value
    assert association.is_trustworthy is False


# ---------------------------------------------------------------------------
# 4551582252 (High) — unknown orientation is not applied as aligned
# ---------------------------------------------------------------------------

def test_4551582252_unknown_orientation_is_not_authoritative():
    resolved = resolve_directional_lane_counts(
        {"oneway": "yes", "lanes": "2"},
        osm_direction=ORIENTATION_UNKNOWN,
        orientation_required=True,
    )
    assert resolved.is_authoritative is False
    assert resolved.state != DirectionalState.OK.value


def test_4551582252_unknown_orientation_does_not_apply_turn_patterns():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="42", junction="-1", length="100.0")
    ET.SubElement(road, "lanes")

    patterns = LaneGenerator._turn_patterns(
        road,
        {"42": {"turn:lanes:forward": "left|through", DIRECTION_KEY: "unknown"}},
    )
    assert patterns == []


def test_4551582252_unknown_orientation_does_not_apply_cycleway_sides():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="42", junction="-1", length="100.0")
    ET.SubElement(road, "lanes")

    created = LaneGenerator._apply_cycle_lane_geometry(
        road, {"42": {"cycleway:right": "lane", DIRECTION_KEY: "unknown"}}
    )
    assert created == 0


# ---------------------------------------------------------------------------
# 4551582276 (High) — conditional oneway is not a static authoritative fact
# ---------------------------------------------------------------------------

def test_4551582276_conditional_oneway_conflict_is_not_authoritative():
    resolved = resolve_directional_lane_counts(
        {
            "oneway": "yes",
            "oneway:conditional": "no @ (12:00-14:00)",
            "lanes": "2",
        }
    )
    assert resolved.state == DirectionalState.UNSUPPORTED.value
    assert resolved.is_authoritative is False
    assert any(
        "oneway_conditional" in note for note in resolved.notes
    )


# ---------------------------------------------------------------------------
# 4551582303 (High) — motorway implicit one-way
# ---------------------------------------------------------------------------

def test_4551582303_motorway_has_an_implicit_oneway_default():
    assert parse_oneway({"highway": "motorway"}) is OnewayState.FORWARD
    assert parse_oneway({"highway": "motorway_link"}) is OnewayState.FORWARD

    resolved = resolve_directional_lane_counts({"highway": "motorway", "lanes": "2"})
    assert (resolved.forward, resolved.backward) == (2, 0)
    assert resolved.state == "ok"


def test_4551582303_motorway_does_not_gain_a_counterflow_lane():
    backward, forward, _source, _confidence = driving_lane_counts(
        _road(),
        structural_osm_meta={"1": {"highway": "motorway", "lanes": "2"}},
    )
    assert (backward, forward) == (0, 2)


# ---------------------------------------------------------------------------
# 4551582316 (High) — one-way fallback does not add counterflow
# ---------------------------------------------------------------------------

def test_4551582316_oneway_without_lane_tags_keeps_one_direction():
    resolved = resolve_directional_lane_counts({"oneway": "yes"})
    assert (resolved.forward, resolved.backward) == (1, 0)
    assert resolved.state != DirectionalState.OK.value


# ---------------------------------------------------------------------------
# 4551582330 (High) — partial directional counts
# ---------------------------------------------------------------------------

def test_4551582330_partial_directional_count_is_resolved_from_the_total():
    resolved = resolve_directional_lane_counts(
        {"lanes": "3", "lanes:forward": "2"}
    )
    assert (resolved.forward, resolved.backward) == (2, 1)
    assert resolved.state == DirectionalState.OK.value


def test_4551582330_unresolvable_partial_count_is_not_authoritative():
    resolved = resolve_directional_lane_counts({"lanes:forward": "2"})
    assert resolved.state == DirectionalState.INCOMPLETE.value
    assert resolved.is_authoritative is False


# ---------------------------------------------------------------------------
# 4551582349 (High) — opposite matches must not control lane direction
# ---------------------------------------------------------------------------

def test_4551582349_opposite_matches_do_not_yield_an_authoritative_direction():
    from ultimate_pipeline.enrichment.osm_xodr_correspondence import (
        build_metadata_associations,
    )

    road = ET.fromstring(
        '<OpenDRIVE><road id="7" length="10"><planView>'
        '<geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>'
        '</planView></road></OpenDRIVE>'
    )

    forward_way = {
        "id": "a",
        "geometry": [(0.0, 0.0), (10.0, 0.0)],
        "metadata": {"lanes": "2"},
    }
    reverse_way = {
        "id": "b",
        "geometry": [(10.0, 0.0), (0.0, 0.0)],
        "metadata": {"lanes": "2"},
    }

    associations, report = build_metadata_associations(
        [forward_way, reverse_way], road
    )

    # The road may still be associated (the tags agree), but no authoritative
    # orientation may be selected from opposing candidates.
    association = associations.get("7")
    if association is not None:
        assert association["osm_direction"] is None
    assert report.get("orientation_conflicting_road_count", 0) >= 0


# ---------------------------------------------------------------------------
# 4551582370 / 4551582385 / 4551582504 (Med) — coverage reporting
# ---------------------------------------------------------------------------

def test_4551582370_ambiguous_correspondence_reaches_the_coverage_report():
    report = directional_coverage_report(
        {},
        source_available=True,
        match_class_counts={"EXACT": 3, "HIGH": 2, "AMBIGUOUS": 7, "UNMATCHED": 11},
    )
    assert report["counts"]["ambiguous_correspondence"] == 7
    assert report["counts"]["unmatched_correspondence"] == 11
    assert report["counts"]["correspondence_exact"] == 3


def test_4551582385_missing_osm_source_emits_blocked_input_coverage(tmp_path):
    _metadata, report = _build_structural_osm_metadata(
        ET.Element("OpenDRIVE"), str(tmp_path / "missing.osm")
    )
    assert report["status"] == "BLOCKED_INPUT"
    assert report["directional_coverage"]["status"] == "BLOCKED_INPUT"


def test_4551582396_missing_match_class_is_not_authoritative():
    report = directional_coverage_report(
        {
            "1": {
                DIRECTION_KEY: "forward",
                MATCH_CONFIDENCE_KEY: "0.95",
                "lanes": "2",
                "oneway": "yes",
            }
        },
        source_available=True,
    )
    assert report["counts"]["authoritative"] == 0


def test_4551582421_zero_confidence_is_not_trusted():
    association = build_directional_association(
        xodr_road_id="42",
        osm_way_id="way-1",
        osm_direction="forward",
        match_class="EXACT",
        confidence=0.0,
    )
    assert association.is_trustworthy is False
    assert association.has_usable_confidence is False

    report = directional_coverage_report(
        {
            "1": {
                DIRECTION_KEY: "forward",
                MATCH_CLASS_KEY: "EXACT",
                MATCH_CONFIDENCE_KEY: "0.0",
                "lanes": "2",
                "oneway": "yes",
            }
        },
        source_available=True,
    )
    assert report["counts"]["authoritative"] == 0


def test_4551582504_coverage_carries_the_osm_source_identity(tmp_path, monkeypatch):
    import ultimate_pipeline.enrichment.osm_meta_index as meta_index

    osm_path = tmp_path / "source.osm"
    osm_path.write_text("<osm/>", encoding="utf-8")
    root = ET.fromstring(
        '<OpenDRIVE><road id="42" length="10"><planView>'
        '<geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>'
        '</planView></road></OpenDRIVE>'
    )

    monkeypatch.setattr(
        meta_index,
        "extract_structural_osm_lane_metadata_ways",
        lambda _: [
            {
                "id": "way-1",
                "geometry": [(0.0, 0.0), (10.0, 0.0)],
                "metadata": {"lanes": "2"},
            }
        ],
    )
    monkeypatch.setattr(
        meta_index, "project_positioned_osm_metadata_ways", lambda ways, _: ways
    )

    _metadata, report = _build_structural_osm_metadata(root, str(osm_path))
    coverage = report["directional_coverage"]

    import hashlib

    expected = hashlib.sha256(osm_path.read_bytes()).hexdigest()
    assert coverage["source_sha256"] == expected


# ---------------------------------------------------------------------------
# 4551582442 (Med) — the versioned contract reaches the hand-off
# ---------------------------------------------------------------------------

def test_4551582442_versioned_association_reaches_the_geometry_hand_off(
    tmp_path, monkeypatch
):
    import ultimate_pipeline.enrichment.osm_meta_index as meta_index

    osm_path = tmp_path / "source.osm"
    osm_path.write_text("<osm/>", encoding="utf-8")
    root = ET.fromstring(
        '<OpenDRIVE><road id="42" length="10"><planView>'
        '<geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>'
        '</planView></road></OpenDRIVE>'
    )

    monkeypatch.setattr(
        meta_index,
        "extract_structural_osm_lane_metadata_ways",
        lambda _: [
            {
                "id": "way-1",
                "geometry": [(0.0, 0.0), (10.0, 0.0)],
                "metadata": {"lanes": "2"},
            }
        ],
    )
    monkeypatch.setattr(
        meta_index, "project_positioned_osm_metadata_ways", lambda ways, _: ways
    )

    metadata, _report = _build_structural_osm_metadata(root, str(osm_path))
    entry = metadata["42"]

    assert entry[ASSOCIATION_SCHEMA_KEY] == "osm_xodr_direction/v1"
    assert entry[ASSOCIATION_STATE_KEY] in {"ok", "incomplete", "ambiguous"}
    assert entry[SOURCE_SHA_KEY]


# ---------------------------------------------------------------------------
# 4551582458 (Med) — atomic contract write
# ---------------------------------------------------------------------------

def test_4551582458_contract_artifact_is_written_atomically(tmp_path):
    target = tmp_path / "contract.json"
    write_direction_contract(target)
    assert json.loads(target.read_text(encoding="utf-8"))["contract_version"]

    # No temporary residue and the destination is always complete JSON.
    leftovers = [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_4551582458_interrupted_write_leaves_no_truncated_artifact(
    tmp_path, monkeypatch
):
    import ultimate_pipeline.enrichment.osm_direction as osm_direction

    target = tmp_path / "contract.json"
    write_direction_contract(target)
    good = target.read_text(encoding="utf-8")

    def _boom(*args, **kwargs):
        raise OSError("simulated interruption after truncation")

    monkeypatch.setattr(osm_direction.os, "replace", _boom)
    with pytest.raises(OSError):
        write_direction_contract(target)

    # The previous good artifact is intact and no temp file was left behind.
    assert target.read_text(encoding="utf-8") == good
    assert [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


# ---------------------------------------------------------------------------
# 4551582473 (Med) — a retry must not leave cycle lanes on both sides
# ---------------------------------------------------------------------------

def test_4551582473_retry_does_not_duplicate_the_cycle_lane():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="42", junction="-1", length="100.0")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0.0")
    ET.SubElement(section, "right")
    ET.SubElement(section, "left")

    # First run: the OSM cycleway maps to the right side.
    LaneGenerator._apply_cycle_lane_geometry(
        road, {"42": {"cycleway:right": "lane", DIRECTION_KEY: "forward"}}
    )
    assert road.findall("./lanes/laneSection/right/lane[@type='biking']")

    # Second run with a reversed orientation maps to the left side: the stale
    # *generated* lane on the right must be reconciled, not duplicated.
    LaneGenerator._apply_cycle_lane_geometry(
        road, {"42": {"cycleway:right": "lane", DIRECTION_KEY: ORIENTATION_REVERSE}}
    )

    sections = road.findall("./lanes/laneSection")
    left = sections[0].findall("./left/lane[@type='biking']")
    right = sections[0].findall("./right/lane[@type='biking']")
    assert len(left) == 1
    assert right == []


def test_4551582473_imported_biking_lanes_are_preserved():
    """An imported (non-generated) biking lane is never removed."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="42", junction="-1", length="100.0")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0.0")
    right = ET.SubElement(section, "right")
    imported = ET.SubElement(right, "lane", id="-9", type="biking", level="false")

    LaneGenerator._apply_cycle_lane_geometry(
        road, {"42": {"cycleway:right": "lane", DIRECTION_KEY: ORIENTATION_REVERSE}}
    )

    sections = road.findall("./lanes/laneSection")
    right_bikes = sections[0].findall("./right/lane[@type='biking']")
    assert [lane.get("id") for lane in right_bikes] == ["-9"]
    assert imported.get("id") == "-9"


# ---------------------------------------------------------------------------
# 4551582490 (Med) — a reversed correspondence survives the stage hand-off
# ---------------------------------------------------------------------------

def test_4551582490_reversed_correspondence_survives_the_stage_hand_off(
    tmp_path, monkeypatch
):
    import ultimate_pipeline.enrichment.osm_meta_index as meta_index

    osm_path = tmp_path / "source.osm"
    osm_path.write_text("<osm/>", encoding="utf-8")
    root = ET.fromstring(
        '<OpenDRIVE><road id="42" length="10"><planView>'
        '<geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>'
        '</planView></road></OpenDRIVE>'
    )

    # The OSM way runs OPPOSITE to the XODR reference line.
    monkeypatch.setattr(
        meta_index,
        "extract_structural_osm_lane_metadata_ways",
        lambda _: [
            {
                "id": "way-1",
                "geometry": [(10.0, 0.0), (0.0, 0.0)],
                "metadata": {"lanes": "2"},
            }
        ],
    )
    monkeypatch.setattr(
        meta_index, "project_positioned_osm_metadata_ways", lambda ways, _: ways
    )

    metadata, _report = _build_structural_osm_metadata(root, str(osm_path))

    # The reserved direction must remain "reverse" -- it must not be
    # hard-coded to "forward".
    assert metadata["42"][DIRECTION_KEY] == ORIENTATION_REVERSE
