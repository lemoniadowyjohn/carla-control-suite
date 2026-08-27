"""ultimate_pipeline/geometry/mesh_continuity_repairer.py -- ENABLE_CURVATURE_SMOOTHING audit.

Found via a systematic ENABLE_* flag audit for the "reads as enabled but never wired" bug
class that has repeatedly surfaced this session (RealismModule street furniture, crosswalks).
MeshContinuityRepairer.__init__ reads ENABLE_CURVATURE_SMOOTHING into self.enable_curv_smooth
(mesh_continuity_repairer.py:47), but unlike ENABLE_GAP_INTERPOLATION/ENABLE_HEADING_DAMPING
(both actually checked in moderate_fix(), lines 246/253), self.enable_curv_smooth is never
referenced anywhere else in the file -- setting the flag True or False has zero behavioral
effect, and no curvature-smoothing logic exists anywhere in this module. This is a LIVE, core
pipeline stage (invoked from stage_06_links.py 3x and main_pipeline.py), unlike a disabled-by-
default prototype.

Per this session's established caution around geometry mutations (the ENABLE_UNSAFE_HEADING_
ONLY_SMOOTHING experiment demonstrated that "obvious" smoothing fixes can silently make a map
measurably worse), implementing new curvature-smoothing logic here is out of scope -- that
would be a feature addition requiring explicit user authorization, not a bug fix. The narrow,
safe fix applied instead: make the gap transparent, matching the pattern already used by
LaneGNNRefiner's stub (which prints a message when its flag is set but the feature is a stub)
rather than silently doing nothing.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.geometry.mesh_continuity_repairer import MeshContinuityRepairer


def _write_minimal_xodr(path: Path) -> None:
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length="10.0")
    plan = ET.SubElement(road, "planView")
    ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="10.0")
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)


def test_curvature_smoothing_flag_true_warns_that_it_has_no_effect(tmp_path, monkeypatch, capsys):
    from ultimate_pipeline.config.settings import SETTINGS
    monkeypatch.setattr(SETTINGS, "ENABLE_CURVATURE_SMOOTHING", True, raising=False)
    xodr = tmp_path / "map.xodr"
    _write_minimal_xodr(xodr)

    MeshContinuityRepairer(str(xodr))

    out = capsys.readouterr().out
    assert "curvature" in out.lower()
    assert "not implemented" in out.lower() or "no effect" in out.lower() or "no-op" in out.lower()


def test_curvature_smoothing_flag_false_no_warning(tmp_path, monkeypatch, capsys):
    from ultimate_pipeline.config.settings import SETTINGS
    monkeypatch.setattr(SETTINGS, "ENABLE_CURVATURE_SMOOTHING", False, raising=False)
    xodr = tmp_path / "map.xodr"
    _write_minimal_xodr(xodr)

    MeshContinuityRepairer(str(xodr))

    out = capsys.readouterr().out
    assert "curvature" not in out.lower()


def test_curvature_smoothing_flag_has_no_effect_on_moderate_fix_output(tmp_path, monkeypatch):
    # Documents the actual defect: the flag genuinely changes nothing about repair behavior,
    # regardless of value -- moderate_fix's gap/heading fixes are controlled by two OTHER
    # flags (ENABLE_GAP_INTERPOLATION, ENABLE_HEADING_DAMPING) that ARE correctly wired.
    from ultimate_pipeline.config.settings import SETTINGS
    monkeypatch.setattr(SETTINGS, "CONTINUITY_MODE", "moderate", raising=False)
    monkeypatch.setattr(SETTINGS, "STRICT_PASS_THROUGH", False, raising=False)

    def _build_road_with_heading_jump():
        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="1", length="20.0")
        plan = ET.SubElement(road, "planView")
        ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="10.0")
        ET.SubElement(plan, "geometry", s="10", x="10", y="0", hdg="0.05", length="10.0")
        return root

    xodr_true = tmp_path / "true.xodr"
    xodr_false = tmp_path / "false.xodr"
    ET.ElementTree(_build_road_with_heading_jump()).write(str(xodr_true), encoding="utf-8")
    ET.ElementTree(_build_road_with_heading_jump()).write(str(xodr_false), encoding="utf-8")

    monkeypatch.setattr(SETTINGS, "ENABLE_CURVATURE_SMOOTHING", True, raising=False)
    r_true = MeshContinuityRepairer(str(xodr_true))
    r_true.process()

    monkeypatch.setattr(SETTINGS, "ENABLE_CURVATURE_SMOOTHING", False, raising=False)
    r_false = MeshContinuityRepairer(str(xodr_false))
    r_false.process()

    hdg_true = [g.get("hdg") for g in r_true.root.findall(".//geometry")]
    hdg_false = [g.get("hdg") for g in r_false.root.findall(".//geometry")]
    assert hdg_true == hdg_false  # flag value made no difference whatsoever
