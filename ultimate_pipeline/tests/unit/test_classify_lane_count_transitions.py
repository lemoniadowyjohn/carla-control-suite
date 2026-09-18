from __future__ import annotations

from pathlib import Path
from typing import Any

from ultimate_pipeline.quality.classify_lane_count_transitions import (
    JUNCTION_TRANSITION,
    LANESECTION_LOCAL_TRANSITION,
    MISSING_PROVENANCE,
    ORDINARY_MERGE,
    ORDINARY_SPLIT,
    RAMP_CONNECTOR_TRANSITION,
    SOURCE_PROVEN,
    SUSPICIOUS,
    UNRESOLVED_LINK,
    classify_lane_count_transitions,
)


def _lane_xml(
    lane_id: int,
    *,
    width_segments: list[tuple[float, float, float, float, float]] | None = None,
    source: str | None = None,
) -> str:
    if width_segments is None:
        width_segments = [(0.0, 3.5, 0.0, 0.0, 0.0)]
    widths = "".join(
        f'<width sOffset="{so}" a="{a}" b="{b}" c="{c}" d="{d}"/>'
        for so, a, b, c, d in width_segments
    )
    metadata = (
        f'<userData><vector key="lane_count_source" value="{source}"/></userData>'
        if source
        else ""
    )
    return f'<lane id="{lane_id}" type="driving">{widths}{metadata}</lane>'


def _section_xml(s: float, lanes_xml: str) -> str:
    return f'<laneSection s="{s}"><right>{lanes_xml}</right></laneSection>'


def _road_xml(
    road_id: str,
    sections_xml: str,
    *,
    length: float,
    junction: str = "-1",
    predecessor: str = "",
    successor: str = "",
) -> str:
    return (
        f'<road id="{road_id}" length="{length}" junction="{junction}"><link>'
        f"{predecessor}{successor}</link><planView>"
        f'<geometry s="0" x="0" y="0" hdg="0" length="{length}"><line/></geometry>'
        f"</planView><lanes>{sections_xml}</lanes></road>"
    )


def _empty_lanes_road_xml(road_id: str, *, length: float, successor: str = "", predecessor: str = "") -> str:
    return (
        f'<road id="{road_id}" length="{length}" junction="-1"><link>'
        f"{predecessor}{successor}</link><planView>"
        f'<geometry s="0" x="0" y="0" hdg="0" length="{length}"><line/></geometry>'
        "</planView><lanes></lanes></road>"
    )


def _pred(road_id: str, contact: str = "end") -> str:
    return f'<predecessor elementType="road" elementId="{road_id}" contactPoint="{contact}"/>'


def _succ(road_id: str, contact: str = "start") -> str:
    return f'<successor elementType="road" elementId="{road_id}" contactPoint="{contact}"/>'


def _doc(*parts: str) -> str:
    return "<OpenDRIVE>" + "".join(parts) + "</OpenDRIVE>"


def _junction_xml(junction_id: str, connections_xml: str) -> str:
    return f'<junction name="{junction_id}" id="{junction_id}">{connections_xml}</junction>'


def _connection_xml(
    conn_id: str, incoming: str, connecting: str, lane_links: list[tuple[int, int]], contact: str = "start"
) -> str:
    links = "".join(f'<laneLink from="{f}" to="{t}"/>' for f, t in lane_links)
    return (
        f'<connection id="{conn_id}" incomingRoad="{incoming}" connectingRoad="{connecting}" '
        f'contactPoint="{contact}">{links}</connection>'
    )


def _write(tmp_path: Path, xml: str) -> Path:
    path = tmp_path / "map.xodr"
    path.write_text(xml, encoding="utf-8")
    return path


def _find(classified: list[dict[str, Any]], road_a: str, road_b: str) -> dict[str, Any]:
    for item in classified:
        ids = {item["source"]["road_id"], item["target"]["road_id"]}
        if ids == {road_a, road_b}:
            return item
    raise AssertionError(f"no classified finding for boundary ({road_a}, {road_b}) in {classified}")


def test_raw_metric_preserved_and_counts_sum_to_original_unexplained_count(tmp_path: Path) -> None:
    # Two independent unexplained boundaries with no special evidence: both
    # should be classifiable (missing_provenance / suspicious), and the sum
    # of all classification buckets must equal the original raw count.
    doc = _doc(
        _road_xml("1", _section_xml(0, _lane_xml(-1)), length=30, successor=_succ("2")),
        _road_xml(
            "2",
            _section_xml(0, _lane_xml(-1) + _lane_xml(-2)),
            length=30,
            predecessor=_pred("1"),
        ),
    )
    path = _write(tmp_path, doc)
    result = classify_lane_count_transitions(path)

    assert result["raw_check"]["summary_metrics"]["unexplained_change"] == 1
    assert result["classified_unexplained_count"] == 1
    assert sum(result["classification_summary"].values()) == 1


