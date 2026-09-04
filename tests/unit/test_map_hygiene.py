# tests/unit/test_map_hygiene.py
# -*- coding: utf-8 -*-

"""
Tests for C10 map-hygiene repairs: island quarantine, degenerate-lane
repair, and genuine (post-C9) elevation z-seam repair.

Per reports/post_audit_hardening/C10_map_hygiene.md:
- Islands: connected components below UP_MIN_COMPONENT_ROADS are quarantined
  (never silently deleted -- reported and reversible).
- Degenerate lanes: widths below UP_MIN_LANE_WIDTH_M (or non-finite width
  polynomials) are repaired to a floor width, or the road is quarantined.
- z-seams: genuine (non-junction-lane-offset) road-to-road z-steps, using
  C9's corrected check_elevation_continuity (imported, not reimplemented),
  are chained so z_end(A) == z_start(B) within eps_z.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.quality.map_hygiene import (
    quarantine_island_roads,
    repair_degenerate_lanes,
    repair_true_zseams,
    repair_lane_width_discontinuities,
)


def _write(tmp_path: Path, name: str, xml_text: str) -> str:
    path = tmp_path / name
    path.write_text(xml_text, encoding="utf-8")
    return str(path)


def _road(
    rid: str,
    *,
    length: float = 10.0,
    junction: str = "-1",
    successor: str = None,
    predecessor: str = None,
    successor_contact: str = "start",
    predecessor_contact: str = "end",
    lane_widths=None,
    elevation_a: float = 0.0,
    elevation_b: float = 0.0,
) -> str:
    """Build a single <road> XML fragment with optional link/lanes/elevation."""
    link = ""
    if successor is not None or predecessor is not None:
        parts = []
        if predecessor is not None:
            parts.append(
                f'<predecessor elementType="road" elementId="{predecessor}" contactPoint="{predecessor_contact}"/>'
            )
        if successor is not None:
            parts.append(
                f'<successor elementType="road" elementId="{successor}" contactPoint="{successor_contact}"/>'
            )
        link = "<link>" + "".join(parts) + "</link>"

    lanes_xml = ""
    if lane_widths is not None:
        lane_entries = []
        for lane_id, width in lane_widths:
            lane_entries.append(
                f'<lane id="{lane_id}" type="driving" level="false">'
                f'<width sOffset="0" a="{width}" b="0" c="0" d="0"/>'
                "</lane>"
            )
        lanes_xml = (
            "<lanes><laneSection s=\"0\">"
            f'<right>{"".join(lane_entries)}</right>'
            "</laneSection></lanes>"
        )

    return (
        f'<road id="{rid}" length="{length}" junction="{junction}">'
        f"{link}"
        f'<planView><geometry s="0" x="0" y="0" hdg="0" length="{length}"><line/></geometry></planView>'
        f'<elevationProfile><elevation s="0" a="{elevation_a}" b="{elevation_b}" c="0.0" d="0.0"/></elevationProfile>'
        f"{lanes_xml}"
        "</road>"
    )


def _wrap(roads_xml: str) -> str:
    return '<?xml version="1.0" encoding="utf-8"?><OpenDRIVE>' + roads_xml + "</OpenDRIVE>"


def _junction(jid: str, connections: list) -> str:
    """Build a single <junction> XML fragment. `connections` is a list of
    (conn_id, incoming_road, connecting_road) tuples."""
    conn_entries = []
    for conn_id, incoming, connecting in connections:
        conn_entries.append(
            f'<connection id="{conn_id}" incomingRoad="{incoming}" '
            f'connectingRoad="{connecting}" contactPoint="start"/>'
        )
    return f'<junction id="{jid}" name="J{jid}">' + "".join(conn_entries) + "</junction>"


# ---------------------------------------------------------------------------
# 1. Island quarantine
# ---------------------------------------------------------------------------


def test_quarantine_island_roads_quarantines_small_component_keeps_main(tmp_path: Path) -> None:
    """A synthetic 2-component map: a large chain (well above the threshold)
    and a small disconnected pair of roads. The small component must be
    quarantined (removed from the output XODR + reported); the main
    component must survive untouched."""
    main_roads = []
    for i in range(1, 26):  # 25-road main chain: 1 <-> 2 <-> ... <-> 25
        succ = str(i + 1) if i < 25 else None
        pred = str(i - 1) if i > 1 else None
        main_roads.append(_road(str(i), successor=succ, predecessor=pred))

    # Disconnected island: roads 101 <-> 102 (size 2, isolated).
    island_roads = [
        _road("101", successor="102"),
        _road("102", predecessor="101"),
    ]

    xodr = _write(tmp_path, "islands.xodr", _wrap("".join(main_roads) + "".join(island_roads)))
    out_xodr = str(tmp_path / "islands_repaired.xodr")

    report = quarantine_island_roads(xodr, out_xodr, min_component_roads=20)

    assert report["ok"] is True
    assert set(report["quarantined_road_ids"]) == {"101", "102"}
    assert report["component_sizes_before"] == [25, 2]
    # The main component (25 roads) must not be in the quarantine list.
    for i in range(1, 26):
        assert str(i) not in report["quarantined_road_ids"]

    out_root = ET.parse(out_xodr).getroot()
    out_ids = {r.get("id") for r in out_root.findall("road")}
    assert out_ids == {str(i) for i in range(1, 26)}


def test_quarantine_island_roads_positive_control_single_component_untouched(
    tmp_path: Path,
) -> None:
    """Positive control: a map that is a single connected component (above
    threshold) must have nothing quarantined."""
    roads = []
    for i in range(1, 26):
        succ = str(i + 1) if i < 25 else None
        pred = str(i - 1) if i > 1 else None
        roads.append(_road(str(i), successor=succ, predecessor=pred))

    xodr = _write(tmp_path, "single_component.xodr", _wrap("".join(roads)))
    out_xodr = str(tmp_path / "single_component_out.xodr")

    report = quarantine_island_roads(xodr, out_xodr, min_component_roads=20)

    assert report["quarantined_road_ids"] == []
    assert report["component_sizes_before"] == [25]

    out_root = ET.parse(out_xodr).getroot()
    assert len(out_root.findall("road")) == 25


def test_quarantine_island_roads_writes_report_with_sizes_and_ids(tmp_path: Path) -> None:
    """The quarantine report must record component sizes and the specific
    quarantined road ids -- auditable, not a silent drop."""
    roads = []
    for i in range(1, 22):  # 21-road main chain
        succ = str(i + 1) if i < 21 else None
        pred = str(i - 1) if i > 1 else None
        roads.append(_road(str(i), successor=succ, predecessor=pred))
    roads.append(_road("999"))  # single isolated road, size-1 component

    xodr = _write(tmp_path, "report_map.xodr", _wrap("".join(roads)))
    out_xodr = str(tmp_path / "report_map_out.xodr")

    report = quarantine_island_roads(xodr, out_xodr, min_component_roads=20)

    assert report["quarantined_road_ids"] == ["999"]
    assert report["count"] == 1
    assert report["total_roads"] == 22
    assert report["min_component_roads"] == 20


def test_quarantine_island_roads_drops_dangling_connections_both_ends_quarantined(
    tmp_path: Path,
) -> None:
    """A junction whose ONLY connection references two roads that are both
    in the quarantined island must have that dangling connection dropped,
    and since it has zero connections left, the junction itself must be
    removed too. Confirmed via a real regen: leaving these in place produces
    JunctionIntegrityGate missing_incoming_road/missing_connecting_road
    issues for road ids this function had just quarantined."""
    main_roads = []
    for i in range(1, 26):
        succ = str(i + 1) if i < 25 else None
        pred = str(i - 1) if i > 1 else None
        main_roads.append(_road(str(i), successor=succ, predecessor=pred))

    island_roads = [
        _road("101", successor="102"),
        _road("102", predecessor="101"),
    ]
    dangling_junction = _junction("500", [("0", "101", "102")])

    xodr = _write(
        tmp_path,
        "islands_with_junction.xodr",
        _wrap("".join(main_roads) + "".join(island_roads) + dangling_junction),
    )
    out_xodr = str(tmp_path / "islands_with_junction_out.xodr")

    report = quarantine_island_roads(xodr, out_xodr, min_component_roads=20)

    assert set(report["quarantined_road_ids"]) == {"101", "102"}
    assert report["dangling_connections_dropped"] == 1
    assert report["empty_junctions_dropped"] == 1

    out_root = ET.parse(out_xodr).getroot()
    assert out_root.findall("junction") == []


def test_quarantine_island_roads_leaves_unrelated_junction_untouched(
    tmp_path: Path,
) -> None:
    """A junction entirely within the SURVIVING main component must be left
    completely alone (no connections dropped, junction not removed), while a
    separate junction entirely within the quarantined island is fully
    removed. Note: a single junction cannot legitimately reference roads in
    BOTH the island and the main component here -- doing so would bridge
    the two into one connected component via `_build_adjacency`'s
    junction-connection edges, which would itself prevent the island from
    being quarantined in the first place. So the realistic "partial loss"
    case is two independent junctions, not one junction with mixed
    connections."""
    main_roads = []
    for i in range(1, 26):
        succ = str(i + 1) if i < 25 else None
        pred = str(i - 1) if i > 1 else None
        main_roads.append(_road(str(i), successor=succ, predecessor=pred))

    island_roads = [
        _road("101", successor="102"),
        _road("102", predecessor="101"),
    ]
    dangling_junction = _junction("500", [("0", "101", "102")])
    valid_junction = _junction("600", [("0", "1", "2")])

    xodr = _write(
        tmp_path,
        "islands_two_junctions.xodr",
        _wrap(
            "".join(main_roads)
            + "".join(island_roads)
            + dangling_junction
            + valid_junction
        ),
    )
    out_xodr = str(tmp_path / "islands_two_junctions_out.xodr")

    report = quarantine_island_roads(xodr, out_xodr, min_component_roads=20)

    assert set(report["quarantined_road_ids"]) == {"101", "102"}
    assert report["dangling_connections_dropped"] == 1
    assert report["empty_junctions_dropped"] == 1

    out_root = ET.parse(out_xodr).getroot()
    surviving_junctions = out_root.findall("junction")
    assert len(surviving_junctions) == 1
    assert surviving_junctions[0].get("id") == "600"
    remaining_connections = surviving_junctions[0].findall("connection")
    assert len(remaining_connections) == 1
    assert remaining_connections[0].get("incomingRoad") == "1"
    assert remaining_connections[0].get("connectingRoad") == "2"


def test_quarantine_island_roads_no_dangling_connections_when_nothing_quarantined(
    tmp_path: Path,
) -> None:
    """Positive control: when no road is quarantined, no connection may be
    dropped and the dangling-connection counters must be zero, not merely
    absent -- callers rely on these keys always being present."""
    roads = []
    for i in range(1, 26):
        succ = str(i + 1) if i < 25 else None
        pred = str(i - 1) if i > 1 else None
        roads.append(_road(str(i), successor=succ, predecessor=pred))
    junction = _junction("500", [("0", "1", "2")])

    xodr = _write(
        tmp_path, "no_island_junction.xodr", _wrap("".join(roads) + junction)
    )
    out_xodr = str(tmp_path / "no_island_junction_out.xodr")

    report = quarantine_island_roads(xodr, out_xodr, min_component_roads=20)

    assert report["quarantined_road_ids"] == []
    assert report["dangling_connections_dropped"] == 0
    assert report["empty_junctions_dropped"] == 0

    out_root = ET.parse(out_xodr).getroot()
    assert len(out_root.findall("junction")) == 1
    assert len(out_root.findall("junction")[0].findall("connection")) == 1


# ---------------------------------------------------------------------------
# 2. Degenerate lane repair
# ---------------------------------------------------------------------------


def test_repair_degenerate_lanes_repairs_001m_lane_to_floor_width(tmp_path: Path) -> None:
    """RED: a 0.01 m lane (degenerate -- CARLA may reject it or render a
    shard) must be repaired to at least the floor width."""
    xodr = _write(
        tmp_path,
        "degenerate.xodr",
        _wrap(_road("1", lane_widths=[("-1", 0.01)])),
    )
    out_xodr = str(tmp_path / "degenerate_repaired.xodr")

    report = repair_degenerate_lanes(xodr, out_xodr, min_lane_width=0.10)

    assert report["ok"] is True
    assert report["repaired_count"] + report["quarantined_count"] >= 1

    out_root = ET.parse(out_xodr).getroot()
    road = out_root.find("road[@id='1']")
    assert road is not None, "road must be repaired in place, not silently dropped"
    width = road.find(".//lane[@id='-1']/width")
    assert float(width.get("a")) >= 0.10 - 1e-9


def test_repair_degenerate_lanes_leaves_normal_width_untouched(tmp_path: Path) -> None:
    """Positive control: a normal 3.5 m lane must be untouched (value and
    count of modifications)."""
    xodr = _write(
        tmp_path,
        "normal.xodr",
        _wrap(_road("1", lane_widths=[("-1", 3.5)])),
    )
    out_xodr = str(tmp_path / "normal_repaired.xodr")

    report = repair_degenerate_lanes(xodr, out_xodr, min_lane_width=0.10)

    assert report["repaired_count"] == 0
    assert report["quarantined_count"] == 0

    out_root = ET.parse(out_xodr).getroot()
    width = out_root.find(".//road[@id='1']//lane[@id='-1']/width")
    assert float(width.get("a")) == pytest.approx(3.5, abs=1e-9)


def test_repair_degenerate_lanes_handles_non_finite_width_polynomial(tmp_path: Path) -> None:
    """A non-finite (NaN/inf) width polynomial coefficient must also be
    treated as degenerate and repaired/quarantined, not crash the repair."""
    xodr = _write(
        tmp_path,
        "nonfinite.xodr",
        _wrap(_road("1", lane_widths=[("-1", "nan")])),
    )
    out_xodr = str(tmp_path / "nonfinite_repaired.xodr")

    report = repair_degenerate_lanes(xodr, out_xodr, min_lane_width=0.10)

    assert report["ok"] is True
    assert report["repaired_count"] + report["quarantined_count"] >= 1

    out_root = ET.parse(out_xodr).getroot()
    # Whether repaired-in-place or quarantined, no NaN/inf width may remain.
    for width in out_root.findall(".//lane/width"):
        a = float(width.get("a"))
        assert a == a and abs(a) != float("inf")  # not NaN, not inf


def test_repair_degenerate_lanes_report_records_reason(tmp_path: Path) -> None:
    """The repair report must record WHY each lane was touched (auditable)."""
    xodr = _write(
        tmp_path,
        "degenerate2.xodr",
        _wrap(_road("1", lane_widths=[("-1", 0.01)])),
    )
    out_xodr = str(tmp_path / "degenerate2_repaired.xodr")

    report = repair_degenerate_lanes(xodr, out_xodr, min_lane_width=0.10)

    assert report["repaired_count"] == 1 or report["quarantined_count"] == 1
    details = report.get("details", [])
    assert len(details) >= 1
    assert details[0]["road_id"] == "1"
    assert details[0]["lane_id"] == "-1"
    assert "reason" in details[0]


# ---------------------------------------------------------------------------
# 3. Genuine z-seam repair (post-C9)
# ---------------------------------------------------------------------------


def test_repair_true_zseams_negative_control_1m_step_repaired_below_eps(
    tmp_path: Path,
) -> None:
    """Negative control: inject a genuine 1 m z-step at an ordinary
    (non-junction) road-to-road boundary. After repair, the dz measured by
    C9's check_elevation_continuity must be below eps_z."""
    xodr = _write(
        tmp_path,
        "zstep.xodr",
        _wrap(
            _road("1", successor="2", elevation_a=400.0)
            + _road("2", predecessor="1", elevation_a=401.0)
        ),
    )
    out_xodr = str(tmp_path / "zstep_repaired.xodr")

    report = repair_true_zseams(xodr, out_xodr, eps_z=0.5)

    assert report["ok"] is True
    assert report["issues_before"] >= 1
    assert report["issues_after"] == 0

    from ultimate_pipeline.quality.check_elevation_continuity import check_elevation_continuity

    post = check_elevation_continuity(out_xodr, eps_z=0.5)
    assert post["num_issues"] == 0


