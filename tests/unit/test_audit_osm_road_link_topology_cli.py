from __future__ import annotations

import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.crosswalk_writer import project_crossing_to_local
from ultimate_pipeline.tools.audit_osm_road_link_topology import main


def test_cli_writes_read_only_topology_report(tmp_path: Path) -> None:
    osm_path = tmp_path / "source.osm"
    xodr_path = tmp_path / "map.xodr"
    report_path = tmp_path / "report.json"
    osm_path.write_text(
        "<osm>"
        '<node id="1" lon="11.4000" lat="48.7000"/>'
        '<node id="2" lon="11.4001" lat="48.7000"/>'
        '<node id="3" lon="11.4002" lat="48.7000"/>'
        '<way id="a"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way>'
        '<way id="b"><nd ref="2"/><nd ref="3"/><tag k="highway" v="residential"/></way>'
        "</osm>",
        encoding="utf-8",
    )
    first, second, third = project_crossing_to_local(
        [(11.4000, 48.7000), (11.4001, 48.7000), (11.4002, 48.7000)], (0.0, 0.0)
    )
    first_heading = math.atan2(second[1] - first[1], second[0] - first[0])
    second_heading = math.atan2(third[1] - second[1], third[0] - second[0])
    first_length = math.dist(first, second)
    second_length = math.dist(second, third)
    xodr_path.write_text(
        "<OpenDRIVE>"
        '<road id="1"><link><successor elementType="road" elementId="2"/></link><planView>'
        f'<geometry s="0" x="{first[0]}" y="{first[1]}" hdg="{first_heading}" length="{first_length}"><line/></geometry>'
        "</planView></road>"
        '<road id="2"><link><predecessor elementType="road" elementId="1"/></link><planView>'
        f'<geometry s="0" x="{second[0]}" y="{second[1]}" hdg="{second_heading}" length="{second_length}"><line/></geometry>'
        "</planView></road>"
        "</OpenDRIVE>",
        encoding="utf-8",
    )

    before = xodr_path.read_bytes()
    assert main(["--xodr", str(xodr_path), "--osm", str(osm_path), "--out", str(report_path)]) == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["summary_metrics"]["agree"] == 2
    assert xodr_path.read_bytes() == before
