# REFAC_VERSION = "v5_preserve"
# NOTE: This file is auto-extracted from ultimate_pipeline/main_pipeline.py.
# It delegates to original helpers by injecting main_pipeline globals at runtime.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from ultimate_pipeline.quality.lane_width_invariants import (
    default_report_path,
    enforce_lane_width_invariants,
)
from ultimate_pipeline.tools.carla_visual_smoke_gate import evaluate_visual_smoke_report
from ultimate_pipeline.utils.file_hashing import safe_sha256_file


def _inject_main_pipeline_globals():
    # Import is inside to avoid import-time side effects/cycles.
    from ultimate_pipeline import main_pipeline as _mp  # type: ignore
    g = globals()
    for k, v in _mp.__dict__.items():
        if k.startswith("__"):
            continue
        if k in ("_inject_main_pipeline_globals",):
            continue
        # Don't overwrite locally-defined names (e.g., stage functions).
        g.setdefault(k, v)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _load_junction_connector_risk(out_dir: str) -> Dict[str, Any]:
    risk_path = Path(out_dir) / "junction_connector_risk.json"
    if not risk_path.exists():
        return {
            "available": False,
            "path": str(risk_path),
            "ok": None,
            "failed_check_count": 0,
            "overlap_pair_count": 0,
            "worst_junction_sample": [],
        }

    try:
        data = json.loads(risk_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "available": False,
            "path": str(risk_path),
            "ok": None,
            "failed_check_count": 0,
            "overlap_pair_count": 0,
            "worst_junction_sample": [],
            "error": str(exc),
        }

    worst = (
        data.get("worst_junction_sample")
        or data.get("worst_junction_ids")
        or data.get("worst_junctions")
        or []
    )
    if isinstance(worst, dict):
        worst_sample = list(worst.values())[:10]
    elif isinstance(worst, list):
        worst_sample = worst[:10]
    else:
        worst_sample = [worst]

    return {
        "available": True,
        "path": str(risk_path),
        "ok": data.get("ok"),
        "failed_check_count": _safe_int(
            data.get("failed_check_count", data.get("n_failed_checks", 0))
        ),
        "overlap_pair_count": _safe_int(
            data.get(
                "overlap_pair_count",
                data.get(
                    "buffered_connector_overlap_pair_count",
                    data.get("overlap_pairs", 0),
                ),
            )
        ),
        "worst_junction_sample": worst_sample,
    }


def _enforce_final_lane_width_invariants(final_out: str, out_dir: str) -> Dict[str, Any]:
    report_path = default_report_path(out_dir, "08_final_selected")
    report = enforce_lane_width_invariants(
        final_out,
        report_path=report_path,
        stage="08_final_selected",
    )
    totals = report.get("totals", {})
    print(
        "[STEP 8] Final lane width invariants: "
        f"found={totals.get('missing_width_lanes_found', 0)} "
        f"fixed={totals.get('missing_width_lanes_fixed', 0)} -> {report_path}"
    )
    if report.get("severity") == "fail":
        raise RuntimeError(
            "Final lane width invariant enforcement failed; "
            f"see {report_path}"
        )
    return report


