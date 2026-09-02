# ultimate_pipeline/quality/check_junction_integrity.py -- zero prior
# test coverage. Live: imported directly by quality/quality_gate_manager.py
# (which is itself imported directly by main_pipeline.py). The module's
# own docstring frames it as "intentionally conservative... focuses on
# reference integrity" -- validates that <junction><connection> elements
# reference existing roads and lanes, and that roads claiming
# junction="<id>" reference a real <junction>. It is coarser than
# quality/check_lane_link_targets_exist.py's laneSection-boundary-aware
# check (that file validates a DIFFERENT thing -- intra-road lane
# predecessor/successor links, not cross-road junction connection
# laneLinks) -- confirmed this coarseness (any laneSection in the road
# counts, not just the boundary one) is the documented intended scope,
# not an accidental gap.
#
# Reviewed carefully for the "gate silently always passes" bug class
# already found once this session in a DIFFERENT function
# (gate_junction_integrity() in quality_gate_manager.py, per prior
# memory) -- that fix was in the gate-consuming/reporting logic, not this
# validator itself. This file's own reference-integrity logic reviewed
# independently here; no bug found.
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.quality.check_junction_integrity import JunctionIntegrityGate


def _xodr(inner: str) -> ET.Element:
    return ET.fromstring(f'<?xml version="1.0"?><OpenDRIVE>{inner}</OpenDRIVE>')


def _road(rid: str, junction: str = "-1", lane_ids: tuple[str, ...] = ("-1",)) -> str:
    lanes_xml = "".join(f'<lane id="{lid}" type="driving"/>' for lid in lane_ids)
    return (
        f'<road name="R{rid}" length="10.0" id="{rid}" junction="{junction}">'
        f'<lanes><laneSection s="0"><right>{lanes_xml}</right></laneSection></lanes>'
        f'</road>'
    )


def test_valid_junction_with_correct_references_has_no_issues():
    root = _xodr(
        _road("1")
        + _road("2", junction="100")
        + _road("3")
        + '<junction id="100" name="J">'
        '<connection id="0" incomingRoad="1" connectingRoad="2">'
        '<laneLink from="-1" to="-1"/>'
        '</connection>'
        '</junction>'
    )

    result = JunctionIntegrityGate.validate(root)

    assert result["ok"] is True
    assert result["issue_count"] == 0
    assert result["issues"] == []


def test_missing_incoming_road_flagged():
    root = _xodr(
        _road("2", junction="100")
        + '<junction id="100" name="J">'
        '<connection id="0" incomingRoad="999" connectingRoad="2"/>'
        '</junction>'
    )

    result = JunctionIntegrityGate.validate(root)

    assert result["ok"] is False
    types = [i["type"] for i in result["issues"]]
    assert "missing_incoming_road" in types


def test_missing_connecting_road_flagged():
    root = _xodr(
        _road("1")
        + '<junction id="100" name="J">'
        '<connection id="0" incomingRoad="1" connectingRoad="999"/>'
        '</junction>'
    )

    result = JunctionIntegrityGate.validate(root)

    assert result["ok"] is False
    types = [i["type"] for i in result["issues"]]
    assert "missing_connecting_road" in types


def test_laneLink_missing_lane_in_incoming_road_flagged():
    root = _xodr(
        _road("1", lane_ids=("-1",))
        + _road("2", junction="100", lane_ids=("-1",))
        + '<junction id="100" name="J">'
        '<connection id="0" incomingRoad="1" connectingRoad="2">'
        '<laneLink from="-5" to="-1"/>'
        '</connection>'
        '</junction>'
    )

    result = JunctionIntegrityGate.validate(root)

    assert result["ok"] is False
    issue = next(i for i in result["issues"] if i["type"] == "missing_lane_in_incoming_road")
    assert issue["lane_from"] == "-5"


