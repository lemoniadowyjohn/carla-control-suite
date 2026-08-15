from ultimate_pipeline.quality.map_acceptance import build_map_acceptance


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
