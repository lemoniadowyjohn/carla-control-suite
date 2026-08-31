from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from ultimate_pipeline.geometry.planview_smoother import PlanViewSmoother
from ultimate_pipeline.pipeline_stages import stage_06_links


def _write_xodr(path: Path, roads: str, junctions: str = "") -> None:
    path.write_text(
        f"""<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <header revMajor="1" revMinor="4" name="stage6_fixture"/>
{roads}
{junctions}
</OpenDRIVE>
""",
        encoding="utf-8",
    )


def _road_with_planview(road_id: str, planview: str, extra: str = "") -> str:
    return f"""
  <road name="r{road_id}" length="20" id="{road_id}" junction="-1">
    <planView>
{planview}
    </planView>
{extra}
  </road>
"""


FIXTURES = {
    "line_followed_by_arc": _road_with_planview(
        "1",
        """
      <geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>
      <geometry s="10" x="10" y="0" hdg="0" length="10"><arc curvature="0.1"/></geometry>
""",
    ),
    "arc_followed_by_line": _road_with_planview(
        "2",
        """
      <geometry s="0" x="0" y="0" hdg="0" length="10"><arc curvature="0.1"/></geometry>
      <geometry s="10" x="8.414709848" y="4.596976941" hdg="1" length="10"><line/></geometry>
""",
    ),
    "short_line_between_two_arcs": _road_with_planview(
        "3",
        """
      <geometry s="0" x="0" y="0" hdg="0" length="10"><arc curvature="0.1"/></geometry>
      <geometry s="10" x="8" y="4" hdg="1" length="0.1"><line/></geometry>
      <geometry s="10.1" x="8.1" y="4.1" hdg="1" length="10"><arc curvature="-0.1"/></geometry>
""",
    ),
    "short_arc_between_lines": _road_with_planview(
        "4",
        """
      <geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>
      <geometry s="10" x="10" y="0" hdg="0" length="0.1"><arc curvature="0.5"/></geometry>
      <geometry s="10.1" x="10.1" y="0" hdg="0.05" length="10"><line/></geometry>
""",
    ),
    "mixed_primitive_chain": _road_with_planview(
        "5",
        """
      <geometry s="0" x="0" y="0" hdg="0" length="5"><line/></geometry>
      <geometry s="5" x="5" y="0" hdg="0" length="5"><arc curvature="0.2"/></geometry>
      <geometry s="10" x="9" y="2" hdg="1" length="5"><spiral curvStart="0.2" curvEnd="0"/></geometry>
""",
    ),
    "heading_discontinuity": _road_with_planview(
        "6",
        """
      <geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>
      <geometry s="10" x="10" y="0" hdg="1.57079632679" length="10"><line/></geometry>
""",
    ),
    "valid_sharp_corner": _road_with_planview(
        "7",
        """
      <geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>
      <geometry s="10" x="10" y="0" hdg="1.57079632679" length="10"><line/></geometry>
""",
    ),
    "dependent_elevation_and_lanes": _road_with_planview(
        "8",
        """
      <geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry>
      <geometry s="10" x="10" y="0" hdg="0" length="0.1"><arc curvature="2.0"/></geometry>
""",
        """
    <elevationProfile><elevation s="0" a="1" b="0" c="0" d="0"/></elevationProfile>
    <lateralProfile><superelevation s="0" a="0" b="0" c="0" d="0"/></lateralProfile>
    <lanes><laneSection s="0"><center><lane id="0" type="none" level="false"/></center></laneSection></lanes>
    <signals><signal id="s1" s="1" t="0"/></signals>
    <objects><object id="o1" s="2" t="0"/></objects>
""",
    ),
}


class _NoopPlotter:
    @staticmethod
    def save_preview(*args, **kwargs):
        return None


class _NoopMeshChecker:
    @staticmethod
    def quick_check(root):
        return {"ok": True}


class _NoopHeatmap:
    @staticmethod
    def run(*args, **kwargs):
        return None


class _DiagnosticMeshRepairer:
    def __init__(self, xodr_path: str):
        self.xodr_path = xodr_path

    def scan_roads(self):
        return {"diagnostic": True}


class _QGate:
    def gate_geometric_continuity(self, path: str):
        return {"ok": True, "path": path}

    def gate_physics_feasibility(self, root):
        return {"ok": True}

    def gate_randomness_entropy(self, root):
        return {"ok": True}


class _FakeStage:
    def __init__(self, out_dir: Path):
        self.out_dir = str(out_dir)
        self.qgate = _QGate()
        self.semantic_state = {}

    def _stage_gate(self, stage: str, gate: str, fn):
        return fn()


def _load_xodr(path: str):
    tree = ET.parse(path)
    return tree, tree.getroot()


