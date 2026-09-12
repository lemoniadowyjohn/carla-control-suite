# REFAC_VERSION = "v1_c10"
# C10: offline map-hygiene repairs wired into the pipeline (islands,
# degenerate lanes, genuine z-seams). See quality/map_hygiene.py.
#
# NOTE: This file is auto-extracted from ultimate_pipeline/main_pipeline.py.
# It delegates to original helpers by injecting main_pipeline globals at runtime.

from __future__ import annotations

import os


def _inject_main_pipeline_globals():
    # Import is inside to avoid import-time side effects/cycles.
    from ultimate_pipeline import main_pipeline as _mp  # type: ignore
    g = globals()
    for k, v in _mp.__dict__.items():
        if k.startswith("__"):
            continue
        if k in ("_inject_main_pipeline_globals",):
            continue
        g.setdefault(k, v)


def _step8h_map_hygiene(self, final_out: str) -> str:
    """Apply C10 offline map-hygiene repairs to the final XODR (post
    junction-link patch) and return the repaired artifact path.

    Order matters: island quarantine may delete roads (so it runs first,
    when references are fewest), then degenerate-lane flooring, then
    z-seam chaining (uses C9's corrected elevation-continuity checker for
    before/after). Each repair writes its own artifact + JSON report so the
    run is fully auditable and reversible. If a repair decides it cannot
    act safely, the input artifact is kept and the reason is recorded.
    """
    _inject_main_pipeline_globals()
    import json
    from pathlib import Path as _Path

    if not bool(getattr(self.settings, "ENABLE_MAP_HYGIENE", True)):
        print("[STEP 8H] Map hygiene disabled (ENABLE_MAP_HYGIENE=false).")
        return str(final_out)

    print("\n============== 🧹 STEP 8H: Map hygiene (C10) ==============")
    from ultimate_pipeline.quality.map_hygiene import (
        quarantine_island_roads,
        repair_degenerate_lanes,
        repair_lane_width_discontinuities,
        repair_true_zseams,
    )

    out_dir = _Path(self.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    input_path = _Path(str(final_out))
    if not input_path.is_file():
        raise FileNotFoundError(
            f"[STEP 8H] Input XODR missing for map hygiene: {input_path}"
        )

    reports: dict = {}

    # ---- 8H-1: island quarantine --------------------------------------
    island_out = out_dir / "08h1_island_quarantined.xodr"
    island_report = quarantine_island_roads(
        str(input_path), str(island_out)
    )
    total_roads = int(island_report.get("total_roads", 0) or 0)
    quarantined_count = int(island_report.get("count", 0) or 0)
    max_fraction = float(
        os.getenv("UP_MAP_HYGIENE_MAX_QUARANTINE_FRACTION", "0.25")
    )
    if total_roads > 0 and quarantined_count > int(max_fraction * total_roads):
        # Safety valve: quarantine removing >25% of the map smells like a
        # broken connectivity graph, not real islands. Keep the input.
        island_report["action"] = "skipped_suspicious_fraction"
        island_report["skipped_reason"] = (
            f"quarantine would remove {quarantined_count}/{total_roads} roads "
            f"(>{max_fraction:.0%}); connectivity graph likely broken"
        )
        reports["island_quarantine"] = island_report
        print(f"⚠️ [STEP 8H] {island_report['skipped_reason']}")
        current_path = input_path
    else:
        island_report["action"] = "applied"
        reports["island_quarantine"] = island_report
        current_path = island_out
        print(
            f"[STEP 8H] Islands quarantined: {quarantined_count} roads "
            f"(components {island_report.get('component_sizes_before')})"
        )

    # ---- 8H-2: degenerate-lane floor repair ----------------------------
    lanes_out = out_dir / "08h2_degenerate_lanes_repaired.xodr"
    lane_report = repair_degenerate_lanes(str(current_path), str(lanes_out))
    reports["degenerate_lanes"] = lane_report
    current_path = lanes_out
    print(
        f"[STEP 8H] Degenerate lanes repaired: "
        f"{int(lane_report.get('repaired_count', 0) or 0)}"
    )

    # ---- 8H-3: genuine z-seam chaining ---------------------------------
    zseam_out = out_dir / "08h3_zseams_repaired.xodr"
    zseam_report = repair_true_zseams(str(current_path), str(zseam_out))
    reports["true_zseams"] = zseam_report
    current_path = zseam_out
    print(
        f"[STEP 8H] Genuine z-seams: before="
        f"{int(zseam_report.get('issues_before', 0) or 0)} after="
        f"{int(zseam_report.get('issues_after', 0) or 0)} "
        f"(roads modified={int(zseam_report.get('roads_modified', 0) or 0)})"
    )

    # ---- 8H-4: lane-width discontinuity repair --------------------------
    lane_width_out = out_dir / "08h4_lane_width_discontinuities_repaired.xodr"
    lane_width_report = repair_lane_width_discontinuities(
        str(current_path), str(lane_width_out)
    )
    reports["lane_width_discontinuities"] = lane_width_report
    current_path = lane_width_out
    print(
        f"[STEP 8H] Lane-width discontinuities: before="
        f"{int(lane_width_report.get('issues_before', 0) or 0)} after="
        f"{int(lane_width_report.get('issues_after', 0) or 0)} "
        f"(roads modified={len(lane_width_report.get('roads_modified', []) or [])})"
    )

    # ---- 8H-5: G6 junction lane-coverage repair (advisory-first) --------
    # Converges an uncovered driving lane onto its already-routed
    # neighbour's existing junction target -- reuses real connector
    # geometry, does not fabricate new connections. Transactional: only
    # committed if repair_issues is empty AND the post-repair G6 audit is
    # fully clean; otherwise the input is kept unchanged and the reason is
    # recorded. Advisory-first per this session's adversarial review of this
    # exact repair: the isolated-component delta and lateral-merge-distance
    # distribution are surfaced for a human to inspect, but this step never
    # fails the hygiene stage (this defect class has been tolerated
    # throughout this map's history; characterizing its resolution should
    # not itself become a new blocker). Off unless explicitly opted in,
    # matching this stage's existing convention for geometry-mutating repairs.
    g6_coverage_enabled = os.getenv(
        "UP_ENABLE_G6_LANE_COVERAGE_REPAIR", "0"
    ).strip().lower() in ("1", "true", "yes", "on")
    if g6_coverage_enabled:
        try:
            import copy as _copy
            import xml.etree.ElementTree as _ET

            from ultimate_pipeline.tools.phase_g6_junction_lanelinks import (
                audit_junction_lanelinks,
                checks_of,
                compute_repair_lateral_distances,
                repair_coverage_gaps,
            )
            from ultimate_pipeline.quality.map_acceptance import (
                component_reachability_summary,
            )

            g6_tree_before = _ET.parse(str(current_path))
            g6_root_before = g6_tree_before.getroot()
            components_before = component_reachability_summary(g6_root_before)

            candidate_root = _copy.deepcopy(g6_root_before)
            repair = repair_coverage_gaps(candidate_root)
            post_audit = audit_junction_lanelinks(candidate_root)
            post_checks = checks_of(post_audit)
            clean = bool(repair["repair_issues"] == [] and all(post_checks.values()))

            distances = compute_repair_lateral_distances(
                candidate_root, repair["added_lanelinks"]
            )
            measured = sorted(
                d["distance_m"] for d in distances if d["distance_m"] is not None
            )
            # 2x a typical driving-lane width (this map's lanes are
            # predominantly 3.5m -- see quality_gate_manager's own
            # drivable-width percentiles) as a reasoned "look closer" flag,
            # not a pass/fail threshold.
            flag_threshold_m = 7.0
            flagged = [
                d for d in distances
                if d["distance_m"] is not None and d["distance_m"] > flag_threshold_m
            ]

            g6_out = out_dir / "08h5_g6_lane_coverage_repaired.xodr"
            if clean and repair["added_lanelinks"]:
                _ET.ElementTree(candidate_root).write(
                    str(g6_out), encoding="utf-8", xml_declaration=True
                )
                components_after = component_reachability_summary(candidate_root)
                current_path = g6_out
                applied = True
            else:
                components_after = components_before
                applied = False

            g6_report = {
                "ok": True,  # advisory -- never fails this stage
                "applied": applied,
                "added_lanelinks_count": len(repair["added_lanelinks"]),
                "repair_issues_count": len(repair["repair_issues"]),
                "post_repair_audit_clean": clean,
                "isolated_lane_component_count_before": (
                    (components_before or {}).get("isolated_lane_component_count")
                ),
                "isolated_lane_component_count_after": (
                    (components_after or {}).get("isolated_lane_component_count")
                ),
                "lateral_merge_distance_m": {
                    "measured_count": len(measured),
                    "unmeasured_count": len(distances) - len(measured),
                    "min": measured[0] if measured else None,
                    "median": measured[len(measured) // 2] if measured else None,
                    "max": measured[-1] if measured else None,
                    "flag_threshold_m": flag_threshold_m,
                    "flagged_count": len(flagged),
                },
                "repairs": distances,
            }
            reports["g6_lane_coverage_repair"] = g6_report
            g6_report_path = out_dir / "08h5_g6_lane_coverage_repair_report.json"
            g6_report_path.write_text(
                json.dumps(g6_report, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
            print(
                "[STEP 8H] G6 lane-coverage repair: "
                f"applied={applied} added={len(repair['added_lanelinks'])} "
                f"isolated_components {g6_report['isolated_lane_component_count_before']}"
                f" -> {g6_report['isolated_lane_component_count_after']} "
                f"-> {g6_report_path}"
            )
        except Exception as e:
            print(f"[STEP 8H] G6 lane-coverage repair failed (continuing, advisory-only): {e}")
            g6_report = {
                "ok": True,
                "status": "INCOMPLETE",
                "applied": False,
                "reason": "repair_exception",
                "error": str(e),
            }
            reports["g6_lane_coverage_repair"] = g6_report
            g6_report_path = out_dir / "08h5_g6_lane_coverage_repair_report.json"
            g6_report_path.write_text(
                json.dumps(g6_report, indent=2, sort_keys=True), encoding="utf-8"
            )
    else:
        print("[STEP 8H] G6 lane-coverage repair disabled.")

    combined = {
        "ok": all(bool(r.get("ok", True)) for r in reports.values()),
        "input_xodr": str(input_path),
        "output_xodr": str(current_path),
        "stages": reports,
    }
    combined_path = out_dir / "map_hygiene_report.json"
    try:
        combined_path.write_text(
            json.dumps(combined, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"[STEP 8H] map_hygiene_report.json write failed: {exc}")
    print(f"[STEP 8H] map_hygiene_report.json -> {combined_path}")

    self.map_hygiene_report = combined
    return str(current_path)