def test_repair_true_zseams_does_not_flatten_real_slope(tmp_path: Path) -> None:
    """Boundary: repair must NOT flatten genuine terrain slope. A road with a
    nonzero b-coefficient (real internal slope) whose declared endpoints
    already match its neighbor must be left with its slope intact."""
    xodr = _write(
        tmp_path,
        "slope.xodr",
        _wrap(
            _road("1", successor="2", elevation_a=400.0, elevation_b=0.5)  # ends at 405.0
            + _road("2", predecessor="1", elevation_a=405.0)
        ),
    )
    out_xodr = str(tmp_path / "slope_repaired.xodr")

    report = repair_true_zseams(xodr, out_xodr, eps_z=0.5)

    assert report["issues_before"] == 0
    assert report["issues_after"] == 0
    assert report["roads_modified"] == 0

    out_root = ET.parse(out_xodr).getroot()
    elev = out_root.find("road[@id='1']/elevationProfile/elevation")
    assert float(elev.get("b")) == pytest.approx(0.5, abs=1e-9)


def test_repair_true_zseams_positive_control_clean_map_untouched(tmp_path: Path) -> None:
    """Positive control: a map with no z-seams must report zero issues
    before and after, with no roads modified."""
    xodr = _write(
        tmp_path,
        "clean.xodr",
        _wrap(
            _road("1", successor="2", elevation_a=400.0)
            + _road("2", predecessor="1", elevation_a=400.0)
        ),
    )
    out_xodr = str(tmp_path / "clean_repaired.xodr")

    report = repair_true_zseams(xodr, out_xodr, eps_z=0.5)

    assert report["issues_before"] == 0
    assert report["issues_after"] == 0
    assert report["roads_modified"] == 0


