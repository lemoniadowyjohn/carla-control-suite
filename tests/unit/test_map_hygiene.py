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
