from __future__ import annotations

import json
from pathlib import Path

from ultimate_pipeline.tools.audit_lane_link_turn_classification import main, run


def _map() -> str:
    return (
        "<OpenDRIVE>"
        '<road id="1"><planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/>'
        "</geometry></planView><lanes><laneSection s=\"0\"><right>"
        '<lane id="-1" type="driving"><width sOffset="0" a="3.5"/></lane>'
        "</right></laneSection></lanes></road>"
        '<road id="2"><planView><geometry s="0" x="10" y="0" hdg="0" length="10"><arc curvature="0.15707963267948966"/>'
        "</geometry></planView><lanes><laneSection s=\"0\"><right>"
        '<lane id="-1" type="driving"><width sOffset="0" a="3.5"/></lane>'
        "</right></laneSection></lanes></road>"
        '<road id="3"><planView><geometry s="0" x="10" y="0" hdg="0" length="10"><arc curvature="-0.15707963267948966"/>'
        "</geometry></planView><lanes><laneSection s=\"0\"><right>"
        '<lane id="-1" type="driving"><width sOffset="0" a="3.5"/></lane>'
        "</right></laneSection></lanes></road>"
        '<junction id="9">'
        '<connection id="left" incomingRoad="1" connectingRoad="2" contactPoint="start"><laneLink from="-1" to="-1"/></connection>'
        '<connection id="right" incomingRoad="1" connectingRoad="3" contactPoint="start"><laneLink from="-1" to="-1"/></connection>'
        "</junction></OpenDRIVE>"
    )


def test_run_returns_incomplete_without_direct_correspondence(tmp_path: Path) -> None:
    xodr = tmp_path / "map.xodr"
    xodr.write_text(_map(), encoding="utf-8")

    report = run(xodr)

    assert report["status"] == "INCOMPLETE"
    assert report["summary_metrics"]["no_osm_turn_data"] == 2


def test_cli_writes_report_and_optional_completeness_failure(tmp_path: Path) -> None:
    xodr = tmp_path / "map.xodr"
    report_path = tmp_path / "report.json"
    xodr.write_text(_map(), encoding="utf-8")

    assert main([str(xodr), "--out", str(report_path)]) == 0
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "INCOMPLETE"
    assert main([str(xodr), "--out", str(report_path), "--require-complete"]) == 1
