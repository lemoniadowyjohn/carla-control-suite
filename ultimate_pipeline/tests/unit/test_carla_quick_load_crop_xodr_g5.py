# -*- coding: utf-8 -*-
"""
G5 regression tests: OpenDRIVE crop reference integrity.

Covers reference-aware pruning after road/junction crop:
- Junction connections referencing dropped roads are removed.
- Signals referencing dropped roads (via dependency owner) are removed.
- Controllers referencing dropped junctions are removed.
- JunctionGroups referencing cropped junctions are removed.
- Input trees remain unmodified.
- Output is deterministic.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.diagnostics.carla_quick_load import crop_xodr


def _road(rid: str, x: float, y: float, *, junction: str = "-1") -> str:
    return (
        f'<road name="R{rid}" length="10.0" id="{rid}" junction="{junction}">'
        f'<planView><geometry s="0" x="{x}" y="{y}" hdg="0" length="10"><line/></geometry></planView>'
        f'</road>'
    )


def _write_xodr(path: Path, roads_xml: str, junctions_xml: str = "",
                signals_xml: str = "", controllers_xml: str = "",
                junction_groups_xml: str = "") -> None:
    path.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?><OpenDRIVE>'
        f'{roads_xml}{junctions_xml}{signals_xml}{controllers_xml}{junction_groups_xml}'
        f'</OpenDRIVE>',
        encoding="utf-8",
    )


def _ids(path: Path, tag: str) -> set[str]:
    root = ET.parse(path).getroot()
    return {e.get("id") for e in root.findall(tag) if e.get("id")}


def _jgroup_names(path: Path) -> set[str]:
    root = ET.parse(path).getroot()
    return {e.get("name") for e in root.findall("junctionGroup") if e.get("name")}


def _connection_refs(path: Path) -> list[tuple[str, str]]:
    """Return (incomingRoad, connectingRoad) for every connection."""
    root = ET.parse(path).getroot()
    out = []
    for j in root.findall("junction"):
        for c in j.findall("connection"):
            out.append((c.get("incomingRoad"), c.get("connectingRoad")))
    return out


# ---------------------------------------------------------------------------
# Junction connection pruning
# ---------------------------------------------------------------------------

def test_junction_connection_to_dropped_road_is_pruned(tmp_path: Path):
    roads = _road("1", 0, 0, junction="J1") + _road("2", 1000, 0, junction="J1")
    junctions = '<junction id="J1" name="J1"><connection id="0" incomingRoad="1" connectingRoad="2"/></junction>'
    xodr = tmp_path / "in.xodr"
    out = tmp_path / "out.xodr"
    _write_xodr(xodr, roads, junctions)
    crop_xodr(str(xodr), str(out), radius_m=300.0)

    assert _ids(out, "road") == {"1"}
    assert _ids(out, "junction") == {"J1"}
    conns = _connection_refs(out)
    # The connection to road "2" must be pruned; no dangling references remain.
    assert all(ir in {"1"} and cr in {"1"} for ir, cr in conns), conns


# ---------------------------------------------------------------------------
# Signal pruning
# ---------------------------------------------------------------------------

def test_signal_with_dropped_owner_road_is_pruned(tmp_path: Path):
    roads = _road("1", 0, 0, junction="-1") + _road("2", 1000, 0, junction="-1")
    signals = (
        '<signal id="S1" type="traffic_light">'
        '<position s="0" t="0" z="0"/>'
        '<dependency owner="2"/>'
        '</signal>'
    )
    xodr = tmp_path / "in.xodr"
    out = tmp_path / "out.xodr"
    _write_xodr(xodr, roads, signals_xml=signals)
    crop_xodr(str(xodr), str(out), radius_m=300.0)

    assert _ids(out, "road") == {"1"}
    assert _ids(out, "signal") == set(), "signal referencing dropped road must be pruned"


def test_signal_with_kept_owner_road_is_retained(tmp_path: Path):
    roads = _road("1", 0, 0, junction="-1")
    signals = (
        '<signal id="S1" type="traffic_light">'
        '<position s="0" t="0" z="0"/>'
        '<dependency owner="1"/>'
        '</signal>'
    )
    xodr = tmp_path / "in.xodr"
    out = tmp_path / "out.xodr"
    _write_xodr(xodr, roads, signals_xml=signals)
    crop_xodr(str(xodr), str(out), radius_m=300.0)

    assert _ids(out, "road") == {"1"}
    assert _ids(out, "signal") == {"S1"}, "signal referencing kept road must be retained"


# ---------------------------------------------------------------------------
# Controller pruning
# ---------------------------------------------------------------------------

def test_controller_with_dropped_junction_is_pruned(tmp_path: Path):
    roads = _road("1", 0, 0, junction="-1") + _road("2", 1000, 0, junction="J1")
    junctions = '<junction id="J1" name="J1"/>'
    controllers = '<controller id="C1" type="traffic_light"><controlled type="junction" id="J1"/></controller>'
    xodr = tmp_path / "in.xodr"
    out = tmp_path / "out.xodr"
    _write_xodr(xodr, roads, junctions, controllers_xml=controllers)
    crop_xodr(str(xodr), str(out), radius_m=300.0)

    assert _ids(out, "road") == {"1"}
    assert _ids(out, "junction") == set(), "unreferenced junction must be dropped"
    assert _ids(out, "controller") == set(), "controller referencing dropped junction must be pruned"


def test_controller_with_kept_junction_is_retained(tmp_path: Path):
    roads = _road("1", 0, 0, junction="J1")
    junctions = '<junction id="J1" name="J1"/>'
    controllers = '<controller id="C1" type="traffic_light"><controlled type="junction" id="J1"/></controller>'
    xodr = tmp_path / "in.xodr"
    out = tmp_path / "out.xodr"
    _write_xodr(xodr, roads, junctions, controllers_xml=controllers)
    crop_xodr(str(xodr), str(out), radius_m=300.0)

    assert _ids(out, "road") == {"1"}
    assert _ids(out, "junction") == {"J1"}
    assert _ids(out, "controller") == {"C1"}


# ---------------------------------------------------------------------------
# JunctionGroup pruning
# ---------------------------------------------------------------------------

def test_junction_group_with_dropped_reference_is_pruned(tmp_path: Path):
    roads = _road("1", 0, 0, junction="-1") + _road("2", 1000, 0, junction="J1")
    junctions = '<junction id="J1" name="J1"/>'
    jgroups = (
        '<junctionGroup name="G1">'
        '<junctionReference id="J1"/>'
        '<junctionReference id="J999"/>'
        '</junctionGroup>'
    )
    xodr = tmp_path / "in.xodr"
    out = tmp_path / "out.xodr"
    _write_xodr(xodr, roads, junctions, junction_groups_xml=jgroups)
    crop_xodr(str(xodr), str(out), radius_m=300.0)

    assert _ids(out, "road") == {"1"}
    assert _ids(out, "junction") == set(), "unreferenced junction must be dropped"
    assert _jgroup_names(out) == set(), "junctionGroup referencing dropped junction must be pruned"


def test_junction_group_with_kept_reference_is_retained(tmp_path: Path):
    roads = _road("1", 0, 0, junction="J1")
    junctions = '<junction id="J1" name="J1"/>'
    jgroups = '<junctionGroup name="G1"><junctionReference id="J1"/></junctionGroup>'
    xodr = tmp_path / "in.xodr"
    out = tmp_path / "out.xodr"
    _write_xodr(xodr, roads, junctions, junction_groups_xml=jgroups)
    crop_xodr(str(xodr), str(out), radius_m=300.0)

    assert _ids(out, "road") == {"1"}
    assert _ids(out, "junction") == {"J1"}
    assert _jgroup_names(out) == {"G1"}, "junctionGroup referencing kept junction must be retained"


# ---------------------------------------------------------------------------
# Input tree unmodified
# ---------------------------------------------------------------------------

def test_input_tree_unmodified_after_crop(tmp_path: Path):
    roads = _road("1", 0, 0, junction="J1") + _road("2", 1000, 0, junction="J1")
    junctions = '<junction id="J1" name="J1"><connection id="0" incomingRoad="1" connectingRoad="2"/></junction>'
    xodr = tmp_path / "in.xodr"
    out = tmp_path / "out.xodr"
    _write_xodr(xodr, roads, junctions)
    original = xodr.read_text(encoding="utf-8")

    crop_xodr(str(xodr), str(out), radius_m=300.0)

    assert xodr.read_text(encoding="utf-8") == original, "input XODR must not be modified"


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

def test_crop_output_is_deterministic(tmp_path: Path):
    roads = _road("1", 0, 0, junction="J1") + _road("2", 1000, 0, junction="J1")
    junctions = '<junction id="J1" name="J1"><connection id="0" incomingRoad="1" connectingRoad="2"/></junction>'
    xodr = tmp_path / "in.xodr"
    out1 = tmp_path / "out1.xodr"
    out2 = tmp_path / "out2.xodr"
    _write_xodr(xodr, roads, junctions)

    crop_xodr(str(xodr), str(out1), radius_m=300.0)
    crop_xodr(str(xodr), str(out2), radius_m=300.0)

    assert out1.read_text(encoding="utf-8") == out2.read_text(encoding="utf-8"), "output must be deterministic"