def test_repair_true_zseams_ignores_junction_connector_offset(tmp_path: Path) -> None:
    """Boundary: junction-connector lane-offset artifacts (per C9) must NOT
    be treated as genuine z-seams and must not be 'repaired' away."""
    xodr = _write(
        tmp_path,
        "junction.xodr",
        _wrap(
            _road("1", successor="9", elevation_a=400.0)
            + _road("9", predecessor="1", elevation_a=401.2, junction="1")
        ),
    )
    out_xodr = str(tmp_path / "junction_repaired.xodr")

    report = repair_true_zseams(xodr, out_xodr, eps_z=0.5)

    assert report["issues_before"] == 0  # ordinary-road issues only, per C9 split
    assert report["issues_after"] == 0
    assert report["roads_modified"] == 0

    out_root = ET.parse(out_xodr).getroot()
    elev9 = out_root.find("road[@id='9']/elevationProfile/elevation")
    assert float(elev9.get("a")) == pytest.approx(401.2, abs=1e-9)


# ---------------------------------------------------------------------------
# 4. Lane width discontinuity repair (deep-audit follow-up, 2026-09-04)
#
# Wiring check_lane_geometry_continuity into map acceptance (WS-A of the
# deep-audit plan) surfaced a real, previously-invisible defect: road 46620's
# right driving lane steps 3.5m -> 3.0m over a 0.05m laneSection -- an instant
# width change, not a taper. Root-caused to stage_07_lanes.py (present as of
# that pipeline stage's own output, not introduced by a later repair), but
# fixing lane-generation logic used for all 32,267 roads to address a single
# outlier was judged too broad-blast-radius; a targeted, minimally-invasive
# post-generation repair (matching this file's established pattern) is safer.
# ---------------------------------------------------------------------------


