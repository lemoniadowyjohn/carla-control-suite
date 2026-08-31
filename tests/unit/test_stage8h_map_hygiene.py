from __future__ import annotations

"""C10 wiring — `_step8h_map_hygiene` must run inside the pipeline and
produce auditable, reversible repairs on the final XODR:

    out/08h1_island_quarantined.xodr      (islands removed, reported)
    out/08h2_degenerate_lanes_repaired.xodr (floor width repair)
    out/08h3_zseams_repaired.xodr          (genuine z-seam chaining)
    out/map_hygiene_report.json

Behavioral contract tested here:
1. island quarantine removes only the disconnected small component,
2. degenerate driving lanes are floored to the minimum width,
3. the suspicious-fraction safety valve keeps the input when quarantine
   would remove too much of the map (broken connectivity graph),
4. ENABLE_MAP_HYGIENE=false returns the input untouched.

All repairs are offline (pure XML); no CARLA server is required.
"""

import xml.etree.ElementTree as ET
from unittest import mock

import pytest

from ultimate_pipeline.config.settings import Settings
from ultimate_pipeline.main_pipeline import MainPipeline


def _road(rid: str, length: float = 100.0, lane_width: float = 3.5,
          z: float = 5.0, succ: str | None = None, pred: str | None = None,
          junction: str = "-1"):
    road = ET.Element("road", id=rid, length=f"{length}", junction=junction)
    link = ET.SubElement(road, "link")
    if pred is not None:
        ET.SubElement(link, "predecessor", elementType="road",
                      elementId=pred, contactPoint="start")
    if succ is not None:
        ET.SubElement(link, "successor", elementType="road",
                      elementId=succ, contactPoint="start")
    elev = ET.SubElement(road, "elevationProfile")
    ET.SubElement(elev, "elevation", s="0.000000", a=f"{z:.6f}",
                  b="0.000000", c="0.000000", d="0.000000")
    lanes = ET.SubElement(road, "lanes")
    ls = ET.SubElement(lanes, "laneSection", s="0.000000")
    right = ET.SubElement(ls, "right")
    lane = ET.SubElement(right, "lane", id="-1", type="driving", level="false")
    ET.SubElement(lane, "width", sOffset="0.000000", a=f"{lane_width:.6f}",
                  b="0.000000", c="0.000000", d="0.000000")
    return road


def _build_xodr(path, *, with_island: bool = True, degenerate_road: str | None = "2",
                n_main: int = 25):
    root = ET.Element("OpenDRIVE")
    ET.SubElement(root, "header", revMajor="1", revMinor="4")
    roads = [_road(str(i), succ=str(i + 1) if i + 1 < n_main else None,
                   pred=str(i - 1) if i > 0 else None)
             for i in range(n_main)]
    if degenerate_road is not None and degenerate_road.isdigit() and int(degenerate_road) < n_main:
        # Replace the driving lane width with a degenerate 1 cm lane.
        for w in roads[int(degenerate_road)].findall(".//width"):
            w.set("a", "0.010000")
    if with_island:
        for rid in ("100", "101", "102"):
            roads.append(_road(rid))
    for r in roads:
        root.append(r)
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)


def _make_pipeline(tmp_path, *, enable: bool = True):
    settings = Settings()
    settings.ENABLE_MAP_HYGIENE = enable
    mp = MainPipeline(settings=settings)
    mp.out_dir = str(tmp_path / "out")
    return mp


def _road_ids(xodr_path) -> set:
    root = ET.parse(str(xodr_path)).getroot()
    return {r.get("id", "") for r in root.findall("road")}


