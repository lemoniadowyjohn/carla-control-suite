import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.tools.phase_g6_junction_lanelinks import (
    audit_junction_lanelinks,
    checks_of,
    compute_repair_lateral_distances,
    repair_coverage_gaps,
)


def _road(rid: str, lanes: str, link: str = "", junction: str = "-1") -> str:
    return f"""
  <road id="{rid}" length="10" junction="{junction}">
    <link>{link}</link>
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
    <lanes><laneSection s="0">
      <left>{lanes.get("left", "") if isinstance(lanes, dict) else ""}</left>
      <center><lane id="0" type="none"/></center>
      <right>{lanes.get("right", lanes) if isinstance(lanes, dict) else lanes}</right>
    </laneSection></lanes>
  </road>
"""


def _lane(lid: int, lane_type: str = "driving") -> str:
    return f'<lane id="{lid}" type="{lane_type}"><width sOffset="0" a="3.5"/></lane>'


def _root(body: str) -> ET.Element:
    return ET.fromstring(f'<OpenDRIVE><header version="1.7"/>{body}</OpenDRIVE>')


def test_g6_from_coverage_ignores_opposite_direction_lane_at_road_end() -> None:
    root = _root(
        _road(
            "A",
            {"left": _lane(1), "right": _lane(-1)},
            '<successor elementType="junction" elementId="9"/>',
        )
        + _road("B", _lane(-1), junction="9")
        + """
  <junction id="9">
    <connection id="0" incomingRoad="A" connectingRoad="B" contactPoint="start">
      <laneLink from="-1" to="-1"/>
    </connection>
  </junction>
"""
    )

    audit = audit_junction_lanelinks(root)

    assert audit["missing_driving_from_coverage"] == []
    assert checks_of(audit)["complete_driving_from_coverage"] is True


def test_g6_from_coverage_requires_positive_lane_at_road_start() -> None:
    root = _root(
        _road(
            "A",
            {"left": _lane(1), "right": _lane(-1)},
            '<predecessor elementType="junction" elementId="9"/>',
        )
        + _road("B", _lane(-1), junction="9")
        + """
  <junction id="9">
    <connection id="0" incomingRoad="A" connectingRoad="B" contactPoint="start">
      <laneLink from="-1" to="-1"/>
    </connection>
  </junction>
"""
    )

    audit = audit_junction_lanelinks(root)

    assert audit["missing_driving_from_coverage"] == [
        {"junction": "9", "connection": "0", "incoming": "A", "lane": "1"}
    ]


def test_g6_to_coverage_ignores_opposite_direction_lane_at_connecting_start() -> None:
    root = _root(
        _road("A", _lane(-1), '<successor elementType="junction" elementId="9"/>')
        + _road("B", {"left": _lane(1), "right": _lane(-1)}, junction="9")
        + """
  <junction id="9">
    <connection id="0" incomingRoad="A" connectingRoad="B" contactPoint="start">
      <laneLink from="-1" to="-1"/>
    </connection>
  </junction>
"""
    )

    audit = audit_junction_lanelinks(root)

    assert audit["missing_driving_to_coverage"] == []
    assert checks_of(audit)["complete_driving_to_coverage"] is True


def test_g6_repair_iterates_chained_lane_merge_coverage() -> None:
    root = _root(
        _road(
            "A",
            _lane(-1) + _lane(-2) + _lane(-3),
            '<successor elementType="junction" elementId="9"/>',
        )
        + _road("B", _lane(-1), junction="9")
        + """
  <junction id="9">
    <connection id="0" incomingRoad="A" connectingRoad="B" contactPoint="start">
      <laneLink from="-3" to="-1"/>
    </connection>
  </junction>
"""
    )

    before = audit_junction_lanelinks(root)
    assert {item["lane"] for item in before["missing_driving_from_coverage"]} == {"-1", "-2"}

    repair = repair_coverage_gaps(root)
    after = audit_junction_lanelinks(root)

    assert repair["repair_issues"] == []
    assert {(item["lane"], item["repair_pass"]) for item in repair["added_lanelinks"]} == {
        ("-2", 1),
        ("-1", 2),
    }
    assert checks_of(after)["complete_driving_from_coverage"] is True


def test_compute_repair_lateral_distances_measures_each_addition() -> None:
    """Verified against the pinned map-of-record this session: a 5-sample
    spot-check of this exact repair implied near-zero merge distances, but
    the true population median across all 126 additions was 3.5m (max 7.1m).
    This function must surface a real, per-addition distance -- not silently
    assume zero -- and lanes farther from the target must show a larger
    distance than lanes closer to it."""
    root = _root(
        _road(
            "A",
            _lane(-1) + _lane(-2) + _lane(-3),
            '<successor elementType="junction" elementId="9"/>',
        )
        + _road("B", _lane(-1), junction="9")
        + """
  <junction id="9">
    <connection id="0" incomingRoad="A" connectingRoad="B" contactPoint="start">
      <laneLink from="-3" to="-1"/>
    </connection>
  </junction>
"""
    )
    repair = repair_coverage_gaps(root)

    distances = compute_repair_lateral_distances(root, repair["added_lanelinks"])

    by_lane = {d["lane"]: d for d in distances}
    assert by_lane["-1"]["distance_m"] == pytest.approx(10.0, abs=1e-6)
    assert by_lane["-2"]["distance_m"] == pytest.approx(10.594810050208546, abs=1e-6)
    # lane -2 is farther from the target than lane -1 -- the distance must
    # reflect that, not report a flat/near-zero value for every addition.
    assert by_lane["-2"]["distance_m"] > by_lane["-1"]["distance_m"]
    assert all(d["reason"] is None for d in distances)


def test_compute_repair_lateral_distances_reports_reason_when_unmeasurable() -> None:
    """An addition referencing a junction/connection that no longer exists
    in `root` must report distance_m=None with a reason, not raise or
    silently vanish from the output."""
    root = _root(_road("A", _lane(-1)))
    fake_addition = [{
        "junction": "does-not-exist", "connection": "0",
        "incoming": "A", "lane": "-1", "target": "-1", "repair_pass": 1,
    }]

    distances = compute_repair_lateral_distances(root, fake_addition)

    assert len(distances) == 1
    assert distances[0]["distance_m"] is None
    assert distances[0]["reason"] == "incoming_road_or_connection_missing"
