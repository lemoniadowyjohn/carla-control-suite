from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.tools.crash_safe_length_repair import (
    apply_c3_violation_length_repair,
    length_invariant_summary,
    merge_road_objects,
    repair_file,
    structural_counts,
)


def _root(text: str) -> ET.Element:
    return ET.fromstring(text)


def test_c3_violation_only_length_repair_removes_geometry_length_violation():
    root = _root(
        '<OpenDRIVE><road id="1" length="10.0">'
        '<planView><geometry s="0.0" length="12.0" x="0" y="0" hdg="0"/></planView>'
        "</road></OpenDRIVE>"
    )

    assert length_invariant_summary(root)["violations"] == 1
    report = apply_c3_violation_length_repair(root)

    assert report["mode"] == "c3_violation_only_full_precision_length_repair"
    assert report["roads_length_adjusted"] == 1
    assert root.find("road").get("length") == repr(12.001)
    assert length_invariant_summary(root)["violations"] == 0


def test_c3_violation_only_length_repair_leaves_compliant_geometry_unchanged():
    root = _root(
        '<OpenDRIVE><road id="1" length="10.0">'
        '<planView><geometry s="0.0" length="9.0" x="0" y="0" hdg="0"/></planView>'
        "</road></OpenDRIVE>"
    )

    report = apply_c3_violation_length_repair(root)

    assert report["roads_length_adjusted"] == 0
    assert root.find("road").get("length") == "10.0"


def test_c3_violation_only_repair_preserves_elevation_signals_and_objects():
    root = _root(
        '<OpenDRIVE><road id="1" length="1.0">'
        '<planView><geometry s="0.0" length="1.5" x="0" y="0" hdg="0"/></planView>'
        '<elevationProfile><elevation s="0" a="1" b="0" c="0" d="0"/></elevationProfile>'
        '<signals><signal id="s1" s="0.1" t="0" type="R" subtype="274"/></signals>'
        '<objects><object id="o1" s="0.1" t="0" type="crosswalk"/></objects>'
        '</road><road id="2" length="10.0">'
        '<planView><geometry s="0.0" length="9.0" x="0" y="0" hdg="0"/></planView>'
        '<elevationProfile><elevation s="0" a="2" b="0" c="0" d="0"/></elevationProfile>'
        "</road><junction id=\"j1\"/></OpenDRIVE>"
    )
    before = structural_counts(root)

    apply_c3_violation_length_repair(root)
    after = structural_counts(root)

    assert after == before
    assert after["signals"] == 1
    assert after["objects"] == 1
    assert after["crosswalk_objects"] == 1
    assert after["nonzero_elevation_segments"] == 2
    assert root.findall("road")[1].get("length") == "10.0"


def test_object_merge_carries_feasible_crosswalk_objects_without_flattening():
    target = _root(
        '<OpenDRIVE><road id="1" length="12.0">'
        '<planView><geometry s="0.0" length="12.0" x="0" y="0" hdg="0"/></planView>'
        '<elevationProfile><elevation s="0" a="3" b="0" c="0" d="0"/></elevationProfile>'
        "</road></OpenDRIVE>"
    )
    source = _root(
        '<OpenDRIVE><road id="1" length="12.0">'
        '<planView><geometry s="0.0" length="12.0" x="0" y="0" hdg="0"/></planView>'
        '<objects><object id="cw1" s="12.0005" t="0" type="crosswalk"/></objects>'
        "</road></OpenDRIVE>"
    )

    report = merge_road_objects(target, source)

    counts = structural_counts(target)
    assert report["feasible"] is True
    assert report["object_s_tolerance_m"] == 1e-3
    assert report["source_objects"] == 1
    assert report["merged"] == 1
    assert counts["objects"] == 1
    assert counts["crosswalk_objects"] == 1
    assert counts["nonzero_elevation_segments"] == 1


def test_repair_file_reduces_synthetic_elevated_violation_to_zero(tmp_path):
    source = tmp_path / "synthetic_elevated_violating.xodr"
    output = tmp_path / "synthetic_elevated_safe.xodr"
    report_json = tmp_path / "report.json"
    report_md = tmp_path / "report.md"
    source.write_text(
        '<OpenDRIVE><road id="1" length="1.0">'
        '<planView><geometry s="0.0" length="1.5" x="0" y="0" hdg="0"/></planView>'
        '<elevationProfile><elevation s="0" a="1" b="0" c="0" d="0"/></elevationProfile>'
        '<signals><signal id="s1" s="0.1" t="0" type="R" subtype="274"/></signals>'
        '</road><road id="2" length="10.0">'
        '<planView><geometry s="0.0" length="9.0" x="0" y="0" hdg="0"/></planView>'
        '<elevationProfile><elevation s="0" a="2" b="0" c="0" d="0"/></elevationProfile>'
        "</road><junction id=\"j1\"/></OpenDRIVE>",
        encoding="utf-8",
    )

    report = repair_file(
        input_xodr=source,
        output_xodr=output,
        report_json=report_json,
        report_md=report_md,
        expected_roads=2,
        expected_junctions=1,
        min_signals=1,
        min_nonzero_elevation=2,
    )

    repaired = ET.parse(output).getroot()
    assert report["verdict"] == "ELEVATED_SAFE_CANDIDATE_PRODUCED"
    assert report["before"]["g19"]["violations"] == 1
    assert report["after"]["g19"]["violations"] == 0
    assert report["length_change_audit"]["unexpected_length_changes"] == []
    assert repaired.findall("road")[0].get("length") == repr(1.501)
    assert repaired.findall("road")[1].get("length") == "10.0"
    assert structural_counts(repaired)["nonzero_elevation_segments"] == 2
    assert report_json.is_file()
    assert report_md.is_file()
