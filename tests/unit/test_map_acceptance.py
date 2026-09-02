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


# ---------------------------------------------------------------------------
# junction_integrity gate wiring
#
# WS1.4 follow-up (2026-09-02): _measure_acceptance()'s gate set never ran
# JunctionIntegrityGate at all, so a real regen's hygiene-corrected candidate
# with 28 dangling junction-connection references (produced by a separate,
# now-fixed map_hygiene.py bug) still measured valid_for_experiments=True.
# Wire it in unconditionally (like geometric_continuity/lane_connectivity),
# not behind an opt-in flag, since dangling junction references are a
# structural defect a "valid" map should never have.
# ---------------------------------------------------------------------------


def test_map_acceptance_hard_fails_on_junction_integrity_issues():
    acceptance = build_map_acceptance(
        {
            "junction_integrity": {
                "ok": False,
                "issue_count": 2,
                "issues": [
                    {"type": "missing_incoming_road", "junction_id": "500", "connection_id": "0"},
                    {"type": "missing_connecting_road", "junction_id": "500", "connection_id": "0"},
                ],
            }
        },
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is False
    assert "junction_integrity" in acceptance["failed_gates"]
    assert acceptance["metrics"]["junction_integrity_ok"] is False
    assert acceptance["metrics"]["junction_integrity_issue_count"] == 2


def test_map_acceptance_passes_when_junction_integrity_clean():
    acceptance = build_map_acceptance(
        {
            "junction_integrity": {"ok": True, "issue_count": 0, "issues": []},
        },
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    assert acceptance["metrics"]["junction_integrity_ok"] is True
    assert acceptance["metrics"]["junction_integrity_issue_count"] == 0


def test_map_acceptance_junction_integrity_absent_from_reports_does_not_fail():
    """No report supplied (e.g. a caller that hasn't run the gate yet) must
    not be treated as a failure -- absence is not the same as ok=False."""
    acceptance = build_map_acceptance(
        {"geometric_continuity": {"decision": {"pass": True, "reason": "ok"}}},
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    assert "junction_integrity" not in acceptance["metrics"]


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


# --------------------------------------------------------------------------
# CODEX C7: enrichment completeness (buildings + functional signals) metrics
# --------------------------------------------------------------------------

_XODR_NO_ENRICHMENT = (
    '<?xml version="1.0" encoding="utf-8"?>'
    "<OpenDRIVE>"
    '<header revMajor="1" revMinor="6"/>'
    '<road id="1" length="10" junction="-1">'
    '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
    "</road>"
    "</OpenDRIVE>"
)

_XODR_WITH_ENRICHMENT = (
    '<?xml version="1.0" encoding="utf-8"?>'
    "<OpenDRIVE>"
    '<header revMajor="1" revMinor="6"/>'
    '<road id="1" length="10" junction="-1">'
    '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
    "<objects>"
    '<object id="b1" type="building" s="1" t="1" zOffset="0" height="10"/>'
    '<object id="b2" type="building" s="2" t="1" zOffset="0" height="10"/>'
    '<object id="tl1" type="traffic_light" s="3" t="0" zOffset="0" height="5" dynamic="no"/>'
    "</objects>"
    "<signals>"
    '<signal id="s1" s="3" t="0" zOffset="5" hOffset="0" dynamic="yes" type="1000001" subtype="-1"/>'
    "</signals>"
    "</road>"
    "</OpenDRIVE>"
)


def test_map_acceptance_reports_zero_buildings_and_signals_metrics(tmp_path):
    xodr = tmp_path / "no_enrichment.xodr"
    xodr.write_text(_XODR_NO_ENRICHMENT, encoding="utf-8")

    acceptance = build_map_acceptance({}, run_id="run", final_xodr_path=str(xodr))

    assert acceptance["metrics"]["buildings_count"] == 0
    assert acceptance["metrics"]["functional_signals_count"] == 0
    assert acceptance["metrics"]["traffic_light_object_count"] == 0


def test_map_acceptance_counts_buildings_and_functional_signals(tmp_path):
    xodr = tmp_path / "enriched.xodr"
    xodr.write_text(_XODR_WITH_ENRICHMENT, encoding="utf-8")

    acceptance = build_map_acceptance({}, run_id="run", final_xodr_path=str(xodr))

    assert acceptance["metrics"]["buildings_count"] == 2
    assert acceptance["metrics"]["functional_signals_count"] == 1
    assert acceptance["metrics"]["traffic_light_object_count"] == 1


def test_map_acceptance_does_not_hard_fail_on_empty_enrichment_by_default(tmp_path):
    """Manual/geometry-only reference maps legitimately have 0 buildings/signals
    in the OpenDRIVE sense -- must not break existing manual-map acceptance."""
    xodr = tmp_path / "no_enrichment.xodr"
    xodr.write_text(_XODR_NO_ENRICHMENT, encoding="utf-8")

    acceptance = build_map_acceptance({}, run_id="run", final_xodr_path=str(xodr))

    assert acceptance["valid_for_experiments"] is True
    assert acceptance["failed_gates"] == []


def test_map_acceptance_hard_fails_on_zero_buildings_when_enrichment_required(tmp_path):
    xodr = tmp_path / "no_enrichment.xodr"
    xodr.write_text(_XODR_NO_ENRICHMENT, encoding="utf-8")

    acceptance = build_map_acceptance(
        {}, run_id="run", final_xodr_path=str(xodr), require_enrichment=True
    )

    assert acceptance["valid_for_experiments"] is False
    assert "enrichment_completeness" in acceptance["failed_gates"]


def test_map_acceptance_hard_fails_on_zero_functional_signals_when_required(tmp_path):
    # Neither <signal> nor the <object type="traffic_light"> fallback is
    # present -- zero light representation of any kind must hard-fail.
    xodr_text = (
        _XODR_WITH_ENRICHMENT.replace(
            '<signal id="s1" s="3" t="0" zOffset="5" hOffset="0" dynamic="yes" type="1000001" subtype="-1"/>',
            "",
        ).replace(
            '<object id="tl1" type="traffic_light" s="3" t="0" zOffset="0" height="5" dynamic="no"/>',
            "",
        )
    )
    xodr = tmp_path / "buildings_only.xodr"
    xodr.write_text(xodr_text, encoding="utf-8")

    acceptance = build_map_acceptance(
        {}, run_id="run", final_xodr_path=str(xodr), require_enrichment=True
    )

    assert acceptance["valid_for_experiments"] is False
    assert "enrichment_completeness" in acceptance["failed_gates"]


def test_map_acceptance_hard_fails_when_signal_absent_and_light_kept_as_prop_only(tmp_path):
    """If traffic lights remain <object>-only (no paired <signal>), that is
    still evidence of light presence per the C7 spec's counting rule ('if
    lights remain <object>, count <object type=traffic_light>') -- it must
    NOT hard-fail the enrichment gate on its own."""
    xodr_text = _XODR_WITH_ENRICHMENT.replace(
        '<signal id="s1" s="3" t="0" zOffset="5" hOffset="0" dynamic="yes" type="1000001" subtype="-1"/>',
        "",
    )
    xodr = tmp_path / "object_only_light.xodr"
    xodr.write_text(xodr_text, encoding="utf-8")

    acceptance = build_map_acceptance(
        {}, run_id="run", final_xodr_path=str(xodr), require_enrichment=True
    )

    assert acceptance["valid_for_experiments"] is True
    assert "enrichment_completeness" not in acceptance["failed_gates"]


def test_map_acceptance_passes_enrichment_gate_when_buildings_and_signals_present(tmp_path):
    xodr = tmp_path / "enriched.xodr"
    xodr.write_text(_XODR_WITH_ENRICHMENT, encoding="utf-8")

    acceptance = build_map_acceptance(
        {}, run_id="run", final_xodr_path=str(xodr), require_enrichment=True
    )

    assert acceptance["valid_for_experiments"] is True
    assert "enrichment_completeness" not in acceptance["failed_gates"]


def test_map_acceptance_counts_traffic_light_objects_as_signals_fallback(tmp_path):
    """If lights remain <object> (no <signal> emitted for some reason), the
    traffic_light_object_count metric must still be visible/non-zero so the
    map is not falsely reported as having zero light representation."""
    xodr_text = _XODR_WITH_ENRICHMENT.replace(
        '<signal id="s1" s="3" t="0" zOffset="5" hOffset="0" dynamic="yes" type="1000001" subtype="-1"/>',
        "",
    )
    xodr = tmp_path / "objects_only.xodr"
    xodr.write_text(xodr_text, encoding="utf-8")

    acceptance = build_map_acceptance({}, run_id="run", final_xodr_path=str(xodr))

    assert acceptance["metrics"]["functional_signals_count"] == 0
    assert acceptance["metrics"]["traffic_light_object_count"] == 1