def _road_with_two_lane_sections(
    rid: str,
    *,
    length: float,
    boundary_s: float,
    width_before: float,
    width_after: float,
    lane_id: str = "-1",
    lane_type: str = "driving",
    lane_type_after: str | None = None,
) -> str:
    """A road with exactly 2 laneSections split at boundary_s, both carrying
    a single flat-width lane at `lane_id`. `lane_type_after` lets a test
    deliberately create a type mismatch (the same false-positive class
    check_lane_geometry_continuity already excludes)."""
    lane_type_after = lane_type_after or lane_type
    return (
        f'<road id="{rid}" length="{length}" junction="-1">'
        f'<planView><geometry s="0" x="0" y="0" hdg="0" length="{length}"><line/></geometry></planView>'
        f'<elevationProfile><elevation s="0" a="0.0" b="0" c="0" d="0"/></elevationProfile>'
        "<lanes>"
        f'<laneSection s="0">'
        f'<right><lane id="{lane_id}" type="{lane_type}" level="false">'
        f'<width sOffset="0" a="{width_before}" b="0" c="0" d="0"/>'
        "</lane></right>"
        "</laneSection>"
        f'<laneSection s="{boundary_s}">'
        f'<right><lane id="{lane_id}" type="{lane_type_after}" level="false">'
        f'<width sOffset="0" a="{width_after}" b="0" c="0" d="0"/>'
        "</lane></right>"
        "</laneSection>"
        "</lanes>"
        "</road>"
    )


