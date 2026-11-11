"""Regression tests for the versioned RQ1 structural signature."""
from __future__ import annotations

from pathlib import Path

from research.rq1_structural_signature import (
    STRUCTURAL_SIGNATURE_V1,
    STRUCTURAL_SIGNATURE_V2,
    compute_structural_signature,
)


def _xodr(
    *,
    x: str = "0",
    y: str = "0",
    hdg: str = "0",
    geometry_length: str = "10",
    road_length: str = "10",
    arc: str = "0.1",
    param_a_u: str = "0",
    elevation_a: str = "0",
    lateral_a: str = "0",
    lane_to: str = "-1",
    duplicate_lane_link: bool = False,
    contact_point: str = "start",
    reordered_attributes: bool = False,
) -> str:
    geometry_attrs = (
        f's="0" x="{x}" y="{y}" hdg="{hdg}" length="{geometry_length}"'
        if not reordered_attributes
        else f'length="{geometry_length}" hdg="{hdg}" y="{y}" x="{x}" s="0"'
    )
    duplicate = f'<laneLink from="-1" to="{lane_to}"/>' if duplicate_lane_link else ""
    return f'''<OpenDRIVE><header/>
  <road id="1" junction="-1" length="{road_length}">
    <planView>
      <geometry {geometry_attrs}><arc curvature="{arc}"/></geometry>
      <geometry s="{geometry_length}" x="10" y="0" hdg="0" length="1"><paramPoly3 aU="{param_a_u}" bU="0" cU="0" dU="0" aV="0" bV="0" cV="0" dV="0" pRange="normalized"/></geometry>
    </planView>
    <elevationProfile><elevation s="0" a="{elevation_a}" b="0" c="0" d="0"/></elevationProfile>
    <lateralProfile><superelevation s="0" a="{lateral_a}" b="0" c="0" d="0"/></lateralProfile>
    <lanes><laneSection s="0"><center><lane id="0" type="driving"/></center></laneSection></lanes>
  </road>
  <junction id="9"><connection id="0" incomingRoad="1" connectingRoad="1" contactPoint="{contact_point}">
    <laneLink from="-1" to="{lane_to}"/>{duplicate}
  </connection></junction>
</OpenDRIVE>'''


def _write(tmp_path: Path, name: str, **kwargs: str | bool) -> Path:
    path = tmp_path / name
    path.write_text(_xodr(**kwargs), encoding="utf-8")
    return path


def _sha(path: Path, version: str) -> str:
    return compute_structural_signature(path, version=version)["sha256"]


def test_v1_digest_is_pinned_and_v2_is_new_default(tmp_path: Path):
    path = _write(tmp_path, "base.xodr")
    assert compute_structural_signature(path)["version"] == STRUCTURAL_SIGNATURE_V2
    assert _sha(path, STRUCTURAL_SIGNATURE_V1) == "f5e457e499acd07685478ec51d2c66d3ce5f5f832688cb492205aca18a660b13"


def test_v2_detects_geometry_and_profile_changes_v1_does_not(tmp_path: Path):
    base = _write(tmp_path, "base.xodr")
    mutations = [
        {"x": "1"}, {"y": "1"}, {"hdg": "1"}, {"geometry_length": "11"},
        {"arc": "0.2"}, {"param_a_u": "1"}, {"road_length": "11"},
        {"elevation_a": "1"}, {"lateral_a": "1"},
    ]
    for index, kwargs in enumerate(mutations):
        changed = _write(tmp_path, f"geometry-{index}.xodr", **kwargs)
        assert _sha(base, STRUCTURAL_SIGNATURE_V1) == _sha(changed, STRUCTURAL_SIGNATURE_V1)
        assert _sha(base, STRUCTURAL_SIGNATURE_V2) != _sha(changed, STRUCTURAL_SIGNATURE_V2)


def test_v2_detects_lane_links_duplicates_and_contact_point(tmp_path: Path):
    base = _write(tmp_path, "base.xodr")
    for index, kwargs in enumerate((
        {"lane_to": "-2"},
        {"duplicate_lane_link": True},
    )):
        changed = _write(tmp_path, f"junction-{index}.xodr", **kwargs)
        assert _sha(base, STRUCTURAL_SIGNATURE_V1) == _sha(changed, STRUCTURAL_SIGNATURE_V1)
        assert _sha(base, STRUCTURAL_SIGNATURE_V2) != _sha(changed, STRUCTURAL_SIGNATURE_V2)
    changed_contact = _write(tmp_path, "junction-contact.xodr", contact_point="end")
    assert _sha(base, STRUCTURAL_SIGNATURE_V2) != _sha(changed_contact, STRUCTURAL_SIGNATURE_V2)


def test_v2_ignores_attribute_order_whitespace_and_matches_identical(tmp_path: Path):
    base = _write(tmp_path, "base.xodr")
    reordered = _write(tmp_path, "reordered.xodr", reordered_attributes=True)
    identical = _write(tmp_path, "identical.xodr")
    assert _sha(base, STRUCTURAL_SIGNATURE_V2) == _sha(reordered, STRUCTURAL_SIGNATURE_V2)
    assert _sha(base, STRUCTURAL_SIGNATURE_V2) == _sha(identical, STRUCTURAL_SIGNATURE_V2)
