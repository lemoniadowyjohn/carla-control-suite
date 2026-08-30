# -*- coding: utf-8 -*-
"""Tests for small quality/check_*.py modules dispatched by
QualityGateManager: check_xml_integrity, check_semantic_overlap,
check_randomness_entropy, collision_mesh. All four had zero prior test
coverage despite being live via gate_xml_integrity / gate_semantic_overlap
/ gate_randomness_entropy / gate_collision_mesh. Reviewed for the same
defect classes found elsewhere this session (missing dict keys, XPath
depth mismatches, silently-swallowed exceptions) -- no bugs found in any
of the four; these are characterization tests locking in current
behavior.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.quality.check_xml_integrity import XMLIntegrityChecker
from ultimate_pipeline.quality.check_semantic_overlap import SemanticOverlapChecker
from ultimate_pipeline.quality.check_randomness_entropy import RandomnessEntropyMetric
from ultimate_pipeline.quality.collision_mesh import CollisionMeshValidator


# ---------------------------------------------------------------------------
# XMLIntegrityChecker
# ---------------------------------------------------------------------------


def test_xml_integrity_missing_file_reports_missing_file(tmp_path):
    issues = XMLIntegrityChecker.validate(str(tmp_path / "does_not_exist.xodr"))
    assert issues == [{"type": "missing_file", "path": str(tmp_path / "does_not_exist.xodr")}]


def test_xml_integrity_unparseable_xml_reports_parse_error(tmp_path):
    bad = tmp_path / "bad.xodr"
    bad.write_text("<OpenDRIVE><unclosed>", encoding="utf-8")
    issues = XMLIntegrityChecker.validate(str(bad))
    assert issues[0]["type"] == "parse_error"


def test_xml_integrity_wrong_root_tag_is_flagged(tmp_path):
    f = tmp_path / "wrong.xodr"
    f.write_text('<?xml version="1.0"?><NotOpenDRIVE/>', encoding="utf-8")
    issues = XMLIntegrityChecker.validate(str(f))
    assert {"type": "root_tag_mismatch", "tag": "NotOpenDRIVE"} in issues


def test_xml_integrity_no_roads_is_flagged(tmp_path):
    f = tmp_path / "noroads.xodr"
    f.write_text(
        '<?xml version="1.0"?><OpenDRIVE><header north="0" south="0" east="0" west="0"/></OpenDRIVE>',
        encoding="utf-8",
    )
    issues = XMLIntegrityChecker.validate(str(f))
    assert {"type": "no_roads"} in issues


def test_xml_integrity_missing_header_is_flagged(tmp_path):
    f = tmp_path / "noheader.xodr"
    f.write_text(
        '<?xml version="1.0"?><OpenDRIVE><road id="1" length="1" junction="-1"/></OpenDRIVE>',
        encoding="utf-8",
    )
    issues = XMLIntegrityChecker.validate(str(f))
    assert {"type": "missing_header"} in issues


def test_xml_integrity_header_missing_bounds_attr_is_flagged(tmp_path):
    f = tmp_path / "badheader.xodr"
    f.write_text(
        '<?xml version="1.0"?><OpenDRIVE>'
        '<header north="0" south="0" east="0"/>'  # missing "west"
        '<road id="1" length="1" junction="-1"/>'
        "</OpenDRIVE>",
        encoding="utf-8",
    )
    issues = XMLIntegrityChecker.validate(str(f))
    assert {"type": "header_missing_attr", "attr": "west"} in issues


def test_xml_integrity_valid_file_reports_no_issues(tmp_path):
    f = tmp_path / "good.xodr"
    f.write_text(
        '<?xml version="1.0"?><OpenDRIVE>'
        '<header north="1" south="0" east="1" west="0"/>'
        '<road id="1" length="1" junction="-1"/>'
        "</OpenDRIVE>",
        encoding="utf-8",
    )
    assert XMLIntegrityChecker.validate(str(f)) == []


# ---------------------------------------------------------------------------
# SemanticOverlapChecker
# ---------------------------------------------------------------------------


def test_semantic_overlap_flags_sidewalk_and_building_on_same_road():
    root = ET.fromstring(
        '<OpenDRIVE><road id="1" length="1" junction="-1">'
        '<objects>'
        '<object id="a" type="sidewalk"/>'
        '<object id="b" type="building"/>'
        "</objects></road></OpenDRIVE>"
    )
    issues = SemanticOverlapChecker.validate(root)
    assert len(issues) == 1
    assert issues[0]["road_id"] == "1"
    assert issues[0]["n_sidewalks"] == 1
    assert issues[0]["n_buildings"] == 1


def test_semantic_overlap_sidewalk_only_is_not_flagged():
    root = ET.fromstring(
        '<OpenDRIVE><road id="1" length="1" junction="-1">'
        '<objects><object id="a" type="sidewalk"/></objects>'
        "</road></OpenDRIVE>"
    )
    assert SemanticOverlapChecker.validate(root) == []


def test_semantic_overlap_no_objects_is_not_flagged():
    root = ET.fromstring('<OpenDRIVE><road id="1" length="1" junction="-1"/></OpenDRIVE>')
    assert SemanticOverlapChecker.validate(root) == []


# ---------------------------------------------------------------------------
# RandomnessEntropyMetric
# ---------------------------------------------------------------------------


def test_randomness_entropy_no_geometry_returns_zero():
    root = ET.fromstring("<OpenDRIVE></OpenDRIVE>")
    assert RandomnessEntropyMetric.compute(root) == 0.0


def test_randomness_entropy_all_headings_identical_is_zero():
    # A single bin -> entropy 0 (perfectly "regular"/grid-aligned).
    xml = "<OpenDRIVE>" + "".join(
        f'<road id="{i}" length="1" junction="-1"><planView>'
        f'<geometry s="0" x="0" y="0" hdg="0.0" length="1"/>'
        f"</planView></road>"
        for i in range(5)
    ) + "</OpenDRIVE>"
    root = ET.fromstring(xml)
    assert RandomnessEntropyMetric.compute(root) == 0.0


def test_randomness_entropy_varied_headings_is_higher_than_uniform():
    import math

    uniform_xml = "<OpenDRIVE>" + "".join(
        f'<road id="{i}" length="1" junction="-1"><planView>'
        f'<geometry s="0" x="0" y="0" hdg="0.0" length="1"/>'
        f"</planView></road>"
        for i in range(8)
    ) + "</OpenDRIVE>"
    varied_xml = "<OpenDRIVE>" + "".join(
        f'<road id="{i}" length="1" junction="-1"><planView>'
        f'<geometry s="0" x="0" y="0" hdg="{i * math.pi / 4.0}" length="1"/>'
        f"</planView></road>"
        for i in range(8)
    ) + "</OpenDRIVE>"

    uniform_entropy = RandomnessEntropyMetric.compute(ET.fromstring(uniform_xml))
    varied_entropy = RandomnessEntropyMetric.compute(ET.fromstring(varied_xml))
    assert varied_entropy > uniform_entropy


def test_randomness_entropy_skips_unparseable_heading():
    root = ET.fromstring(
        '<OpenDRIVE><road id="1" length="1" junction="-1"><planView>'
        '<geometry s="0" x="0" y="0" hdg="not_a_number" length="1"/>'
        "</planView></road></OpenDRIVE>"
    )
    # No valid headings collected -> falls back to the "no headings" path.
    assert RandomnessEntropyMetric.compute(root) == 0.0


# ---------------------------------------------------------------------------
# CollisionMeshValidator
# ---------------------------------------------------------------------------


def test_collision_mesh_disabled_by_default_returns_no_issues(monkeypatch):
    import ultimate_pipeline.quality.collision_mesh as cm_mod

    monkeypatch.setattr(cm_mod.SETTINGS, "ENABLE_SHAPELY_GEOMETRY_QA", False, raising=False)
    root = ET.fromstring("<OpenDRIVE></OpenDRIVE>")
    assert CollisionMeshValidator.validate(root) == []


def test_collision_mesh_enabled_but_shapely_missing_returns_no_issues(monkeypatch):
    import ultimate_pipeline.quality.collision_mesh as cm_mod

    monkeypatch.setattr(cm_mod.SETTINGS, "ENABLE_SHAPELY_GEOMETRY_QA", True, raising=False)
    monkeypatch.setattr(cm_mod, "HAS_SHAPELY", False, raising=False)
    root = ET.fromstring("<OpenDRIVE></OpenDRIVE>")
    assert CollisionMeshValidator.validate(root) == []


def test_collision_mesh_skips_roads_with_too_few_points(monkeypatch):
    import ultimate_pipeline.quality.collision_mesh as cm_mod

    if not cm_mod.HAS_SHAPELY:
        import pytest

        pytest.skip("shapely not installed in this environment")

    monkeypatch.setattr(cm_mod.SETTINGS, "ENABLE_SHAPELY_GEOMETRY_QA", True, raising=False)
    root = ET.fromstring(
        '<OpenDRIVE><road id="1" length="1" junction="-1"><planView>'
        '<geometry s="0" x="0" y="0" hdg="0" length="1"/>'
        '<geometry s="1" x="1" y="0" hdg="0" length="1"/>'
        "</planView></road></OpenDRIVE>"
    )
    # Only 2 points on this road -- below the "need >= 4 points" threshold
    # -- must be skipped cleanly, not raise.
    assert CollisionMeshValidator.validate(root) == []
