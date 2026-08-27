"""ultimate_pipeline/geometry/quarantine_bad_roads.py -- deletes roads from the XODR
outright based on thresholded continuity/geometry metrics. A scoring or selection bug here
would silently remove the WRONG roads from a real map. Confirmed as the live module (imported
by stage_06_links.py and thesis_protocol_postprocess.py); a same-named but materially
different ultimate_pipeline/quality/quarantine_bad_roads.py exists with zero importers anywhere
in the repo (dead code, left untouched here). Found via the orphaned-.pyc sweep -- an orphaned
tests/unit/test_quarantine_bad_roads.py .pyc existed with no matching .py source.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.geometry.quarantine_bad_roads import (
    DEFAULT_THRESHOLDS,
    _angle_diff_rad,
    _collect_geometry_metrics,
    _parse_continuity_report,
    _score_and_reasons,
    quarantine_bad_roads,
    write_quarantine_report,
)


def _road_with_geometries(rid, geoms):
    # geoms: list of (hdg_deg, curvature) tuples, one planView <geometry> per entry
    road = ET.Element("road", id=rid, length="10.0", junction="-1")
    planview = ET.SubElement(road, "planView")
    for i, (hdg_deg, curvature) in enumerate(geoms):
        import math
        geom = ET.SubElement(
            planview, "geometry", s=str(float(i)), x="0", y="0",
            hdg=str(math.radians(hdg_deg)), length="1.0",
        )
        if curvature:
            ET.SubElement(geom, "arc", curvature=str(curvature))
        else:
            ET.SubElement(geom, "line")
    return road


def _write_xodr(path: Path, roads) -> None:
    root = ET.Element("OpenDRIVE")
    for r in roads:
        root.append(r)
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# _angle_diff_rad
# ---------------------------------------------------------------------------

def test_angle_diff_rad_wraps_around_pi():
    import math
    # 350 deg vs 10 deg is a 20 deg difference, not 340
    diff = _angle_diff_rad(math.radians(350), math.radians(10))
    assert abs(math.degrees(diff) - 20.0) < 1e-6


def test_angle_diff_rad_zero_for_identical_headings():
    assert _angle_diff_rad(1.234, 1.234) == 0.0


# ---------------------------------------------------------------------------
# _parse_continuity_report
# ---------------------------------------------------------------------------

def test_parse_continuity_report_none_returns_empty():
    assert _parse_continuity_report(None) == {}


def test_parse_continuity_report_extracts_max_dxy_per_road():
    report = {
        "issues": [
            {"from_road": "1", "to_road": "2", "dxy": 0.5, "dhdg": 2.0},
            {"from_road": "1", "to_road": "3", "dxy": 3.0, "dhdg": 1.0},
        ]
    }
    scores = _parse_continuity_report(report)
    # road "1" appears in both issues (as from_road) -> takes the max dxy across them
    assert scores["1"]["continuity_dxy_max_m"] == 3.0
    assert scores["1"]["continuity_issue_count"] == 2
    assert scores["2"]["continuity_dxy_max_m"] == 0.5
    assert scores["3"]["continuity_dxy_max_m"] == 3.0


def test_parse_continuity_report_malformed_issue_entries_skipped():
    report = {"issues": ["not a dict", {"from_road": "1", "dxy": 1.0}]}
    scores = _parse_continuity_report(report)
    assert "1" in scores
    assert len(scores) == 1


# ---------------------------------------------------------------------------
# _collect_geometry_metrics
# ---------------------------------------------------------------------------

def test_collect_geometry_metrics_heading_jump():
    road = _road_with_geometries("1", [(0.0, 0.0), (45.0, 0.0)])
    root = ET.Element("OpenDRIVE")
    root.append(road)
    metrics = _collect_geometry_metrics(root)
    assert abs(metrics["1"]["heading_jump_max_deg"] - 45.0) < 1e-6


def test_collect_geometry_metrics_curvature_abs_and_jump():
    road = _road_with_geometries("1", [(0.0, 0.1), (0.0, 0.4)])
    root = ET.Element("OpenDRIVE")
    root.append(road)
    metrics = _collect_geometry_metrics(root)
    assert abs(metrics["1"]["curvature_abs_max"] - 0.4) < 1e-9
    assert abs(metrics["1"]["curvature_jump_max"] - 0.3) < 1e-9


def test_collect_geometry_metrics_road_without_planview_skipped():
    road = ET.Element("road", id="1", length="10.0")
    root = ET.Element("OpenDRIVE")
    root.append(road)
    metrics = _collect_geometry_metrics(root)
    assert metrics == {}


def test_collect_geometry_metrics_road_without_geometry_children_skipped():
    road = ET.Element("road", id="1", length="10.0")
    ET.SubElement(road, "planView")  # present but empty
    root = ET.Element("OpenDRIVE")
    root.append(road)
    metrics = _collect_geometry_metrics(root)
    assert metrics == {}


# ---------------------------------------------------------------------------
# _score_and_reasons
# ---------------------------------------------------------------------------

def test_score_and_reasons_below_threshold_no_flag():
    entry = {"heading_jump_max_deg": 5.0}
    score, reasons = _score_and_reasons(entry, DEFAULT_THRESHOLDS)
    assert score == 0.0
    assert reasons == []


def test_score_and_reasons_above_threshold_flags_and_scores():
    # heading_jump_max_m threshold is 30.0 deg; 60 deg is exactly 2x over
    entry = {"heading_jump_max_deg": 60.0}
    score, reasons = _score_and_reasons(entry, DEFAULT_THRESHOLDS)
    assert reasons == ["heading_jump"]
    assert abs(score - 2.0) < 1e-9


def test_score_and_reasons_multiple_violations_take_max_score():
    entry = {
        "heading_jump_max_deg": 60.0,  # threshold 30 -> ratio 2.0
        "curvature_abs_max": 5.0,      # threshold 0.5 -> ratio 10.0 (dominates)
    }
    score, reasons = _score_and_reasons(entry, DEFAULT_THRESHOLDS)
    assert set(reasons) == {"heading_jump", "curvature_abs"}
    assert abs(score - 10.0) < 1e-9


def test_score_and_reasons_zero_threshold_disables_check():
    entry = {"heading_jump_max_deg": 999.0}
    thresholds = dict(DEFAULT_THRESHOLDS)
    thresholds["heading_jump_max_deg"] = 0.0
    score, reasons = _score_and_reasons(entry, thresholds)
    assert reasons == []
    assert score == 0.0


# ---------------------------------------------------------------------------
# quarantine_bad_roads -- end-to-end
# ---------------------------------------------------------------------------

def test_quarantine_removes_the_single_worst_offender_by_default(tmp_path: Path):
    good = _road_with_geometries("1", [(0.0, 0.0), (5.0, 0.0)])  # under every threshold
    bad = _road_with_geometries("2", [(0.0, 0.0), (90.0, 0.0)])  # 90deg heading jump >> 30 max
    xin = tmp_path / "in.xodr"
    xout = tmp_path / "out.xodr"
    _write_xodr(xin, [good, bad])

    report = quarantine_bad_roads(str(xin), str(xout))

    assert report["ok"] is True
    assert report["road_ids_quarantined"] == ["2"]
    assert report["count_removed"] == 1
    out_root = ET.parse(str(xout)).getroot()
    remaining_ids = {r.get("id") for r in out_root.findall("road")}
    assert remaining_ids == {"1"}


def test_quarantine_no_candidates_removes_nothing(tmp_path: Path):
    good1 = _road_with_geometries("1", [(0.0, 0.0), (2.0, 0.0)])
    good2 = _road_with_geometries("2", [(0.0, 0.0), (3.0, 0.0)])
    xin = tmp_path / "in.xodr"
    xout = tmp_path / "out.xodr"
    _write_xodr(xin, [good1, good2])

    report = quarantine_bad_roads(str(xin), str(xout))

    assert report["status"] == "no_roads_removed"
    assert report["count_removed"] == 0
    out_root = ET.parse(str(xout)).getroot()
    assert {r.get("id") for r in out_root.findall("road")} == {"1", "2"}


def test_quarantine_worst_offender_selected_by_score_not_just_flagged_order(tmp_path: Path):
    # Both roads violate a threshold, but road "2" is a much worse violator (higher score) --
    # with default max_fraction=0.01 on 3 roads, floor(3*0.01)=0 -> the "at least one" rule
    # kicks in, so exactly the single WORST road must be removed, not road "1".
    ok = _road_with_geometries("1", [(0.0, 0.0), (1.0, 0.0)])
    mild = _road_with_geometries("2", [(0.0, 0.0), (35.0, 0.0)])   # just over 30 threshold
    severe = _road_with_geometries("3", [(0.0, 0.0), (150.0, 0.0)])  # far over
    xin = tmp_path / "in.xodr"
    xout = tmp_path / "out.xodr"
    _write_xodr(xin, [ok, mild, severe])

    report = quarantine_bad_roads(str(xin), str(xout))

    assert report["count_removed"] == 1
    assert report["road_ids_quarantined"] == ["3"]


def test_quarantine_max_fraction_bounds_removal_count(tmp_path: Path):
    # 10 roads, all violating heading_jump, max_fraction=0.2 -> floor(10*0.2)=2 removed
    roads = []
    for i in range(10):
        # increasing severity so the ranking is deterministic
        roads.append(_road_with_geometries(str(i), [(0.0, 0.0), (35.0 + i, 0.0)]))
    xin = tmp_path / "in.xodr"
    xout = tmp_path / "out.xodr"
    _write_xodr(xin, roads)

    report = quarantine_bad_roads(str(xin), str(xout), max_fraction=0.2)

    assert report["count_removed"] == 2
    # the two most severe (highest heading jump) roads are ids "9" and "8"
    assert set(report["road_ids_quarantined"]) == {"8", "9"}


def test_quarantine_continuity_report_feeds_into_scoring(tmp_path: Path):
    ok = _road_with_geometries("1", [(0.0, 0.0), (1.0, 0.0)])
    other = _road_with_geometries("2", [(0.0, 0.0), (1.0, 0.0)])  # geometry alone is fine
    xin = tmp_path / "in.xodr"
    xout = tmp_path / "out.xodr"
    _write_xodr(xin, [ok, other])
    # "99" is not a real road in this map -- _parse_continuity_report flags BOTH from_road
    # and to_road symmetrically, so naming a non-existent counterpart keeps only "2" flagged
    # (naming "1" as the counterpart would tie both roads' scores and the road_id tiebreak
    # would remove "1" instead, since sort key is (-score, road_id) ascending).
    continuity_report = {
        "issues": [{"from_road": "2", "to_road": "99", "dxy": 50.0, "dhdg": 0.0}],
    }

    report = quarantine_bad_roads(str(xin), str(xout), continuity_report=continuity_report)

    # road "2" is flagged purely from the continuity report (dxy=50 >> 1.0 threshold),
    # despite having no problematic geometry of its own.
    assert report["road_ids_quarantined"] == ["2"]


def test_quarantine_records_input_and_output_sha256(tmp_path: Path):
    bad = _road_with_geometries("1", [(0.0, 0.0), (90.0, 0.0)])
    xin = tmp_path / "in.xodr"
    xout = tmp_path / "out.xodr"
    _write_xodr(xin, [bad])

    report = quarantine_bad_roads(str(xin), str(xout))

    assert len(report["input_xodr_sha256"]) == 64
    assert len(report["output_xodr_sha256"]) == 64
    assert report["input_xodr_sha256"] != report["output_xodr_sha256"]  # output had a road removed


def test_write_quarantine_report_creates_parent_dirs_and_valid_json(tmp_path: Path):
    out_path = tmp_path / "nested" / "dir" / "report.json"
    write_quarantine_report(str(out_path), {"ok": True, "count_removed": 0})
    assert out_path.is_file()
    assert json.loads(out_path.read_text(encoding="utf-8"))["ok"] is True
