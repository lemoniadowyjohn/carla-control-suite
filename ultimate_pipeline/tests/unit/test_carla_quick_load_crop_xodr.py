# ultimate_pipeline/diagnostics/carla_quick_load.py::crop_xodr() -- zero
# prior test coverage. Live: called from stage_02_topology_semantics.py
# and stage_05_geometry.py to produce a fast, radius-cropped preview XODR
# for visualization (the real full map is untouched for the pipeline
# proper -- this is a QA/preview-only artifact, not a submitted map).
#
# Real bug found: the orphaned-junction cleanup did
# `root.find("junctions")` (a wrapper element) before iterating
# `.findall("junction")` on it. This codebase's XODR convention (and
# standard OpenDRIVE) always puts <junction> elements as direct children
# of <OpenDRIVE>, never wrapped in a <junctions> container -- confirmed
# by grep: no other file in the repo ever looks for "junctions" (plural).
# root.find("junctions") therefore always returned None, silently
# skipping the cleanup for every cropped preview ever produced. The
# function's own comment says this is "safe even if missed" (CARLA
# tolerates unused junction elements), so this was never a correctness
# bug for the preview's loadability -- just dead code that never did what
# it was written to do. Fixed: search root.findall("junction") directly.
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.diagnostics.carla_quick_load import crop_xodr


def _road(rid: str, x: float, y: float, *, junction: str = "-1") -> str:
    return (
        f'<road name="R{rid}" length="10.0" id="{rid}" junction="{junction}">'
        f'<planView><geometry s="0" x="{x}" y="{y}" hdg="0" length="10"><line/></geometry></planView>'
        f'</road>'
    )


def _write_xodr(path: Path, roads_xml: str, junctions_xml: str = "") -> None:
    path.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><OpenDRIVE>{roads_xml}{junctions_xml}</OpenDRIVE>',
        encoding="utf-8",
    )


def _road_ids(xodr_path: Path) -> set[str]:
    root = ET.parse(xodr_path).getroot()
    return {r.get("id") for r in root.findall("road")}


def _junction_ids(xodr_path: Path) -> set[str]:
    root = ET.parse(xodr_path).getroot()
    return {j.get("id") for j in root.findall("junction")}


def test_keeps_roads_within_radius_drops_roads_outside(tmp_path: Path):
    roads = _road("1", 0, 0) + _road("2", 100, 0) + _road("3", 1000, 0)
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads)
    out = tmp_path / "out.xodr"

    crop_xodr(str(xodr), str(out), radius_m=300.0)

    assert _road_ids(out) == {"1", "2"}


def test_keeps_road_if_any_geometry_point_within_radius(tmp_path: Path):
    # Two-geometry road: first far outside, second within radius -> kept
    # ("intentionally conservative" per docstring).
    road = (
        '<road name="R9" length="20.0" id="9" junction="-1">'
        '<planView>'
        '<geometry s="0" x="1000" y="0" hdg="0" length="10"><line/></geometry>'
        '<geometry s="10" x="50" y="0" hdg="0" length="10"><line/></geometry>'
        '</planView>'
        '</road>'
    )
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, road)
    out = tmp_path / "out.xodr"

    crop_xodr(str(xodr), str(out), radius_m=300.0)

    assert _road_ids(out) == {"9"}


def test_nonfinite_coords_do_not_count_as_within_radius(tmp_path: Path):
    road = (
        '<road name="R9" length="10.0" id="9" junction="-1">'
        '<planView><geometry s="0" x="nan" y="nan" hdg="0" length="10"><line/></geometry></planView>'
        '</road>'
    )
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, road)
    out = tmp_path / "out.xodr"

    crop_xodr(str(xodr), str(out), radius_m=300.0)

    assert _road_ids(out) == set()


def test_orphaned_junction_removed_when_no_referencing_road_survives(tmp_path: Path):
    roads = _road("1", 0, 0) + _road("2", 1000, 0, junction="100")
    junction = '<junction id="100" name="J"><connection id="0" incomingRoad="1" connectingRoad="2"/></junction>'
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads, junction)
    out = tmp_path / "out.xodr"

    crop_xodr(str(xodr), str(out), radius_m=300.0)

    assert _road_ids(out) == {"1"}
    assert _junction_ids(out) == set()


def test_referenced_junction_kept_when_a_road_still_references_it(tmp_path: Path):
    roads = _road("1", 0, 0, junction="100") + _road("2", 1000, 0)
    junction = '<junction id="100" name="J"><connection id="0" incomingRoad="1" connectingRoad="1"/></junction>'
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads, junction)
    out = tmp_path / "out.xodr"

    crop_xodr(str(xodr), str(out), radius_m=300.0)

    assert _road_ids(out) == {"1"}
    assert _junction_ids(out) == {"100"}


def test_output_dir_created_if_missing(tmp_path: Path):
    roads = _road("1", 0, 0)
    xodr = tmp_path / "in.xodr"
    _write_xodr(xodr, roads)
    out = tmp_path / "nested" / "dir" / "out.xodr"

    crop_xodr(str(xodr), str(out), radius_m=300.0)

    assert out.is_file()