@pytest.fixture(autouse=True)
def _patch_stage6_runtime(monkeypatch):
    monkeypatch.setattr(stage_06_links, "PlanViewSmoother", PlanViewSmoother, raising=False)
    monkeypatch.setattr(stage_06_links, "MeshContinuityRepairer", _DiagnosticMeshRepairer, raising=False)
    monkeypatch.setattr(stage_06_links, "MapPlotter", _NoopPlotter, raising=False)
    monkeypatch.setattr(stage_06_links, "MeshChecker", _NoopMeshChecker, raising=False)
    monkeypatch.setattr(stage_06_links, "HeatmapGenerator", _NoopHeatmap, raising=False)
    monkeypatch.setattr(stage_06_links, "load_xodr", _load_xodr, raising=False)
    monkeypatch.setattr(stage_06_links, "_count_lanes", lambda path: 0, raising=False)


@pytest.mark.parametrize("fixture_name", sorted(FIXTURES))
def test_stage6_read_only_containment_preserves_protected_semantics(
    tmp_path: Path,
    fixture_name: str,
) -> None:
    src = tmp_path / f"{fixture_name}.xodr"
    geo = tmp_path / f"{fixture_name}.geo.xodr"
    cont = tmp_path / f"{fixture_name}.cont.xodr"
    _write_xodr(src, FIXTURES[fixture_name])
    root = ET.parse(src).getroot()

    out = stage_06_links._run_stage6_read_only_diagnostic(
        _FakeStage(tmp_path),
        str(src),
        str(geo),
        str(cont),
        root,
        min_len=2.0,
        max_len=300.0,
        max_curv=1.0,
    )

    assert out == str(cont)
    assert stage_06_links._semantic_stage6_diff(str(src), str(cont))["ok"] is True
    report = json.loads((tmp_path / "stage6_containment_runtime.json").read_text(encoding="utf-8"))
    assert report["mode"] == "READ_ONLY_DIAGNOSTIC"
    assert report["xodr_semantic_changes"]["ok"] is True


def test_stage6_semantic_diff_detects_protected_planview_change(tmp_path: Path) -> None:
    before = tmp_path / "before.xodr"
    after = tmp_path / "after.xodr"
    _write_xodr(before, FIXTURES["line_followed_by_arc"])
    shutil.copy2(before, after)
    root = ET.parse(after).getroot()
    geom = root.find("./road/planView/geometry")
    assert geom is not None
    geom.set("length", "11")
    ET.ElementTree(root).write(after, encoding="UTF-8", xml_declaration=True)

    diff = stage_06_links._semantic_stage6_diff(str(before), str(after))

    assert diff["ok"] is False
    assert diff["changed"] == [{"domain": "road", "road_id": "1"}]


def test_stage6_governed_profiles_are_contained() -> None:
    class Release:
        RELEASE_PROFILE = "STRUCTURAL_RELEASE"
        THESIS_STRICT = True

    class Experimental:
        RELEASE_PROFILE = "EXPERIMENTAL_UNSAFE"
        THESIS_STRICT = False

    assert stage_06_links._stage6_governed_containment(Release()) is True
    assert stage_06_links._stage6_governed_containment(Experimental()) is False


def test_stage6_governed_containment_development_profile_is_not_contained() -> None:
    class Development:
        RELEASE_PROFILE = "DEVELOPMENT"
        THESIS_STRICT = False

    assert stage_06_links._stage6_governed_containment(Development()) is False


def test_stage6_governed_containment_named_profile_without_thesis_strict_is_contained() -> None:
    # A non-DEVELOPMENT, non-EXPERIMENTAL_UNSAFE profile is contained by
    # name alone -- THESIS_STRICT is not the only path to containment.
    class Structural:
        RELEASE_PROFILE = "STRUCTURAL_RELEASE"
        THESIS_STRICT = False

    assert stage_06_links._stage6_governed_containment(Structural()) is True


def test_stage6_governed_containment_no_profile_no_strict_is_not_contained() -> None:
    class Bare:
        RELEASE_PROFILE = ""
        THESIS_STRICT = False

    assert stage_06_links._stage6_governed_containment(Bare()) is False


def test_stage6_governed_containment_thesis_strict_overrides_experimental_unsafe() -> None:
    # THESIS_STRICT must win even if a profile explicitly opts into
    # EXPERIMENTAL_UNSAFE -- academic-validity containment cannot be
    # bypassed by profile choice alone.
    class StrictExperimental:
        RELEASE_PROFILE = "EXPERIMENTAL_UNSAFE"
        THESIS_STRICT = True

    assert stage_06_links._stage6_governed_containment(StrictExperimental()) is True