def test_hygiene_removes_islands_and_floors_degenerate_lanes(tmp_path):
    src = tmp_path / "final.xodr"
    _build_xodr(src)
    mp = _make_pipeline(tmp_path)

    out = mp._step8h_map_hygiene(str(src))

    assert out.endswith("08h3_zseams_repaired.xodr"), out
    final_ids = _road_ids(out)
    assert "100" not in final_ids and "101" not in final_ids and "102" not in final_ids
    for i in range(25):
        assert str(i) in final_ids, f"main road {i} must survive island quarantine"

    report = mp.map_hygiene_report
    assert report["stages"]["island_quarantine"]["action"] == "applied"
    assert report["stages"]["island_quarantine"]["count"] == 3
    assert report["stages"]["degenerate_lanes"]["repaired_count"] == 1

    # Degenerate lane floored to >= 0.10 m on the final artifact.
    root = ET.parse(out).getroot()
    min_w = min(
        float(w.get("a"))
        for road in root.findall("road")
        if road.get("id") == "2"
        for w in road.findall(".//width")
    )
    assert min_w >= 0.10

    # Intermediate artifacts + combined report exist for auditability.
    for name in ("08h1_island_quarantined.xodr",
                 "08h2_degenerate_lanes_repaired.xodr",
                 "08h3_zseams_repaired.xodr",
                 "map_hygiene_report.json"):
        assert (tmp_path / "out" / name).is_file(), name


def test_hygiene_suspicious_fraction_safety_valve(tmp_path):
    """If quarantine would remove >25% of the map (a broken connectivity
    graph rather than real islands), the stage keeps the input and records
    the skip reason."""
    src = tmp_path / "final.xodr"
    _build_xodr(src, n_main=10, with_island=False)  # single 10-road component < 20
    mp = _make_pipeline(tmp_path)

    out = mp._step8h_map_hygiene(str(src))

    report = mp.map_hygiene_report
    island = report["stages"]["island_quarantine"]
    assert island["action"] == "skipped_suspicious_fraction"
    assert "skipped_reason" in island
    # Downstream stages still ran on the untouched input artifact.
    assert _road_ids(out) == {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"}


def test_hygiene_disabled_returns_input_untouched(tmp_path):
    src = tmp_path / "final.xodr"
    _build_xodr(src)
    mp = _make_pipeline(tmp_path, enable=False)

    out = mp._step8h_map_hygiene(str(src))

    assert out == str(src)
    assert not (tmp_path / "out").exists() or not (tmp_path / "out" / "map_hygiene_report.json").exists()


def test_hygiene_combined_ok_reflects_a_failed_sub_stage(tmp_path):
    """map_hygiene_report.json's top-level "ok" must reflect whether every
    sub-stage actually succeeded, not be hardcoded True regardless.
    repair_true_zseams() has a real, meaningful ok=(issues_after==0)
    signal (its repair loop can legitimately give up early without
    resolving every seam) -- the combined report must not silently
    discard that."""
    src = tmp_path / "final.xodr"
    _build_xodr(src, with_island=False, degenerate_road=None)
    mp = _make_pipeline(tmp_path)

    failing_zseam_report = {
        "ok": False,
        "eps_z": 0.05,
        "issues_before": 3,
        "issues_after": 2,
        "roads_modified": 1,
        "roads_modified_ids": ["0"],
        "input_xodr": "x",
        "output_xodr": "y",
    }
    with mock.patch(
        "ultimate_pipeline.quality.map_hygiene.repair_true_zseams",
        return_value=failing_zseam_report,
    ):
        mp._step8h_map_hygiene(str(src))

    report = mp.map_hygiene_report
    assert report["stages"]["true_zseams"]["ok"] is False
    assert report["ok"] is False, (
        "a failed z-seam repair must flip the combined report's ok field, "
        "not be silently discarded behind a hardcoded True"
    )


def test_hygiene_is_idempotent_on_clean_map(tmp_path):
    """A clean map (no islands, no degenerate lanes, no z-seams) passes
    through with zero reported changes."""
    src = tmp_path / "final.xodr"
    _build_xodr(src, with_island=False, degenerate_road=None)
    mp = _make_pipeline(tmp_path)

    out = mp._step8h_map_hygiene(str(src))
    report = mp.map_hygiene_report

    assert report["stages"]["island_quarantine"]["count"] == 0
    assert report["stages"]["degenerate_lanes"]["repaired_count"] == 0
    assert report["stages"]["true_zseams"]["issues_after"] == 0
    assert _road_ids(out) == {str(i) for i in range(25)}
