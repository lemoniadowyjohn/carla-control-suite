from ultimate_pipeline.quality.check_geometric_continuity import (
    check_geometric_continuity,
)
from ultimate_pipeline.quality.map_acceptance import build_map_acceptance


def test_map_acceptance_accepts_when_only_junction_connector_lane_offsets_present(tmp_path):
    """
    CODEX C6 re-baseline: geometric_continuity's `ok` flag now excludes
    junction-connector reference-line offsets (they are diagnostic, not
    genuine discontinuities -- see
    ultimate_pipeline/quality/check_geometric_continuity.py and
    reports/post_audit_hardening/C6_CONTINUITY_CHECKER.md). A map whose only
    "issues" are junction-connector lane-boundary offsets must be accepted
    by map_acceptance, not fail closed on ~27k false positives.
    """
    xodr = tmp_path / "gate.xodr"
    xodr.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        "<OpenDRIVE>"
        '<header revMajor="1" revMinor="6"/>'
        '<road id="1" length="10" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        "</road>"
        '<road id="100" length="5" junction="10">'
        '<link><predecessor elementType="road" elementId="1" contactPoint="end"/></link>'
        '<planView><geometry s="0" x="10" y="3.5" hdg="0" length="5"><line/></geometry></planView>'
        "</road>"
        '<junction id="10">'
        '<connection id="0" incomingRoad="1" connectingRoad="100" contactPoint="start">'
        '<laneLink from="-1" to="-1"/>'
        "</connection>"
        "</junction>"
        "</OpenDRIVE>",
        encoding="utf-8",
    )

    geom_report = check_geometric_continuity(str(xodr))
    assert geom_report["ok"] is True
    assert geom_report["num_junction_connector_issues"] == 1

    acceptance = build_map_acceptance({"geometric_continuity": geom_report}, run_id="run")

    assert acceptance["valid_for_experiments"] is True
    assert acceptance["failed_gates"] == []
    assert acceptance["metrics"]["geometric_continuity_ok"] is True


def test_map_acceptance_rejects_geometric_continuity_gate_decision_failure():
    acceptance = build_map_acceptance(
        {
            "geometric_continuity": {
                "decision": {
                    "pass": False,
                    "reason": "27193 offending segments exceed continuity thresholds",
                },
                "observed": {
                    "seam_distance_m": {"p95": 288.7, "max": 4666.0},
                },
            }
        },
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is False
    assert acceptance["failed_gates"] == ["geometric_continuity"]
    assert "27193 offending segments" in acceptance["hard_fail_reasons"][0]["reason"]
    assert acceptance["metrics"]["geometric_continuity_ok"] is False


def test_map_acceptance_accepts_successful_geometric_continuity_gate_decision():
    acceptance = build_map_acceptance(
        {
            "geometric_continuity": {
                "decision": {"pass": True, "reason": "ok"},
            }
        },
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    assert acceptance["metrics"]["geometric_continuity_ok"] is True


def test_map_acceptance_rejects_unresolved_lane_successor_autofix_report():
    acceptance = build_map_acceptance(
        {
            "lane_section_successors": {
                "broken_before_count": 10,
                "still_broken_count": 2,
                "strategy": "infer_from_road_links",
            }
        },
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is False
    assert acceptance["failed_gates"] == ["lane_section_successors"]
    assert acceptance["metrics"]["lane_successor_missing_count"] == 2


def test_map_acceptance_accepts_resolved_lane_successor_autofix_report():
    acceptance = build_map_acceptance(
        {
            "lane_section_successors": {
                "broken_before_count": 10565,
                "still_broken_count": 0,
                "strategy": "infer_from_road_links",
            }
        },
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    assert acceptance["metrics"]["lane_ok"] is True
    assert acceptance["metrics"]["lane_successor_missing_count"] == 0
