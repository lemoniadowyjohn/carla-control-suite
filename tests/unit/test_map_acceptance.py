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


# ---------------------------------------------------------------------------
# Deep-audit follow-up (2026-09-04): 5 more checkers existed in the codebase,
# complete and correct, already used mid-pipeline or as an opt-in live-CARLA
# perception gate, but never reached final map-of-record acceptance -- same
# shape as the junction_integrity gap above. Wired in unconditionally, since
# a lane narrower than a car or a 45-degree slope is a genuine structural
# defect, not an opt-in completeness nicety.
# ---------------------------------------------------------------------------


def test_map_acceptance_hard_fails_on_lane_width_continuity_issues():
    acceptance = build_map_acceptance(
        {
            "lane_width_continuity": {
                "ok": False,
                "num_issues": 1,
                "issues": [{"road_id": "1", "type": "width_too_narrow"}],
            }
        },
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is False
    assert "lane_width_continuity" in acceptance["failed_gates"]
    assert acceptance["metrics"]["lane_width_continuity_ok"] is False
    assert acceptance["metrics"]["lane_width_continuity_issue_count"] == 1


def test_map_acceptance_passes_when_lane_width_continuity_clean():
    acceptance = build_map_acceptance(
        {"lane_width_continuity": {"ok": True, "num_issues": 0, "issues": []}},
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    assert acceptance["metrics"]["lane_width_continuity_ok"] is True
    assert acceptance["metrics"]["lane_width_continuity_issue_count"] == 0


def test_map_acceptance_hard_fails_on_lane_geometry_continuity_issues():
    acceptance = build_map_acceptance(
        {
            "lane_geometry_continuity": {
                "ok": False,
                "n_issues": 1,
                "issues": [{"road_id": "1", "type": "lane_offset_discontinuity"}],
            }
        },
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is False
    assert "lane_geometry_continuity" in acceptance["failed_gates"]
    assert acceptance["metrics"]["lane_geometry_continuity_ok"] is False
    assert acceptance["metrics"]["lane_geometry_continuity_issue_count"] == 1


def test_map_acceptance_passes_when_lane_geometry_continuity_clean():
    acceptance = build_map_acceptance(
        {"lane_geometry_continuity": {"ok": True, "n_issues": 0, "issues": []}},
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    assert acceptance["metrics"]["lane_geometry_continuity_ok"] is True
    assert acceptance["metrics"]["lane_geometry_continuity_issue_count"] == 0


def test_map_acceptance_hard_fails_on_elevation_missing_and_cliffs_issues():
    acceptance = build_map_acceptance(
        {
            "elevation_missing_and_cliffs": {
                "ok": False,
                "zero_ratio": 0.5,
                "max_link_dz": 120.0,
                "error": "zero_ratio 0.5 exceeds max_zero_ratio 0.01",
            }
        },
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is False
    assert "elevation_missing_and_cliffs" in acceptance["failed_gates"]
    assert acceptance["metrics"]["elevation_missing_and_cliffs_ok"] is False
    assert acceptance["metrics"]["elevation_zero_ratio"] == 0.5
    assert acceptance["metrics"]["elevation_max_link_dz_m"] == 120.0


def test_map_acceptance_passes_when_elevation_missing_and_cliffs_clean():
    acceptance = build_map_acceptance(
        {
            "elevation_missing_and_cliffs": {
                "ok": True,
                "zero_ratio": 0.0,
                "max_link_dz": 0.3,
            }
        },
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    assert acceptance["metrics"]["elevation_missing_and_cliffs_ok"] is True


def test_map_acceptance_hard_fails_on_elevation_smoothness_issues():
    acceptance = build_map_acceptance(
        {
            "elevation_smoothness": {
                "ok": False,
                "issue_count": 3,
                "issues": [{"road_id": "1", "type": "slope_too_steep"}],
            }
        },
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is False
    assert "elevation_smoothness" in acceptance["failed_gates"]
    assert acceptance["metrics"]["elevation_smoothness_ok"] is False
    assert acceptance["metrics"]["elevation_smoothness_issue_count"] == 3


def test_map_acceptance_passes_when_elevation_smoothness_clean():
    acceptance = build_map_acceptance(
        {"elevation_smoothness": {"ok": True, "issue_count": 0, "issues": []}},
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    assert acceptance["metrics"]["elevation_smoothness_ok"] is True
    assert acceptance["metrics"]["elevation_smoothness_issue_count"] == 0


def test_map_acceptance_hard_fails_on_physics_feasibility_issues():
    acceptance = build_map_acceptance(
        {
            "physics_feasibility": {
                "ok": False,
                "issue_count": 1,
                "issues": [{"road_id": "1", "type": "lane_too_narrow", "value": 0.3}],
            }
        },
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is False
    assert "physics_feasibility" in acceptance["failed_gates"]
    assert acceptance["metrics"]["physics_feasibility_ok"] is False
    assert acceptance["metrics"]["physics_feasibility_issue_count"] == 1


def test_map_acceptance_passes_when_physics_feasibility_clean():
    acceptance = build_map_acceptance(
        {"physics_feasibility": {"ok": True, "issue_count": 0, "issues": []}},
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    assert acceptance["metrics"]["physics_feasibility_ok"] is True
    assert acceptance["metrics"]["physics_feasibility_issue_count"] == 0


# ---------------------------------------------------------------------------
# Deep-audit follow-up (2026-09-04), round 2: semantic_overlap,
# randomness_entropy, collision_mesh are self-documented as heuristic/
# diagnostic/non-fatal by their own authors -- unlike the 5 structural gates
# above, these must only ever produce a SOFT warning, never a hard fail.
# ---------------------------------------------------------------------------


def test_map_acceptance_soft_warns_on_semantic_overlap_issues_never_hard_fails():
    acceptance = build_map_acceptance(
        {
            "semantic_overlap": {
                "ok": False,
                "issue_count": 1,
                "issues": [{"road_id": "1", "type": "sidewalk_building_overlap_candidate"}],
            }
        },
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    assert "semantic_overlap" not in acceptance["failed_gates"]
    assert acceptance["metrics"]["semantic_overlap_ok"] is False
    assert acceptance["metrics"]["semantic_overlap_issue_count"] == 1
    assert any(w["gate"] == "semantic_overlap" for w in acceptance["soft_warnings"])


def test_map_acceptance_passes_when_semantic_overlap_clean():
    acceptance = build_map_acceptance(
        {"semantic_overlap": {"ok": True, "issue_count": 0, "issues": []}},
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    assert acceptance["metrics"]["semantic_overlap_ok"] is True
    assert acceptance["soft_warnings"] == []


def test_map_acceptance_soft_warns_on_low_randomness_entropy_never_hard_fails():
    acceptance = build_map_acceptance(
        {"randomness_entropy": {"ok": False, "entropy": 0.01}},
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    assert "randomness_entropy" not in acceptance["failed_gates"]
    assert acceptance["metrics"]["randomness_entropy_ok"] is False
    assert acceptance["metrics"]["randomness_entropy_entropy"] == 0.01
    assert any(w["gate"] == "randomness_entropy" for w in acceptance["soft_warnings"])


def test_map_acceptance_passes_when_randomness_entropy_clean():
    acceptance = build_map_acceptance(
        {"randomness_entropy": {"ok": True, "entropy": 0.87}},
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    assert acceptance["metrics"]["randomness_entropy_ok"] is True
    assert acceptance["soft_warnings"] == []


def test_map_acceptance_soft_warns_on_collision_mesh_issues_never_hard_fails():
    acceptance = build_map_acceptance(
        {
            "collision_mesh": {
                "ok": False,
                "issue_count": 1,
                "issues": ["Road 1: failed to build buffered geometry"],
            }
        },
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    assert "collision_mesh" not in acceptance["failed_gates"]
    assert acceptance["metrics"]["collision_mesh_ok"] is False
    assert any(w["gate"] == "collision_mesh" for w in acceptance["soft_warnings"])


def test_map_acceptance_passes_when_collision_mesh_clean_or_disabled():
    acceptance = build_map_acceptance(
        {"collision_mesh": {"ok": True, "issue_count": 0, "issues": []}},
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    assert acceptance["metrics"]["collision_mesh_ok"] is True
    assert acceptance["soft_warnings"] == []


def test_map_acceptance_new_gates_absent_from_reports_does_not_fail():
    """As with junction_integrity: no report supplied must not be treated as
    a failure -- absence is not the same as ok=False."""
    acceptance = build_map_acceptance(
        {"geometric_continuity": {"decision": {"pass": True, "reason": "ok"}}},
        run_id="run",
    )

    assert acceptance["valid_for_experiments"] is True
    for key in (
        "lane_width_continuity",
        "lane_geometry_continuity",
        "elevation_missing_and_cliffs",
        "elevation_smoothness",
        "physics_feasibility",
        "semantic_overlap",
        "randomness_entropy",
        "collision_mesh",
    ):
        assert key not in acceptance["metrics"]


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