def test_repair_lane_width_discontinuities_fixes_short_leading_section(tmp_path: Path) -> None:
    """Matches the real road-46620 case: a short (0.05m) leading section
    with a width that disagrees with the much-longer trailing section --
    the SHORTER (leading) section must be the one adjusted, since that
    alters the least amount of road."""
    xodr = _write(
        tmp_path,
        "narrowing.xodr",
        _wrap(
            _road_with_two_lane_sections(
                "1", length=214.74, boundary_s=0.05, width_before=3.5, width_after=3.0
            )
        ),
    )
    out_xodr = str(tmp_path / "narrowing_repaired.xodr")

    report = repair_lane_width_discontinuities(xodr, out_xodr, eps=0.10)

    assert report["issues_before"] == 1
    assert report["issues_after"] == 0
    assert report["ok"] is True
    assert report["repaired_count"] == 1
    assert report["roads_modified"] == ["1"]
    assert report["details"][0]["adjusted_section"] == "prev"

    out_root = ET.parse(out_xodr).getroot()
    sections = out_root.find("road[@id='1']/lanes").findall("laneSection")
    first_width = sections[0].find("right/lane/width")
    second_width = sections[1].find("right/lane/width")
    # The short leading section's width now matches the long trailing
    # section's width (3.0), not the other way around.
    assert float(first_width.get("a")) == pytest.approx(3.0, abs=1e-6)
    assert float(second_width.get("a")) == pytest.approx(3.0, abs=1e-6)