def test_laneLink_missing_lane_in_connecting_road_flagged():
    root = _xodr(
        _road("1", lane_ids=("-1",))
        + _road("2", junction="100", lane_ids=("-1",))
        + '<junction id="100" name="J">'
        '<connection id="0" incomingRoad="1" connectingRoad="2">'
        '<laneLink from="-1" to="-7"/>'
        '</connection>'
        '</junction>'
    )

    result = JunctionIntegrityGate.validate(root)

    assert result["ok"] is False
    issue = next(i for i in result["issues"] if i["type"] == "missing_lane_in_connecting_road")
    assert issue["lane_to"] == "-7"


def test_laneLink_not_checked_when_roads_are_missing_avoids_double_reporting():
    # incomingRoad doesn't exist at all -- laneLink validation must be
    # skipped for this connection (nothing sensible to check against),
    # not crash or produce a spurious lane-missing issue on top of the
    # already-reported missing_incoming_road.
    root = _xodr(
        _road("2", junction="100")
        + '<junction id="100" name="J">'
        '<connection id="0" incomingRoad="999" connectingRoad="2">'
        '<laneLink from="-1" to="-1"/>'
        '</connection>'
        '</junction>'
    )

    result = JunctionIntegrityGate.validate(root)

    types = [i["type"] for i in result["issues"]]
    assert types == ["missing_incoming_road"]


def test_road_referencing_missing_junction_flagged():
    root = _xodr(_road("1", junction="999"))

    result = JunctionIntegrityGate.validate(root)

    assert result["ok"] is False
    issue = next(i for i in result["issues"] if i["type"] == "road_references_missing_junction")
    assert issue["road_id"] == "1"
    assert issue["junction"] == "999"


def test_road_with_junction_minus_one_is_not_flagged():
    root = _xodr(_road("1", junction="-1"))

    result = JunctionIntegrityGate.validate(root)

    assert result["ok"] is True


def test_road_with_no_junction_attribute_is_not_flagged():
    root = ET.fromstring(
        '<?xml version="1.0"?><OpenDRIVE>'
        '<road name="R1" length="10.0" id="1">'
        '<lanes><laneSection s="0"><right><lane id="-1" type="driving"/></right></laneSection></lanes>'
        '</road>'
        '</OpenDRIVE>'
    )

    result = JunctionIntegrityGate.validate(root)

    assert result["ok"] is True


def test_accepts_file_path_not_just_element(tmp_path):
    xodr_path = tmp_path / "in.xodr"
    xodr_path.write_text(
        '<?xml version="1.0"?><OpenDRIVE>' + _road("1") + '</OpenDRIVE>',
        encoding="utf-8",
    )

    result = JunctionIntegrityGate.validate(str(xodr_path))

    assert result["ok"] is True


def test_malformed_xodr_returns_error_dict_not_crash(tmp_path):
    xodr_path = tmp_path / "bad.xodr"
    xodr_path.write_text("not valid xml <<<", encoding="utf-8")

    result = JunctionIntegrityGate.validate(str(xodr_path))

    assert result["ok"] is False
    assert "error" in result


def test_lane_ids_collected_across_all_lane_sections_of_a_road():
    # Documented "conservative" scope: a lane id valid ANYWHERE in the
    # road (any laneSection), not just the laneSection touching the
    # junction, is accepted -- confirms this coarser behavior is what the
    # code actually does (vs. some stricter boundary-aware check).
    road = (
        '<road name="R1" length="20.0" id="1" junction="-1">'
        '<lanes>'
        '<laneSection s="0"><right><lane id="-1" type="driving"/></right></laneSection>'
        '<laneSection s="10"><right><lane id="-2" type="driving"/></right></laneSection>'
        '</lanes>'
        '</road>'
    )
    root = _xodr(
        road
        + _road("2", junction="100", lane_ids=("-1",))
        + '<junction id="100" name="J">'
        '<connection id="0" incomingRoad="1" connectingRoad="2">'
        '<laneLink from="-2" to="-1"/>'
        '</connection>'
        '</junction>'
    )

    result = JunctionIntegrityGate.validate(root)

    assert result["ok"] is True
