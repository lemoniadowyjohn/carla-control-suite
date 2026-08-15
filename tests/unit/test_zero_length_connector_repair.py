from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.tools.crash_safe_length_repair import structural_counts
from ultimate_pipeline.tools.zero_length_connector_repair import (
    apply_reference_zero_length_connector_repair,
    nonpositive_geometry_details,
    repair_file,
)


def _root(text: str) -> ET.Element:
    return ET.fromstring(text)


def test_reference_zero_length_repair_copies_matching_reference_geometry_length():
    target = _root(
        '<OpenDRIVE><road id="50003" length="0.10000000" junction="131">'
        '<planView><geometry s="0.00000000" x="842522.0" y="5461822.0" hdg="0.00000000" length="0.00000000"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="367.0" b="0" c="0" d="0"/></elevationProfile>'
        "</road></OpenDRIVE>"
    )
    reference = _root(
        '<OpenDRIVE><road id="50003" length="0.10000000" junction="131">'
        '<planView><geometry s="0.00000000" x="842522.0" y="5461822.0" hdg="0.00000000" length="0.10000000"><line/></geometry></planView>'
        "</road></OpenDRIVE>"
    )

    assert len(nonpositive_geometry_details(target)) == 1
    report = apply_reference_zero_length_connector_repair(target, reference)

    assert report["geometry_lengths_changed"] == 1
    assert report["skipped"] == []
    assert target.find("./road/planView/geometry").get("length") == "0.10000000"
    assert nonpositive_geometry_details(target) == []
    assert structural_counts(target)["nonzero_elevation_segments"] == 1


def test_reference_zero_length_repair_skips_geometry_identity_mismatch():
    target = _root(
        '<OpenDRIVE><road id="50003" length="0.10000000">'
        '<planView><geometry s="0.00000000" x="842522.0" y="5461822.0" hdg="0.00000000" length="0.00000000"><line/></geometry></planView>'
        "</road></OpenDRIVE>"
    )
    reference = _root(
        '<OpenDRIVE><road id="50003" length="0.10000000">'
        '<planView><geometry s="0.00000000" x="842523.0" y="5461822.0" hdg="0.00000000" length="0.10000000"><line/></geometry></planView>'
        "</road></OpenDRIVE>"
    )

    report = apply_reference_zero_length_connector_repair(target, reference)

    assert report["geometry_lengths_changed"] == 0
    assert report["skipped"][0]["reason"] == "geometry_identity_mismatch_against_reference"
    assert target.find("./road/planView/geometry").get("length") == "0.00000000"


def test_repair_file_preserves_structure_and_removes_synthetic_nonpositive_geometry(tmp_path):
    target = tmp_path / "elevated_safe.xodr"
    reference = tmp_path / "flat_safe.xodr"
    output = tmp_path / "elevated_safe_loadable.xodr"
    report_json = tmp_path / "report.json"
    report_md = tmp_path / "report.md"
    target.write_text(
        '<OpenDRIVE><road id="50003" length="0.10000000" junction="131">'
        '<planView><geometry s="0.00000000" x="842522.0" y="5461822.0" hdg="0.00000000" length="0.00000000"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="367.0" b="0" c="0" d="0"/></elevationProfile>'
        '<signals><signal id="s1" s="0.01" t="0" type="R" subtype="274"/></signals>'
        '<objects><object id="cw1" s="0.01" t="0" type="crosswalk"/></objects>'
        "</road><junction id=\"131\"/></OpenDRIVE>",
        encoding="utf-8",
    )
    reference.write_text(
        '<OpenDRIVE><road id="50003" length="0.10000000" junction="131">'
        '<planView><geometry s="0.00000000" x="842522.0" y="5461822.0" hdg="0.00000000" length="0.10000000"><line/></geometry></planView>'
        "</road><junction id=\"131\"/></OpenDRIVE>",
        encoding="utf-8",
    )

    report = repair_file(
        input_xodr=target,
        reference_xodr=reference,
        output_xodr=output,
        report_json=report_json,
        report_md=report_md,
    )

    repaired = ET.parse(output).getroot()
    assert report["verdict"] == "E1B_LOADABILITY_CONNECTOR_REPAIR_PASS"
    assert len(report["before"]["nonpositive_geometry_details"]) == 1
    assert len(report["after"]["nonpositive_geometry_details"]) == 0
    assert repaired.find("./road/planView/geometry").get("length") == "0.10000000"
    counts = structural_counts(repaired)
    assert counts["roads"] == 1
    assert counts["junctions"] == 1
    assert counts["signals"] == 1
    assert counts["objects"] == 1
    assert counts["nonzero_elevation_segments"] == 1
    assert report_json.is_file()
    assert report_md.is_file()