def _write_final_selected_xodr_status(final_out: str, out_dir: str) -> Dict[str, Any]:
    risk = _load_junction_connector_risk(out_dir)
    visual_gate_path = Path(out_dir) / "final_visual_smoke" / "carla_visual_smoke_gate.json"
    visual_gate = {
        "ok": False,
        "status": "missing",
        "reason": "carla_visual_smoke_gate_missing",
    }
    if visual_gate_path.exists():
        try:
            visual_payload = json.loads(visual_gate_path.read_text(encoding="utf-8"))
            visual_eval = evaluate_visual_smoke_report(visual_payload, require_files=False)
            visual_gate = {
                "ok": bool(visual_eval.get("ok", False)),
                "status": "pass" if bool(visual_eval.get("ok", False)) else "fail",
                "reason": str(visual_eval.get("reason") or ""),
            }
        except Exception as exc:
            visual_gate = {
                "ok": False,
                "status": "invalid",
                "reason": str(exc),
            }
    status = {
        "schema": "final_selected_xodr_status_v1",
        "selected_xodr_path": str(final_out),
        "sha256": safe_sha256_file(final_out),
        "junction_connector_risk_ok": risk.get("ok"),
        "failed_check_count": _safe_int(risk.get("failed_check_count", 0)),
        "overlap_pair_count": _safe_int(risk.get("overlap_pair_count", 0)),
        "worst_junction_sample": risk.get("worst_junction_sample", []),
        "junction_connector_risk_report_path": risk.get("path"),
        "junction_connector_risk_report_available": bool(risk.get("available")),
        "CARLA_VISUAL_READY": "yes" if bool(visual_gate.get("ok", False)) else "no",
        "PERCEPTION_READY": "no",
        "perception_gate_reason": (
            ""
            if bool(visual_gate.get("ok", False))
            else "blocked_until_carla_visual_smoke_gate_passes"
        ),
        "carla_visual_smoke_gate_report_path": str(visual_gate_path),
        "carla_visual_smoke_gate": visual_gate,
        "recommended_visual_gate_command": (
            "python -m ultimate_pipeline.tools.carla_visual_smoke_gate "
            f"--xodr {final_out} --out {Path(out_dir) / 'final_visual_smoke'} --strict"
        ),
        "recommended_readiness_gate_command": (
            "python -m ultimate_pipeline.tools.final_map_readiness_gate "
            f"--xodr {final_out} --visual-gate-report {visual_gate_path}"
        ),
    }
    status_path = Path(out_dir) / "final_selected_xodr_status.json"
    status_path.write_text(
        json.dumps(status, indent=2, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )
    print(f"[STEP 8] final_selected_xodr_status.json -> {status_path}")
    return status


def _step8f_optional_carla_elevation_validation(self, final_out: str) -> None:
    _inject_main_pipeline_globals()
    enabled = str(
        os.getenv(
            "UP_ENABLE_CARLA_ELEVATION_VALIDATION",
            "1"
            if bool(
                getattr(self.settings, "ENABLE_CARLA_ELEVATION_VALIDATION", False)
            )
            else "0",
        )
    ).strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        return

    strict_quality = os.getenv("UP_STRICT_QUALITY_GATES", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    report_path = Path(self.out_dir) / "carla_elevation_validation.json"
    report: Dict[str, Any] = {
        "enabled": True,
        "ok": False,
        "reason": "",
        "xodr_path": str(final_out),
        "sampling_source": "carla_waypoints",
        "sampled_waypoints": 0,
        "waypoint_sample_limit": 200,
        "z_std": None,
        "z_min": None,
        "z_max": None,
        "bounds": None,
        "strict_quality_gates": bool(strict_quality),
    }

    try:
        carla_disabled_env = os.getenv("UP_DISABLE_CARLA", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        carla_disabled_setting = not bool(
            getattr(self.settings, "ENABLE_CARLA", True)
        )
        if carla_disabled_env or carla_disabled_setting:
            report["reason"] = "carla_disabled"
        elif self._carla_isolation_enabled():
            smoke = self._carla_smoke_load_subprocess(
                xodr_path=final_out,
                label="elevation_validation",
                spawn_ego=False,
                tick_frames=0,
                screenshot=False,
                timeout_s=int(getattr(self.settings, "CARLA_TIMEOUT_S", 180.0)),
            )
            payload = smoke.get("payload", {}) if isinstance(smoke, dict) else {}
            sampled = int(payload.get("waypoint_sample_count", 0) or 0)
            report["sampled_waypoints"] = sampled
            report["z_std"] = payload.get("waypoint_z_std")
            report["z_min"] = payload.get("waypoint_z_min")
            report["z_max"] = payload.get("waypoint_z_max")
            report["bounds"] = payload.get("map_bounds")
            if bool(payload.get("load_ok")) and sampled > 0:
                report["ok"] = True
                report["reason"] = "ok"
            else:
                report["reason"] = str(payload.get("error") or "carla_load_failed")
        else:
            from ultimate_pipeline.core.carla_opendrive_loader import (
                load_opendrive_world_from_file,
            )

            if self.client is None:
                self._connect_carla()
            if self.client is None:
                report["reason"] = "carla_client_unavailable"
            else:
                world = load_opendrive_world_from_file(
                    self.client,
                    Path(final_out),
                    timeout_s=float(
                        getattr(self.settings, "CARLA_TIMEOUT_S", 180.0)
                    ),
                    retries=1,
                    do_reload=True,
                )
                amap = world.get_map()
                waypoints = list(amap.generate_waypoints(2.0))
                sampled = waypoints[: int(report["waypoint_sample_limit"])]
                report["sampled_waypoints"] = int(len(sampled))
                if sampled:
                    xs = [float(wp.transform.location.x) for wp in sampled]
                    ys = [float(wp.transform.location.y) for wp in sampled]
                    zs = [float(wp.transform.location.z) for wp in sampled]
                    report["z_min"] = float(min(zs))
                    report["z_max"] = float(max(zs))
                    report["z_std"] = (
                        float(statistics.pstdev(zs)) if len(zs) > 1 else 0.0
                    )
                    report["bounds"] = {
                        "x_min": float(min(xs)),
                        "x_max": float(max(xs)),
                        "y_min": float(min(ys)),
                        "y_max": float(max(ys)),
                        "z_min": float(min(zs)),
                        "z_max": float(max(zs)),
                    }
                    report["ok"] = True
                    report["reason"] = "ok"
                else:
                    report["reason"] = "no_waypoints"
    except Exception as e:
        report["ok"] = False
        report["reason"] = f"exception:{e}"

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=True, sort_keys=True)
        print(f"[STEP 8] carla_elevation_validation.json -> {report_path}")
    except Exception as e:
        print(f"[STEP 8] carla_elevation_validation.json write failed: {e}")

    if strict_quality and not bool(report.get("ok", False)):
        raise RuntimeError(
            "CARLA elevation validation failed in strict mode: "
            f"{report.get('reason')} (see {report_path})"
        )
    if not bool(report.get("ok", False)):
        print(
            f"⚠️ CARLA elevation validation failed (non-strict): {report.get('reason')}"
        )


def _step8_marking_summary(self, final_out: str) -> None:
    _inject_main_pipeline_globals()
    try:
        tree, root = load_xodr(final_out)
        summary = MarkingBuilder.summarize_markings(root)
        self.vreport.add_dict("markings_summary", summary)

        print("[INFO] Marking summary:")
        print(f"   total marked lanes: {summary['total_marked_lanes']}")
        print(f"   center marks:       {summary['total_center_marks']}")
        print(f"   by color:           {summary['by_color']}")
        print(f"   by type:            {summary['by_type']}")
    except Exception as e:
        print(f"⚠️ Marking summary failed: {e}")

# ---------------- 8C) 🚗 FINAL SPAWN VALIDATION (LIGHT LOAD) ----------------


def _step8c_spawn_validation(self, final_out: str) -> None:
    _inject_main_pipeline_globals()
    s = self.settings

    assert getattr(s, "FORCE_LIGHT_LOAD_IN_STEP_8", True), (
        "FULL map load in STEP 8 is forbidden"
    )

    stage_name = "final_spawn_validation_light"

    light_out = final_out.replace(".xodr", "_light.xodr")

    try:
        strip_heavy_xodr_layers(
            final_out,
            light_out,
            drop_signals=True,
            drop_controllers=False,
        )
    except Exception as e:
        raise RuntimeError(
            f"❌ Failed to create LIGHT XODR ({light_out}): {e}"
        ) from e

    if self._carla_isolation_enabled():
        smoke = self._carla_smoke_load_subprocess(
            xodr_path=light_out,
            label=stage_name,
            spawn_ego=False,
            tick_frames=2,
            screenshot=False,
            timeout_s=int(getattr(self.settings, "CARLA_TIMEOUT_S", 180.0)),
        )
        try:
            outp = os.path.join(self.out_dir, f"carla_smoke_{stage_name}.json")
            with open(outp, "w", encoding="utf-8") as f:
                json.dump(smoke, f, indent=2, default=str, ensure_ascii=True)
        except Exception:
            pass

        payload = smoke.get("payload") if isinstance(smoke, dict) else None
        load_ok = (
            bool(payload.get("load_ok", False))
            if isinstance(payload, dict)
            else False
        )
        spawn_n = (
            int(payload.get("spawn_points_count", 0))
            if isinstance(payload, dict)
            else 0
        )

        if not load_ok:
            raise RuntimeError(
                f"❌ CARLA could not load LIGHT map for spawn validation: {light_out} "
                f"(isolation mode). See: {smoke.get('payload_path')}"
            )
        if spawn_n <= 0:
            raise RuntimeError(
                "❌ No valid spawn points — final map NOT drivable (isolation mode)."
            )

        print(
            f"✅ Spawn points validated — final map is drivable. (spawn_points={spawn_n})"
        )
        self.vreport.add("drivability", "spawn_points", f"ok ({spawn_n})")
        return

    loaded, self.client = carla_load_xodr_with_restart(
        self.client,
        light_out,
        stage_name,
    )

    if not loaded:
        raise RuntimeError(
            f"❌ CARLA could not load LIGHT map for spawn validation: {light_out}"
        )

    ensure_carla_ready(self.client)

    if not SpawnValidator.check(self.client):
        raise RuntimeError("❌ No valid spawn points — final map NOT drivable")

    print("✅ Spawn points validated — final map is drivable.")
    self.vreport.add("drivability", "spawn_points", "ok")

# ---------------- 8) 🔗 MARKINGS + INTEGRITY ----------------


def _unsafe_lanelink_regen_enabled(settings_obj) -> bool:
    enabled = bool(getattr(settings_obj, "ENABLE_LANELINK_REGEN", False))
    env_val = os.getenv("UP_ENABLE_LANELINK_REGEN", "").strip().lower()
    if env_val in ("1", "true", "yes", "on"):
        enabled = True
    return enabled


def _step8_markings_and_integrity(self, lanes_out: str, final_out: str) -> str:
    _inject_main_pipeline_globals()
    s = self.settings
    print("\n============== 🔗 STEP 8: LaneLinks & Markings ==============")

    tree, root = load_xodr(lanes_out)
    self._assert_geometry_frozen(root, "STEP 8")

    # ---------------------------------------------------------
    # 🛠️ HARD NORMALIZATION (pre-LaneLinkBuilder)
    # ---------------------------------------------------------
    # Build parent lookup once (ElementTree has no getparent()).
    # NOTE: This map is valid for the current tree snapshot; we only use it for removals below.
    parent_map = {child: parent for parent in root.iter() for child in list(parent)}

    # 1) Driving lanes with id=0 are illegal for CARLA (and can break link logic)
    removed_zero = 0
    for lane in root.findall(".//lane[@type='driving'][@id='0']"):
        parent = parent_map.get(lane)
        if parent is not None:
            parent.remove(lane)
            removed_zero += 1

    if removed_zero:
        print(f"⚠️ Removed {removed_zero} illegal driving lane(s) with id=0")

    # 2) Ensure every driving lane has a <link> node (LaneLinkBuilder expects it)
    created_links = 0
    for lane in root.findall(".//lane[@type='driving']"):
        if lane.find("link") is None:
            ET.SubElement(lane, "link")
            created_links += 1

    if created_links:
        print(f"⚠️ Added missing <link> nodes to {created_links} driving lanes")

    # ---------------------------------------------------------
    # Build LaneLinks + Markings (final topology/semantics here)
    # ---------------------------------------------------------
    if _unsafe_lanelink_regen_enabled(s):
        LaneLinkBuilder.regenerate(root)
    else:
        print("⏭️ LaneLinkBuilder.regenerate disabled (ENABLE_LANELINK_REGEN=0). "
              "Existing lane links preserved.")
    junction_lanelink_sanity = LaneLinkBuilder.sanitize_junction_lane_links(
        root, verbose=True
    )
    try:
        sanity_path = os.path.join(self.out_dir, "junction_lanelink_sanity.json")
        with open(sanity_path, "w", encoding="utf-8") as f:
            json.dump(
                junction_lanelink_sanity,
                f,
                indent=2,
                ensure_ascii=True,
                sort_keys=True,
            )
        print(f"[STEP 8] junction_lanelink_sanity.json -> {sanity_path}")
    except Exception as e:
        print(f"[STEP 8] junction laneLink sanity report write skipped: {e}")
    MarkingBuilder.add_basic_markings(root)

    # Save ONCE so path-based gates/repairs operate deterministically
    save_xodr(tree, final_out)
    print(f"✅ Final map XML written → {final_out}")
    semantic_out = final_out.replace(".xodr", "_semantic.xodr")
    import shutil

    shutil.copyfile(final_out, semantic_out)
    print(f"🧠 Semantic final saved → {semantic_out}")

    # ---------------------------------------------------------
    # 🔧 NEW: Repair + assert laneSection successor resolvability
    # (prevents CARLA MapBuilder.cpp asserts)
    # ---------------------------------------------------------
    fixed_out = final_out.replace(".xodr", "_laneSectionFixed.xodr")
    rep = repair_and_assert_lane_section_successors(
        xodr_path=final_out,
        out_path=fixed_out,
        lane_types=("driving",),  # strict CARLA-relevant lanes
        strict=True,  # fail if non-repairable discontinuities exist
    )
    print(
        f"✅ LaneSection successor repair: repairs={rep.get('repairs', 0)} "
        f"failures={len(rep.get('failures', []))}"
    )

    # 🎯 AUTHORITATIVE MAP SWITCH
    final_out = fixed_out
    try:
        shutil.copyfile(final_out, semantic_out)
        print(f"Semantic final refreshed -> {semantic_out}")
    except Exception as e:
        print(f"⚠️ WARNING: Failed to refresh semantic XODR: {e}")
    # ---------------------------------------------------------
    # 🛡️ HARD CARLA INVARIANT ENFORCEMENT (SINGLE AUTHORITY PASS)
    # - No driving lane may exist without a valid driving successor
    # ---------------------------------------------------------
    tree_chk, root_chk = load_xodr(final_out)

    # Build lane index: (road_id, laneSection_s, lane_id) → lane element
    lane_index = {}
    for road in root_chk.findall("./road"):
        road_id = road.get("id")
        lanes = road.find("lanes")
        if lanes is None:
            continue
        for ls in lanes.findall("./laneSection"):
            ls_s = ls.get("s")
            for lane in ls.findall("./lane"):
                lane_index[(road_id, ls_s, lane.get("id"))] = lane

    def _safe_remove_link(lane_elem: ET.Element) -> None:
        link = lane_elem.find("link")
        if link is not None:
            lane_elem.remove(link)

    downgraded_invalid = 0
    # ---------------------------------------------------------
    # 📝 IMPORTANT: Do NOT mass-downgrade driving lanes here.
    # Many OpenDRIVE files do not encode lane successors with (road,laneSection,lane).
    # CARLA stability issues are primarily addressed by laneSection successor repair above.
    # ---------------------------------------------------------
    tree_chk, root_chk = load_xodr(final_out)

    missing_lane_successor = 0
    for lane in root_chk.findall(".//lane[@type='driving']"):
        succ = lane.find("link/successor")
        if succ is None:
            missing_lane_successor += 1

    if missing_lane_successor:
        print(
            f"✅ Driving lanes without explicit lane-level successor: {missing_lane_successor} (allowed)"
        )

    print("Enforcing CARLA successor invariant (laneSection-level)...")
    # Evidence artifact for thesis/debugging (never fatal)
    try:
        write_lane_connectivity_report(
            xodr_path=final_out,
            out_json=final_out.replace(".xodr", "_lane_connectivity_report.json"),
            allow_dead_ends=True,
        )
    except Exception as _exc:
        print(f"[lane_connectivity] Warning: could not write report: {_exc}")

    try:
        assert_all_lanes_have_successors(final_out, allow_dead_ends=True)
        print("✅ CARLA successor invariant satisfied (dead-ends allowed).")
    except RuntimeError as e:
        # ---------------------------------------------
        # 🔧 AUTOFIX LANE SUCCESSORS (optional):
        # Try to infer and add missing lane successors from road links.
        #
        # Enable via env: UP_AUTOFIX_LANE_SUCCESSORS=1
        # ---------------------------------------------
        env_autofix_successors = str(
            os.getenv("UP_AUTOFIX_LANE_SUCCESSORS", "0")
        ).strip().lower() in ("1", "true", "yes", "on")

        if env_autofix_successors:
            print(
                "[lane_connectivity] UP_AUTOFIX_LANE_SUCCESSORS enabled → attempting repair..."
            )
            fixed_out_path = final_out.replace(
                ".xodr", "_lane_successor_fixed.xodr"
            )
            report_path = os.path.join(
                self.out_dir, "lane_successor_autofix_report.json"
            )

            repair_report = autofix_missing_lane_successors(
                xodr_path=final_out,
                allow_dead_ends=True,
                output_path=fixed_out_path,
            )

            # Add pipeline run context to report
            repair_report["pipeline_run_dir"] = self.out_dir

            # Write the report
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(repair_report, f, indent=2, ensure_ascii=True)
            print(f"[lane_connectivity] Autofix report → {report_path}")
            print(
                f"[lane_connectivity] Fixed {repair_report['fixed_count']}/{repair_report['broken_before_count']} broken lanes"
            )

            if repair_report["still_broken_count"] > 0:
                print(
                    f"[lane_connectivity] ⚠️ WARNING: {repair_report['still_broken_count']} lanes still broken after autofix"
                )

            # Use the fixed XODR
            final_out = fixed_out_path

            # Re-check to ensure the output is CARLA-safe
            try:
                assert_all_lanes_have_successors(final_out, allow_dead_ends=True)
                print(
                    "✅ CARLA successor invariant satisfied after autofix (dead-ends allowed)."
                )
            except RuntimeError as e2:
                # Autofix didn't fully resolve. For thesis stability, we can optionally
                # downgrade only the broken driving lanes to type=none so CARLA can still load.
                strict = str(
                    os.getenv("UP_STRICT_LANE_SUCCESSORS", "0")
                ).strip().lower() in ("1", "true", "yes", "on")
                if strict:
                    print(
                        f"[lane_connectivity] Strict mode enabled → failing: {e2}"
                    )
                    raise e2
                print(
                    "[lane_connectivity] Autofix incomplete → applying downgrade fallback for remaining broken lanes"
                )
                fixed_out2 = final_out.replace(
                    ".xodr", "_autofix_missingSuccessorDowngraded.xodr"
                )
                try:
                    rep2 = downgrade_broken_driving_lanes_to_none(
                        xodr_in=final_out,
                        xodr_out=fixed_out2,
                        allow_dead_ends=True,
                        out_json=fixed_out2.replace(
                            ".xodr", "_autofix_report.json"
                        ),
                    )
                    print(
                        f"[lane_connectivity] Downgrade fallback complete. Output → {fixed_out2}"
                    )
                    final_out = fixed_out2
                    # Re-check; downgrade should remove the fatal condition
                    assert_all_lanes_have_successors(
                        final_out, allow_dead_ends=True
                    )
                    print(
                        "✅ CARLA successor invariant satisfied after downgrade fallback (dead-ends allowed)."
                    )
                except Exception as e3:
                    print(f"[lane_connectivity] Downgrade fallback failed: {e3}")
                    raise e2

        # ---------------------------------------------
        # 🔄 FALLBACK: DOWNGRADE MODE (optional):
        # Convert only *broken* driving lanes to type=none so CARLA can load the map.
        #
        # Enable via:
        #   - settings: AUTOFIX_MISSING_LANE_SUCCESSORS = True
        #   - or env:  UP_AUTOFIX_MISSING_LANE_SUCCESSORS=1
        # ---------------------------------------------
        elif bool(
            getattr(self.settings, "AUTOFIX_MISSING_LANE_SUCCESSORS", False)
        ) or str(
            os.getenv("UP_AUTOFIX_MISSING_LANE_SUCCESSORS", "0")
        ).strip().lower() in ("1", "true", "yes", "on"):
            fixed_out2 = final_out.replace(
                ".xodr", "_autofix_missingSuccessorDowngraded.xodr"
            )
            rep = downgrade_broken_driving_lanes_to_none(
                xodr_in=final_out,
                xodr_out=fixed_out2,
                allow_dead_ends=True,
                out_json=fixed_out2.replace(".xodr", "_autofix_report.json"),
            )

            # Use downgraded XODR
            final_out = fixed_out2

            # Re-check; if still broken, decide strict vs continue.
            strict = str(
                os.getenv("UP_STRICT_LANE_SUCCESSORS", "0")
            ).strip().lower() in ("1", "true", "yes", "on")
            try:
                assert_all_lanes_have_successors(final_out, allow_dead_ends=True)
                print(
                    "✅ CARLA successor invariant satisfied after downgrade (dead-ends allowed)."
                )
            except RuntimeError as e3:
                # Record failure evidence and either raise (strict) or continue.
                fail_json = os.path.join(
                    self.out_dir, "lane_successor_final_fail.json"
                )
                try:
                    with open(fail_json, "w", encoding="utf-8") as f:
                        json.dump(
                            {"error": str(e3)}, f, indent=2, ensure_ascii=True
                        )
                    print(
                        f"[lane_connectivity] Final lane successor invariant still broken; evidence -> {fail_json}"
                    )
                except Exception as _exc:
                    print(
                        f"[lane_connectivity] Could not write failure evidence: {_exc}"
                    )
                if strict:
                    raise
                else:
                    print(
                        "[lane_connectivity] Continuing despite lane successor invariant violation (non-strict mode)."
                    )

            print(
                f"[lane_connectivity] Applied fallback autofix: downgraded {rep.get('downgraded_count', 0)} driving lanes; output: {fixed_out2}"
            )
            final_out = fixed_out2

            # Re-check to ensure the output is CARLA-safe.
            assert_all_lanes_have_successors(final_out, allow_dead_ends=True)
            print(
                "✅ CARLA successor invariant satisfied after downgrade autofix (dead-ends allowed)."
            )
        else:
            raise e

    self._run_geometric_continuity_gate(final_out, "after_lane_successor_repair")

    self._step8_marking_summary(final_out)

    # Canonical CRS override for auto final map (if manual proj4 available + offset large)
    try:
        self._maybe_override_final_georef(final_out)
    except Exception as e:
        print(f"[STEP 8] georef override skipped: {e}")

    if getattr(self.settings, "ENABLE_SPAWN_VALIDATION_STEP8", False):
        self._step8c_spawn_validation(final_out)
    # ---------------------------------------------------------
    # 🚧 Collision mesh gate (on authoritative file)
    # ---------------------------------------------------------
    tree2, root2 = load_xodr(final_out)
    if getattr(s, "USE_SHAPELY", False):
        print("✅ Shapely enabled — running full polygon collision mesh gate.")
        self.qgate.gate_collision_mesh(root2)
        save_xodr(tree2, final_out)  # ✅ persist authoritative mutation
    else:
        print("⚠️ Shapely disabled — skipping Shapely-based collision mesh gate.")

    # ---------------------------------------------------------
    # 📝 XODR final integrity (NOW reachable)
    # ---------------------------------------------------------
    print("\n============== 📝 XODR Final Integrity Check ==============")
    _enforce_final_lane_width_invariants(final_out, self.out_dir)
    tree2, root2 = load_xodr(final_out)

    try:
        uniqueness_issues = check_xml_uniqueness(root2)
        if uniqueness_issues:
            print("❌ XODR uniqueness issues detected:")
            for msg in uniqueness_issues:
                print("   -", msg)
            self.vreport.add_dict(
                "xodr_uniqueness_issues", {"issues": uniqueness_issues}
            )
        else:
            print("✅ XODR id uniqueness check passed.")

        xsd_path = getattr(s, "XODR_XSD_PATH", None)
        ok_schema, err = validate_xodr_schema(final_out, xsd_path)
        if not ok_schema:
            print(f"❌ XODR schema violation: {err}")
            self.vreport.add("xodr_schema", "error", err)
        else:
            print(
                "✅ XODR schema validation passed."
                if xsd_path
                else "✅ XODR schema validation skipped (no XSD)."
            )
    except Exception as e:
        print(f"⚠️ XODR final integrity check failed: {e}")

    # ---------------------------------------------------------
    # 📊 Map statistics (NOW reachable)
    # ---------------------------------------------------------
    print("\n============== 📊 STEP 8B: Map Statistics ==============")
    stats = XODRStatistics.compute(final_out)
    stats_path = os.path.join(self.out_dir, "map_statistics.json")
    XODRStatistics.save_json(stats, stats_path)
    self.vreport.add_dict("map_statistics", stats)
    print(f"✅ Map statistics saved → {stats_path}")

    _write_final_selected_xodr_status(final_out, self.out_dir)

    print("[DEBUG] Lanes after STEP 8:", _count_lanes(final_out))
    return final_out

# ---------------- 8D) 🛫 OPTIONAL PREFLIGHT VALIDATION ----------------


def _step8d_preflight_validation(self, final_out: str) -> None:
    """
    Optional env-flagged final validation using preflight_xodr_loadability.
    Controlled by UP_RUN_PREFLIGHT=1.
    """
    _inject_main_pipeline_globals()
    if not os.getenv("UP_RUN_PREFLIGHT", "").strip() in ("1", "true", "yes", "on"):
        return

    print("\n============== 🛫 STEP 8D: Preflight XODR Loadability ==============")
    from pathlib import Path
    from ultimate_pipeline.tools.preflight_xodr_loadability import run_preflight

    preflight_dir = Path(self.out_dir) / "preflight"
    try:
        report = run_preflight(Path(final_out), preflight_dir)
        status = report["summary"]["status"]

        # Write carla_loadability_status.json
        status_path = Path(self.out_dir) / "carla_loadability_status.json"
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "status": status,
                    "error_count": report["summary"]["error_count"],
                    "warning_count": report["summary"]["warning_count"],
                    "preflight_report_path": str(
                        preflight_dir / "preflight_report.json"
                    ),
                    "checked_at_utc": report["summary"]["checked_at_utc"],
                },
                f,
                indent=2,
            )

        if status != "ok":
            allow_fail = os.getenv("UP_ALLOW_PREFLIGHT_FAIL", "").strip() in (
                "1",
                "true",
                "yes",
                "on",
            )
            if not allow_fail:
                raise RuntimeError(
                    f"❌ Preflight validation failed: {report['summary']['error_count']} errors detected. "
                    f"See {preflight_dir / 'preflight_report.json'} for details."
                )
            else:
                print(
                    f"⚠️ Preflight validation failed but UP_ALLOW_PREFLIGHT_FAIL=1 (continuing)"
                )
        else:
            print("✅ Preflight validation passed")

    except Exception as e:
        if not os.getenv("UP_ALLOW_PREFLIGHT_FAIL", "").strip() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            raise
        print(
            f"⚠️ Preflight validation exception: {e} (continuing due to UP_ALLOW_PREFLIGHT_FAIL)"
        )


def _step8c_carla_safety_prune(self, final_out: str) -> str:
    _inject_main_pipeline_globals()
    s = self.settings
    out_pruned = final_out.replace(".xodr", "_carla_pruned.xodr")
    report = os.path.join(self.out_dir, "carla_prune_report.json")

    pruner = CarlaSafetyPruner(min_road_length_m=0.5)
    pruner.prune(final_out, out_pruned, report_path=report)

    print(f"🧹 CARLA prune output → {out_pruned}")

    # Geometric continuity check after CARLA pruning
    self._stage_gate(
        "08_carla_prune",
        "geometric_continuity",
        lambda: self.qgate.gate_geometric_continuity(out_pruned),
    )

    return out_pruned

# ---------------- 9) 🧩 TILING ----------------