def test_source_proven_lane_change(tmp_path: Path) -> None:
    doc = _doc(
        _road_xml(
            "1",
            _section_xml(0, _lane_xml(-1, source="osm:lanes")),
            length=30,
            successor=_succ("2"),
        ),
        _road_xml(
            "2",
            _section_xml(0, _lane_xml(-1) + _lane_xml(-2)),
            length=30,
            predecessor=_pred("1"),
        ),
    )
    result = classify_lane_count_transitions(_write(tmp_path, doc))
    finding = _find(result["classified_findings"], "1", "2")
    assert finding["category"] == SOURCE_PROVEN
    assert finding["evidence"]["proven_side"] == "source"


def test_junction_transition_declared_connection_tier(tmp_path: Path) -> None:
    doc = _doc(
        _road_xml("10", _section_xml(0, _lane_xml(-1) + _lane_xml(-2)), length=50, successor=_succ("20")),
        _road_xml(
            "20",
            _section_xml(0, _lane_xml(-1)),
            length=10,
            junction="1",
            predecessor=_pred("10", "end"),
        ),
        _junction_xml("1", _connection_xml("0", "10", "20", [(-1, -1)])),
    )
    result = classify_lane_count_transitions(_write(tmp_path, doc))
    finding = _find(result["classified_findings"], "10", "20")
    assert finding["category"] == JUNCTION_TRANSITION
    assert finding["evidence"]["tier"] == "declared_connection"


def test_junction_transition_connector_adjacent_tier(tmp_path: Path) -> None:
    # Road 20 is a real, registered junction connector (declared as
    # connectingRoad for the 10->20 movement, where counts happen to
    # match) but the boundary under test is its *other* end (20->30),
    # which OpenDRIVE's <connection> schema never separately declares.
    doc = _doc(
        _road_xml("10", _section_xml(0, _lane_xml(-1)), length=50, successor=_succ("20")),
        _road_xml(
            "20",
            _section_xml(0, _lane_xml(-1)),
            length=10,
            junction="1",
            predecessor=_pred("10", "end"),
            successor=_succ("30"),
        ),
        _road_xml(
            "30",
            _section_xml(0, _lane_xml(-1) + _lane_xml(-2)),
            length=50,
            predecessor=_pred("20", "end"),
        ),
        _junction_xml("1", _connection_xml("0", "10", "20", [(-1, -1)])),
    )
    result = classify_lane_count_transitions(_write(tmp_path, doc))
    finding = _find(result["classified_findings"], "20", "30")
    assert finding["category"] == JUNCTION_TRANSITION
    assert finding["evidence"]["tier"] == "connector_adjacent"
    assert finding["evidence"]["connector_road_id"] == "20"


def test_ramp_connector_transition(tmp_path: Path) -> None:
    doc = _doc(
        _road_xml("40", _section_xml(0, _lane_xml(-1) + _lane_xml(-2)), length=200, successor=_succ("41")),
        _road_xml("41", _section_xml(0, _lane_xml(-1)), length=10, predecessor=_pred("40")),
    )
    result = classify_lane_count_transitions(_write(tmp_path, doc))
    finding = _find(result["classified_findings"], "40", "41")
    assert finding["category"] == RAMP_CONNECTOR_TRANSITION
    assert finding["evidence"]["short_side"] == "target"


def test_lanesection_local_transition(tmp_path: Path) -> None:
    # Road 50's own first laneSection (the one read at its "start" edge) is
    # only 3m long before a second laneSection takes over -- the lane-count
    # change is a local taper zone, not an abrupt jump exactly at the link.
    sections = _section_xml(0, _lane_xml(-1) + _lane_xml(-2)) + _section_xml(
        3, _lane_xml(-1) + _lane_xml(-2)
    )
    doc = _doc(
        _road_xml("49", _section_xml(0, _lane_xml(-1)), length=50, successor=_succ("50")),
        _road_xml("50", sections, length=100, predecessor=_pred("49")),
    )
    result = classify_lane_count_transitions(_write(tmp_path, doc))
    finding = _find(result["classified_findings"], "49", "50")
    assert finding["category"] == LANESECTION_LOCAL_TRANSITION
    assert finding["evidence"]["target_edge_section_length_m"] == 3.0


