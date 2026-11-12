"""V95 strict target-existence and XML admission controls; offline synthetic maps."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ultimate_pipeline.quality.check_road_boundary_links_strict import check_road_boundary_links_strict


def _road(rid: str, lanes: tuple[str, ...] = ('-1',), *, road_link: str = '',
          lane_link: str = '', width: float = 3.5, lane_type: str = 'driving', sections: str | None = None) -> str:
    if sections is None:
        lanes_xml = ''.join(f'<lane id="{lid}" type="{lane_type}"><link>{lane_link}</link><width sOffset="0" a="{width}" b="0" c="0" d="0"/></lane>' for lid in lanes)
        sections = f'<laneSection s="0"><center><lane id="0" type="none"/></center><right>{lanes_xml}</right></laneSection>'
    return (f'<road id="{rid}" length="10" junction="-1"><link>{road_link}</link>'
            f'<lanes>{sections}</lanes></road>')


def _write(tmp_path: Path, *roads: str, junctions: str = '', header: str = '') -> Path:
    p = tmp_path / 'map.xodr'
    p.write_text(f'<OpenDRIVE>{header}{"".join(roads)}{junctions}</OpenDRIVE>', encoding='utf-8')
    return p


def _check(tmp_path: Path, *roads: str, junctions: str = '') -> dict:
    return check_road_boundary_links_strict(_write(tmp_path, *roads, junctions=junctions))


def _codes(rep: dict) -> list[str]:
    return [issue['code'] for issue in rep['issues']]


def test_valid_crossroad_explicit_link_passes(tmp_path: Path) -> None:
    a = _road('A', road_link='<successor elementType="road" elementId="B" contactPoint="start"/>',
              lane_link='<successor id="-1"/>')
    b = _road('B')
    rep = _check(tmp_path, a, b)
    assert rep['ok'] is True, rep
    assert rep['checked_road_links'] == 1
    assert rep['checked_lane_links'] == 1
    assert rep['input_sha256'] and len(rep['input_sha256']) == 64


def test_missing_target_road_is_not_skipped(tmp_path: Path) -> None:
    rep = _check(tmp_path, _road('A', road_link='<successor elementType="road" elementId="MISSING" contactPoint="start"/>',
                                 lane_link='<successor id="-1"/>'))
    assert rep['ok'] is False
    assert 'MISSING_TARGET_ROAD' in _codes(rep)


@pytest.mark.parametrize('cp', ['', 'middle', 'START'])
def test_invalid_contact_point_rejected_not_assumed_start(tmp_path: Path, cp: str) -> None:
    attr = f' contactPoint="{cp}"' if cp else ''
    rep = _check(tmp_path, _road('A', road_link=f'<successor elementType="road" elementId="B"{attr}/>',
                                     lane_link='<successor id="-1"/>'), _road('B'))
    assert 'MISSING_OR_INVALID_CONTACT_POINT' in _codes(rep)


def test_missing_target_lane_at_linked_boundary(tmp_path: Path) -> None:
    rep = _check(tmp_path, _road('A', road_link='<successor elementType="road" elementId="B" contactPoint="start"/>',
                                     lane_link='<successor id="-4"/>'), _road('B', lanes=('-1',)))
    assert 'MISSING_CROSSROAD_LANE' in _codes(rep)


def test_non_drivable_target_is_not_clean(tmp_path: Path) -> None:
    rep = _check(tmp_path, _road('A', road_link='<successor elementType="road" elementId="B" contactPoint="start"/>',
                                     lane_link='<successor id="-1"/>'), _road('B', lane_type='sidewalk'))
    assert 'NONDRIVABLE_CROSSROAD_TARGET' in _codes(rep)


def test_correct_end_boundary_orientation_used(tmp_path: Path) -> None:
    sec0 = '<laneSection s="0"><right><lane id="-1" type="driving"/></right></laneSection>'
    sec5 = '<laneSection s="5"><right><lane id="-9" type="driving"/></right></laneSection>'
    rep = _check(tmp_path, _road('A', road_link='<successor elementType="road" elementId="B" contactPoint="end"/>',
                                     lane_link='<successor id="-9"/>'), _road('B', sections=sec0 + sec5))
    assert rep['ok'] is True, rep


def test_wrong_end_boundary_target_rejected(tmp_path: Path) -> None:
    sec0 = '<laneSection s="0"><right><lane id="-9" type="driving"/></right></laneSection>'
    sec5 = '<laneSection s="5"><right><lane id="-1" type="driving"/></right></laneSection>'
    rep = _check(tmp_path, _road('A', road_link='<successor elementType="road" elementId="B" contactPoint="end"/>',
                                     lane_link='<successor id="-9"/>'), _road('B', sections=sec0 + sec5))
    assert 'MISSING_CROSSROAD_LANE' in _codes(rep)


def test_valid_junction_mapping(tmp_path: Path) -> None:
    incoming = _road('A', road_link='<successor elementType="junction" elementId="J"/>')
    connector = _road('C', lanes=('-2',))
    junction = '<junction id="J"><connection incomingRoad="A" connectingRoad="C" contactPoint="start"><laneLink from="-1" to="-2"/></connection></junction>'
    rep = _check(tmp_path, incoming, connector, junctions=junction)
    assert rep['ok'] is True, rep
    assert rep['checked_junction_links'] == 1


def test_junction_missing_target_lane(tmp_path: Path) -> None:
    incoming = _road('A', road_link='<successor elementType="junction" elementId="J"/>')
    connector = _road('C', lanes=('-2',))
    junction = '<junction id="J"><connection incomingRoad="A" connectingRoad="C" contactPoint="start"><laneLink from="-1" to="-9"/></connection></junction>'
    rep = _check(tmp_path, incoming, connector, junctions=junction)
    assert 'MISSING_JUNCTION_TO_LANE' in _codes(rep)


def test_junction_missing_source_lane(tmp_path: Path) -> None:
    incoming = _road('A', road_link='<successor elementType="junction" elementId="J"/>')
    connector = _road('C', lanes=('-2',))
    junction = '<junction id="J"><connection incomingRoad="A" connectingRoad="C" contactPoint="start"><laneLink from="-55" to="-2"/></connection></junction>'
    rep = _check(tmp_path, incoming, connector, junctions=junction)
    assert 'MISSING_JUNCTION_FROM_LANE' in _codes(rep)


def test_junction_incoming_side_never_inferred(tmp_path: Path) -> None:
    junction = '<junction id="J"><connection incomingRoad="A" connectingRoad="C" contactPoint="start"><laneLink from="-1" to="-1"/></connection></junction>'
    rep = _check(tmp_path, _road('A'), _road('C'), junctions=junction)
    assert 'UNVERIFIED_INCOMING_JUNCTION_SIDE' in _codes(rep)


def test_duplicate_road_id_rejected(tmp_path: Path) -> None:
    rep = _check(tmp_path, _road('A'), _road('A'))
    assert 'DUPLICATE_ROAD_ID' in _codes(rep)


def test_duplicate_lane_section_rejected(tmp_path: Path) -> None:
    sec = '<laneSection s="0"><right><lane id="-1" type="driving"/></right></laneSection>'
    rep = _check(tmp_path, _road('A', sections=sec + sec))
    assert 'DUPLICATE_LANE_SECTION' in _codes(rep)


def test_empty_map_fails(tmp_path: Path) -> None:
    rep = check_road_boundary_links_strict(_write(tmp_path))
    assert rep['status'] == 'FAIL'
    assert 'NO_ROADS' in _codes(rep)


def test_only_center_lanes_does_not_certify(tmp_path: Path) -> None:
    rep = _check(tmp_path, _road('A', lanes=()))
    assert 'NO_DRIVABLE_ROADS' in _codes(rep)


def test_utf16_doctype_rejected_before_xml_parse(tmp_path: Path) -> None:
    xml = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE OpenDRIVE [<!ENTITY bomb "X">]><OpenDRIVE><road id="A" length="10"/></OpenDRIVE>'
    p = tmp_path / 'utf16.xodr'
    p.write_bytes(xml.encode('utf-16'))
    rep = check_road_boundary_links_strict(p)
    assert rep['status'] == 'BLOCKED_INPUT'
    assert 'BLOCKED_XML_INPUT' in _codes(rep)


def test_prefix_comment_does_not_bypass_doctype(tmp_path: Path) -> None:
    p = tmp_path / 'comment_bypass.xodr'
    p.write_bytes(b'<!-- <OpenDRIVE -->' + b' ' * 70_000 + b'<!DOCTYPE OpenDRIVE [<!ENTITY x "X">]><OpenDRIVE></OpenDRIVE>')
    rep = check_road_boundary_links_strict(p)
    assert rep['status'] == 'BLOCKED_INPUT'
    assert 'BLOCKED_XML_INPUT' in _codes(rep)


def test_max_size_admission_before_read(tmp_path: Path) -> None:
    p = _write(tmp_path, _road('A'))
    rep = check_road_boundary_links_strict(p, max_bytes=16)
    assert rep['status'] == 'BLOCKED_INPUT'
    assert 'BLOCKED_XML_INPUT' in _codes(rep)


def test_report_truncates_display_not_number_of_failures(tmp_path: Path) -> None:
    bad = _road('A', road_link='<successor elementType="road" elementId="MISSING"/>')
    rep = check_road_boundary_links_strict(_write(tmp_path, bad, bad), max_issues=1)
    assert rep['num_issues'] > 1
    assert len(rep['issues']) == 1
    assert rep['issue_list_truncated'] is True
    assert rep['ok'] is False


def test_does_not_fabricate_missing_lane_successors(tmp_path: Path) -> None:
    p = _write(tmp_path, _road('A', road_link='<successor elementType="road" elementId="B" contactPoint="start"/>'), _road('B'))
    before = p.read_bytes()
    rep = check_road_boundary_links_strict(p)
    assert rep['ok'] is True, rep
    assert p.read_bytes() == before
    assert rep['scope'] == 'declared_road_and_junction_link_targets_only'


def test_cli_nonzero_on_invalid_link(tmp_path: Path) -> None:
    p = _write(tmp_path, _road('A', road_link='<successor elementType="road" elementId="X"/>'))
    out = tmp_path / 'report.json'
    proc = subprocess.run([sys.executable, '-m', 'ultimate_pipeline.quality.check_road_boundary_links_strict', str(p), '--out', str(out)], capture_output=True, text=True)
    assert proc.returncode == 2
    assert json.loads(out.read_text())['ok'] is False


def test_wrong_lane_id_sign_fails_instead_of_implicit_orientation_guess(tmp_path: Path) -> None:
    rep = _check(tmp_path, _road('A', lanes=('1',)))
    assert 'LANE_SIDE_SIGN_MISMATCH' in _codes(rep)


def test_malformed_lane_id_fails(tmp_path: Path) -> None:
    rep = _check(tmp_path, _road('A', lanes=('foo',)))
    assert 'INVALID_LANE_ID' in _codes(rep)


def test_duplicate_lane_id_same_section_fails(tmp_path: Path) -> None:
    rep = _check(tmp_path, _road('A', lanes=('-1', '-1')))
    assert 'DUPLICATE_LANE_ID' in _codes(rep)


def test_valid_positive_left_lane_not_rejected(tmp_path: Path) -> None:
    sec = '<laneSection s="0"><left><lane id="1" type="driving"/></left><right><lane id="-1" type="driving"/></right></laneSection>'
    rep = _check(tmp_path, _road('A', sections=sec))
    assert rep['ok'] is True, rep


def test_road_link_to_missing_junction_rejected(tmp_path: Path) -> None:
    rep = _check(tmp_path, _road('A', road_link='<successor elementType="junction" elementId="NOT_HERE"/>'))
    assert 'MISSING_TARGET_JUNCTION' in _codes(rep)


def test_unknown_road_link_type_rejected(tmp_path: Path) -> None:
    rep = _check(tmp_path, _road('A', road_link='<successor elementType="garbage" elementId="B"/>'), _road('B'))
    assert 'INVALID_ROAD_LINK_TYPE' in _codes(rep)


def test_duplicate_junction_ids_rejected(tmp_path: Path) -> None:
    rep = _check(tmp_path, _road('A'), junctions='<junction id="J"/><junction id="J"/>')
    assert 'DUPLICATE_JUNCTION_ID' in _codes(rep)