def test_repair_lane_width_discontinuities_adjusts_shorter_trailing_section(tmp_path: Path) -> None:
    """When the LATER section is the shorter one, that side must be
    adjusted instead -- always the section that alters less road length."""
    xodr = _write(
        tmp_path,
        "widening.xodr",
        _wrap(
            _road_with_two_lane_sections(
                "1", length=100.0, boundary_s=99.9, width_before=3.0, width_after=3.6
            )
        ),
    )
    out_xodr = str(tmp_path / "widening_repaired.xodr")

    report = repair_lane_width_discontinuities(xodr, out_xodr, eps=0.10)

    assert report["issues_before"] == 1
    assert report["issues_after"] == 0
    assert report["details"][0]["adjusted_section"] == "next"

    out_root = ET.parse(out_xodr).getroot()
    sections = out_root.find("road[@id='1']/lanes").findall("laneSection")
    first_width = sections[0].find("right/lane/width")
    second_width = sections[1].find("right/lane/width")
    assert float(first_width.get("a")) == pytest.approx(3.0, abs=1e-6)
    assert float(second_width.get("a")) == pytest.approx(3.0, abs=1e-6)


def test_repair_lane_width_discontinuities_ignores_lane_type_mismatch(tmp_path: Path) -> None:
    """A sidewalk<->driving transition (the established false-positive
    class, road 46620's ORIGINAL DEEP_QUALITY_SWEEP finding) must not be
    touched -- check_lane_geometry_continuity itself already excludes it,
    and this repair must inherit that exclusion by only acting on issues
    the checker actually reports."""
    xodr = _write(
        tmp_path,
        "type_transition.xodr",
        _wrap(
            _road_with_two_lane_sections(
                "1",
                length=100.0,
                boundary_s=0.05,
                width_before=2.0,
                width_after=3.5,
                lane_id="1",
                lane_type="sidewalk",
                lane_type_after="driving",
            )
        ),
    )
    out_xodr = str(tmp_path / "type_transition_repaired.xodr")

    report = repair_lane_width_discontinuities(xodr, out_xodr, eps=0.10)

    assert report["issues_before"] == 0
    assert report["repaired_count"] == 0
    assert report["roads_modified"] == []

    out_root = ET.parse(out_xodr).getroot()
    sections = out_root.find("road[@id='1']/lanes").findall("laneSection")
    assert float(sections[0].find("right/lane/width").get("a")) == pytest.approx(2.0, abs=1e-6)
    assert float(sections[1].find("right/lane/width").get("a")) == pytest.approx(3.5, abs=1e-6)


def test_repair_lane_width_discontinuities_positive_control_clean_map_untouched(
    tmp_path: Path,
) -> None:
    """A map with no width discontinuity must be reported clean and left
    byte-for-byte unmodified in content."""
    xodr = _write(
        tmp_path,
        "clean.xodr",
        _wrap(
            _road_with_two_lane_sections(
                "1", length=100.0, boundary_s=50.0, width_before=3.5, width_after=3.55
            )
        ),
    )
    out_xodr = str(tmp_path / "clean_out.xodr")

    report = repair_lane_width_discontinuities(xodr, out_xodr, eps=0.10)

    assert report["issues_before"] == 0
    assert report["issues_after"] == 0
    assert report["repaired_count"] == 0
    assert report["roads_modified"] == []

    out_root = ET.parse(out_xodr).getroot()
    sections = out_root.find("road[@id='1']/lanes").findall("laneSection")
    assert float(sections[0].find("right/lane/width").get("a")) == pytest.approx(3.5, abs=1e-6)
    assert float(sections[1].find("right/lane/width").get("a")) == pytest.approx(3.55, abs=1e-6)