def test_ordinary_merge_with_taper_evidence(tmp_path: Path) -> None:
    # Road 60 has two driving lanes; lane -2 tapers from full width (3.5m)
    # at the far end of its section down to 0.1m right at the road's end
    # (the link boundary), consistent with a genuine converging lane.
    lane_minus2 = _lane_xml(-2, width_segments=[(0.0, 3.5, (0.1 - 3.5) / 30.0, 0.0, 0.0)])
    doc = _doc(
        _road_xml(
            "60",
            _section_xml(0, _lane_xml(-1) + lane_minus2),
            length=30,
            successor=_succ("61"),
        ),
        _road_xml("61", _section_xml(0, _lane_xml(-1)), length=40, predecessor=_pred("60")),
    )
    result = classify_lane_count_transitions(_write(tmp_path, doc))
    finding = _find(result["classified_findings"], "60", "61")
    assert finding["category"] == ORDINARY_MERGE
    assert finding["evidence"]["tapering_lane_ids"] == ["-2"]


def test_ordinary_split_with_taper_evidence(tmp_path: Path) -> None:
    # Road 71 has two driving lanes; lane -2 tapers from 0.1m at the start
    # (the link boundary) up to full width (3.5m) by the far end of its
    # section, consistent with a genuine diverging lane.
    lane_minus2 = _lane_xml(-2, width_segments=[(0.0, 0.1, (3.5 - 0.1) / 30.0, 0.0, 0.0)])
    doc = _doc(
        _road_xml("70", _section_xml(0, _lane_xml(-1)), length=40, successor=_succ("71")),
        _road_xml(
            "71",
            _section_xml(0, _lane_xml(-1) + lane_minus2),
            length=30,
            predecessor=_pred("70"),
        ),
    )
    result = classify_lane_count_transitions(_write(tmp_path, doc))
    finding = _find(result["classified_findings"], "70", "71")
    assert finding["category"] == ORDINARY_SPLIT
    assert finding["evidence"]["tapering_lane_ids"] == ["-2"]


def test_missing_provenance_small_delta_no_other_evidence(tmp_path: Path) -> None:
    doc = _doc(
        _road_xml("80", _section_xml(0, _lane_xml(-1)), length=30, successor=_succ("81")),
        _road_xml(
            "81",
            _section_xml(0, _lane_xml(-1) + _lane_xml(-2)),
            length=30,
            predecessor=_pred("80"),
        ),
    )
    result = classify_lane_count_transitions(_write(tmp_path, doc))
    finding = _find(result["classified_findings"], "80", "81")
    assert finding["category"] == MISSING_PROVENANCE
    assert finding["evidence"]["delta"] == 1


def test_suspicious_unexplained_discontinuity_large_delta(tmp_path: Path) -> None:
    doc = _doc(
        _road_xml("90", _section_xml(0, _lane_xml(-1)), length=30, successor=_succ("91")),
        _road_xml(
            "91",
            _section_xml(0, _lane_xml(-1) + _lane_xml(-2) + _lane_xml(-3) + _lane_xml(-4)),
            length=30,
            predecessor=_pred("90"),
        ),
    )
    result = classify_lane_count_transitions(_write(tmp_path, doc))
    finding = _find(result["classified_findings"], "90", "91")
    assert finding["category"] == SUSPICIOUS
    assert finding["evidence"]["delta"] == 3
    assert finding in result["suspicious_review_set"]


def test_unresolved_link_when_linked_road_has_no_lanesection_data(tmp_path: Path) -> None:
    doc = _doc(
        _empty_lanes_road_xml("100", length=20, successor=_succ("101")),
        _road_xml("101", _section_xml(0, _lane_xml(-1)), length=30, predecessor=_pred("100")),
    )
    result = classify_lane_count_transitions(_write(tmp_path, doc))
    finding = _find(result["classified_findings"], "100", "101")
    assert finding["category"] == UNRESOLVED_LINK


def test_no_change_and_osm_explained_boundaries_are_not_classified(tmp_path: Path) -> None:
    # NO_CHANGE and OSM_EXPLAINED_CHANGE boundaries from the raw checker
    # must not appear in classified_findings at all -- this module only
    # ever touches the UNEXPLAINED_CHANGE bucket.
    doc = _doc(
        _road_xml(
            "1",
            _section_xml(0, _lane_xml(-1, source="osm:lanes")),
            length=30,
            successor=_succ("2"),
        ),
        _road_xml(
            "2",
            _section_xml(0, _lane_xml(-1, source="osm:lanes")),
            length=30,
            predecessor=_pred("1"),
        ),
    )
    result = classify_lane_count_transitions(_write(tmp_path, doc))
    assert result["raw_check"]["summary_metrics"]["osm_explained_change"] == 0
    assert result["raw_check"]["summary_metrics"]["no_change"] == 1
    assert result["classified_findings"] == []
    assert result["classified_unexplained_count"] == 0
