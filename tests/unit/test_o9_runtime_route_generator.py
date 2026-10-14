"""Tests for O9 deterministic runtime route generator."""
from __future__ import annotations

import json
from pathlib import Path

from tools.runtime_route_generator import generate_routes


def _map(path: Path) -> Path:
    path.write_text("""<OpenDRIVE>
<road id="1" junction="-1" length="10"><planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView><lanes><laneSection s="0"><right><lane id="-1" type="driving"><width sOffset="0" a="3" b="0" c="0" d="0"/></lane></right></laneSection></lanes></road>
<road id="2" junction="1" length="5"><planView><geometry s="0" x="10" y="0" hdg="0" length="5"><line/></geometry></planView><lanes><laneSection s="0"><right><lane id="-1" type="driving"><width sOffset="0" a="3" b="0" c="0" d="0"/></lane></right></laneSection></lanes></road>
<junction id="1"><connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start"/></junction>
</OpenDRIVE>""", encoding="utf-8")
    return path


def test_routes_are_deterministic_and_bound_to_sha(tmp_path: Path):
    p = _map(tmp_path / "map.xodr")
    a = generate_routes(p, "a" * 64)
    b = generate_routes(p, "a" * 64)
    assert a["routes"] == b["routes"]
    assert all(route["source_map_sha256"] == "a" * 64 for route in a["routes"])


def test_missing_categories_are_incomplete(tmp_path: Path):
    p = _map(tmp_path / "map.xodr")
    report = generate_routes(p, "a" * 64)
    assert report["status"] == "INCOMPLETE"
    assert "roundabout" in report["missing_categories"]


def test_gap026_routes_are_diagnostic_only(tmp_path: Path):
    p = _map(tmp_path / "map.xodr")
    report = generate_routes(p, "a" * 64)
    gap = [r for r in report["routes"] if r["category"] == "gap026_severe_candidate"]
    assert all(r["diagnostic_only"] for r in gap)


def test_route_output_serializes(tmp_path: Path):
    json.dumps(generate_routes(_map(tmp_path / "map.xodr"), "a" * 64), sort_keys=True)
