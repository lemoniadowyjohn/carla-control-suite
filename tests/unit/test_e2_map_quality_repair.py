from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.tools.e2_map_quality_repair import (
    add_header_offset_if_missing,
    reconcile_short_connector_geometry_lengths,
    repair_file,
    smooth_elevation_jumps_endpoint_preserving,
    strict_elevation_jump_details,
)


def _root(text: str) -> ET.Element:
    return ET.fromstring(text)


def test_add_header_offset_is_noop_geometry_transform():
    root = _root(
        '<OpenDRIVE><header revMajor="1" revMinor="4">'
        "<geoReference>+proj=utm +zone=32</geoReference>"
        "</header>"
        '<road id="1" length="1.0"><planView>'
        '<geometry s="0" x="840000" y="5460000" hdg="0" length="1.0"><line/></geometry>'
        "</planView></road></OpenDRIVE>"
    )

    report = add_header_offset_if_missing(root)

    assert report["changed"] is True
    assert root.find("./header/offset").attrib == {"x": "0.0", "y": "0.0", "z": "0.0", "hdg": "0.0"}
    assert root.find("./road/planView/geometry").get("x") == "840000"
    assert root.find("./road/planView/geometry").get("y") == "5460000"


def test_reconcile_short_connector_geometry_length_to_road_length():
    root = _root(
        '<OpenDRIVE><road id="49822" length="0.10000000" junction="339">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="0.00000002"><line/></geometry></planView>'
        "</road></OpenDRIVE>"
    )

    report = reconcile_short_connector_geometry_lengths(root)

    assert report["geometry_lengths_changed"] == 1
    assert root.find("./road/planView/geometry").get("length") == "0.10000000"


def test_endpoint_preserving_elevation_smoothing_reduces_internal_jumps():
    root = _root(
        '<OpenDRIVE><road id="r1" length="20.0">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="20.0"><line/></geometry></planView>'
        "<elevationProfile>"
        '<elevation s="0" a="100.0" b="0" c="0" d="0"/>'
        '<elevation s="5" a="106.0" b="0" c="0" d="0"/>'
        '<elevation s="10" a="106.0" b="0" c="0" d="0"/>'
        '<elevation s="15" a="101.0" b="0" c="0" d="0"/>'
        '<elevation s="20" a="100.0" b="0" c="0" d="0"/>'
        "</elevationProfile>"
        "</road></OpenDRIVE>"
    )

    assert len(strict_elevation_jump_details(root)) == 2
    report = smooth_elevation_jumps_endpoint_preserving(root, max_dz_per_m=0.25)

    elems = root.findall("./road/elevationProfile/elevation")
    assert report["roads_smoothed"] == 1
    assert len(strict_elevation_jump_details(root)) == 0
    assert elems[0].get("a") == "100.0"
    assert elems[-1].get("a") == "100.0"
    assert elems[0].get("b") != "0.000000"
    assert all(elem.get("c") == "0.000000" for elem in elems)
    assert all(elem.get("d") == "0.000000" for elem in elems)


def test_repair_file_preserves_synthetic_structure_and_reports_partial_preflight_absence(tmp_path):
    source = tmp_path / "input.xodr"
    output = tmp_path / "output.xodr"
    report_json = tmp_path / "report.json"
    report_md = tmp_path / "report.md"
    source.write_text(
        '<OpenDRIVE><header revMajor="1" revMinor="4">'
        "<geoReference>+proj=utm +zone=32</geoReference>"
        "</header>"
        '<road id="r1" length="20.0">'
        '<planView><geometry s="0" x="840000" y="5460000" hdg="0" length="20.0"><line/></geometry></planView>'
        "<elevationProfile>"
        '<elevation s="0" a="100.0" b="0" c="0" d="0"/>'
        '<elevation s="5" a="106.0" b="0" c="0" d="0"/>'
        '<elevation s="10" a="106.0" b="0" c="0" d="0"/>'
        '<elevation s="15" a="101.0" b="0" c="0" d="0"/>'
        '<elevation s="19" a="100.0" b="0" c="0" d="0"/>'
        "</elevationProfile>"
        '<signals><signal id="s1" s="1" t="0" type="R" subtype="274"/></signals>'
        '<objects><object id="cw1" s="1" t="0" type="crosswalk"/></objects>'
        "</road>"
        '<road id="49822" length="0.10000000" junction="339">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="0.00000002"><line/></geometry></planView>'
        '<elevationProfile><elevation s="0" a="100.0" b="0" c="0" d="0"/></elevationProfile>'
        "</road>"
        '<junction id="339"/></OpenDRIVE>',
        encoding="utf-8",
    )

    report = repair_file(
        input_xodr=source,
        output_xodr=output,
        report_json=report_json,
        report_md=report_md,
    )

    repaired = ET.parse(output).getroot()
    assert report["after"]["counts"]["roads"] == 2
    assert report["after"]["counts"]["junctions"] == 1
    assert report["after"]["counts"]["signals"] == 1
    assert report["after"]["counts"]["objects"] == 1
    assert report["after"]["counts"]["nonzero_elevation_segments"] == 6
    assert report["after"]["elevation_qa"]["strict_elev_jump_count"] == 0
    assert repaired.find("./header/offset") is not None
    assert repaired.find("./road[@id='49822']/planView/geometry").get("length") == "0.10000000"
    assert report["verdict"] == "DRIVABLE_CANDIDATE_REVIEW_REQUIRED"
    assert report_json.is_file()
    assert report_md.is_file()
