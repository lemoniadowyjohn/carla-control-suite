from __future__ import annotations

import json

import pytest


def _write_xodr(tmp_path, body: str, name: str = "map.xodr") -> str:
    path = tmp_path / name
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<header revMajor="1" revMinor="6"/>'
        f"{body}"
        "</OpenDRIVE>",
        encoding="utf-8",
    )
    return str(path)


# Two roads whose planView geometries are perfectly continuous (road 1 ends
# exactly where road 2 starts, same heading) -> zero issues expected.
_CONTINUOUS_BODY = """
<road name="r1" length="10.0" id="1" junction="-1">
  <link><successor elementType="road" elementId="2" contactPoint="start"/></link>
  <planView>
    <geometry s="0.0" x="0.0" y="0.0" hdg="0.0" length="10.0"><line/></geometry>
  </planView>
  <lanes><laneSection s="0.0"><center><lane id="0" type="driving" level="0"/></center></laneSection></lanes>
</road>
<road name="r2" length="10.0" id="2" junction="-1">
  <link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>
  <planView>
    <geometry s="0.0" x="10.0" y="0.0" hdg="0.0" length="10.0"><line/></geometry>
  </planView>
  <lanes><laneSection s="0.0"><center><lane id="0" type="driving" level="0"/></center></laneSection></lanes>
</road>
"""

# Same topology, but road 2 starts 5m away from where road 1 ends -> a real
# discontinuity that check_geometric_continuity must flag.
_BROKEN_BODY = """
<road name="r1" length="10.0" id="1" junction="-1">
  <link><successor elementType="road" elementId="2" contactPoint="start"/></link>
  <planView>
    <geometry s="0.0" x="0.0" y="0.0" hdg="0.0" length="10.0"><line/></geometry>
  </planView>
  <lanes><laneSection s="0.0"><center><lane id="0" type="driving" level="0"/></center></laneSection></lanes>
</road>
<road name="r2" length="10.0" id="2" junction="-1">
  <link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>
  <planView>
    <geometry s="0.0" x="15.0" y="0.0" hdg="0.0" length="10.0"><line/></geometry>
  </planView>
  <lanes><laneSection s="0.0"><center><lane id="0" type="driving" level="0"/></center></laneSection></lanes>
</road>
"""


def test_find_broken_roads_reports_no_issues_for_continuous_map(tmp_path, capsys):
    from ultimate_pipeline.dev_tools.tools.find_broken_roads import main

    xodr_path = _write_xodr(tmp_path, _CONTINUOUS_BODY)

    exit_code = main([xodr_path])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "No broken road links found" in out


def test_find_broken_roads_reports_issues_for_broken_map(tmp_path, capsys):
    from ultimate_pipeline.dev_tools.tools.find_broken_roads import main

    xodr_path = _write_xodr(tmp_path, _BROKEN_BODY)

    exit_code = main([xodr_path])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Broken road link" in out
    assert "from_road" not in out  # human-readable, not a raw dict dump
    assert "1" in out and "2" in out


def test_find_broken_roads_json_mode_emits_parseable_report(tmp_path, capsys):
    from ultimate_pipeline.dev_tools.tools.find_broken_roads import main

    xodr_path = _write_xodr(tmp_path, _BROKEN_BODY)

    exit_code = main([xodr_path, "--json"])

    out = capsys.readouterr().out
    assert exit_code == 1
    report = json.loads(out)
    assert report["ok"] is False
    # The gap is flagged from both directions: road 1's successor link to
    # road 2, and road 2's predecessor link back to road 1.
    assert report["num_issues"] == 2
    from_roads = {issue["from_road"] for issue in report["issues"]}
    to_roads = {issue["to_road"] for issue in report["issues"]}
    assert from_roads == {"1", "2"}
    assert to_roads == {"1", "2"}


def test_find_broken_roads_requires_xodr_argument(capsys):
    from ultimate_pipeline.dev_tools.tools.find_broken_roads import main

    # argparse's standard behavior for a missing required positional: print
    # usage to stderr and sys.exit(2).
    with pytest.raises(SystemExit) as excinfo:
        main([])

    err = capsys.readouterr().err
    assert excinfo.value.code == 2
    assert "usage" in err.lower() or "xodr" in err.lower()


def test_find_broken_roads_underlying_helper_returns_report_dict(tmp_path):
    from ultimate_pipeline.dev_tools.tools.find_broken_roads import find_broken_roads

    xodr_path = _write_xodr(tmp_path, _BROKEN_BODY)

    report = find_broken_roads(xodr_path)

    assert report["ok"] is False
    assert report["num_issues"] == 2


def test_scan_for_discontinuities_delegates_to_corrected_checker(tmp_path):
    """
    MeshContinuityRepairer.scan_for_discontinuities() was a dead `pass` stub
    with zero callers in the canonical tree. Rather than leaving it dead or
    reimplementing a second, parallel continuity scanner, it now redirects to
    the same C6-corrected checker used by the CLI and by stage_06_links.py's
    quality gate, returning the report dict (previously it silently returned
    None).
    """
    from ultimate_pipeline.geometry.mesh_continuity_repairer import MeshContinuityRepairer

    xodr_path = _write_xodr(tmp_path, _BROKEN_BODY)
    repairer = MeshContinuityRepairer(xodr_path)

    report = repairer.scan_for_discontinuities()

    assert report is not None
    assert report["ok"] is False
    assert report["num_issues"] == 2
    from_roads = {issue["from_road"] for issue in report["issues"]}
    assert from_roads == {"1", "2"}


def test_scan_for_discontinuities_ok_for_continuous_map(tmp_path):
    from ultimate_pipeline.geometry.mesh_continuity_repairer import MeshContinuityRepairer

    xodr_path = _write_xodr(tmp_path, _CONTINUOUS_BODY)
    repairer = MeshContinuityRepairer(xodr_path)

    report = repairer.scan_for_discontinuities()

    assert report["ok"] is True
    assert report["num_issues"] == 0
