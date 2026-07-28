# REFAC_VERSION = "v5_preserve"
# NOTE: This file is auto-extracted from ultimate_pipeline/main_pipeline.py.
# It delegates to original helpers by injecting main_pipeline globals at runtime.

from __future__ import annotations

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


def _unsafe_planview_mutations_enabled(settings_obj) -> bool:
    enabled = bool(getattr(settings_obj, "ENABLE_UNSAFE_PLANVIEW_MUTATIONS", False))
    env_val = os.getenv("UP_ENABLE_UNSAFE_PLANVIEW_MUTATIONS", "").strip().lower()
    if env_val in ("1", "true", "yes", "on"):
        enabled = True
    return enabled


def _step6_planview_continuity(
    self,
    elev_out: str,
    geo_out: str,
    cont_out: str,
) -> str:
    _inject_main_pipeline_globals()
    s = self.settings
    unsafe = _unsafe_planview_mutations_enabled(s)
    print("\n============== 📐 STEP 6: PlanView & Continuity ==============")

    tree, root = load_xodr(elev_out)

    MIN_LEN = getattr(s, "MIN_GEOM_MERGE_LENGTH", 0.10)
    MAX_LEN = getattr(s, "MAX_GEOM_MERGE_LENGTH", 300.0)
    MAX_CURV = getattr(s, "CURVATURE_MAX_ALLOWED", 1.0)

    if unsafe:
        # 1) smooth heading jumps
        try:
            print("🔥 Pre-smoothing geometry (heading jumps)…")
            num_smoothed = PlanViewSmoother.smooth_heading_jumps(
                root, threshold_deg=12.0
            )
            print(f"   → Smoothed {num_smoothed} heading discontinuities.")
        except Exception as e:
            print(f"⚠️ Heading smoothing skipped/failed: {e}")

        # 2) merge small geometries
        merged = PlanViewSmoother.merge_small_geometries(
            root,
            min_length=MIN_LEN,
            max_merged_length=MAX_LEN,
        )
        print(f"   → Merged {merged} tiny segments (< {MIN_LEN} m).")

        # 3) remove micro-fragments
        removed = PlanViewSmoother.merge_short_segments(root, min_len=MIN_LEN * 0.25)
        print(f"   → Removed {removed} micro-fragments (< {MIN_LEN * 0.25:.2f} m).")

        # 4) clamp curvature again (safety)
        clamped = PlanViewSmoother.clamp_curvature(root, MAX_CURV)
        print(f"   → Curvature clamped: {clamped}")

        # 5) recompute s
        PlanViewSmoother.recompute_s_values(root)
        if getattr(s, "ENABLE_GEOMETRY_START_RECOMPUTE", False):
            fixed = PlanViewSmoother.recompute_geometry_starts(root)
            print(f"   → Geometry start points fixed: {fixed}")
        else:
            print("⏭️ Geometry start recompute disabled (safe default).")
    else:
        print("⏭️ Unsafe planView mutations disabled (ENABLE_UNSAFE_PLANVIEW_MUTATIONS=0). "
              "Skipping heading smoothing, merge, micro-fragment removal, geometry start recompute.")
        clamped = PlanViewSmoother.clamp_curvature(root, MAX_CURV)
        print(f"   → Curvature clamped: {clamped}")
        PlanViewSmoother.recompute_s_values(root)
        print("⏭️ Geometry start recompute disabled (safe default).")

    save_xodr(tree, geo_out)
    print(f"✅ PlanView smoothed → {geo_out}")
    MapPlotter.save_preview(geo_out, self.out_dir, stage="05_planview_merge")

    # 6) continuity repair
    MeshContinuityRepairer.run(geo_out, cont_out)

    # Geometric continuity check (XY/heading at road joins)
    continuity_report = self._stage_gate(
        "06_continuity",
        "geometric_continuity",
        lambda: self.qgate.gate_geometric_continuity(cont_out),
    )

    if isinstance(continuity_report, dict) and not continuity_report.get(
        "ok", True
    ):
        enable_quarantine = os.getenv(
            "UP_ENABLE_ROAD_QUARANTINE", ""
        ).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        if enable_quarantine:
            try:
                from ultimate_pipeline.geometry.quarantine_bad_roads import (
                    DEFAULT_THRESHOLDS,
                    quarantine_bad_roads,
                    write_quarantine_report,
                )

                def _env_float(name: str, default: float) -> float:
                    try:
                        return float(os.getenv(name, default))
                    except Exception:
                        return default

                thresholds = {
                    "continuity_dxy_max_m": _env_float(
                        "UP_QUARANTINE_CONTINUITY_DXY",
                        DEFAULT_THRESHOLDS["continuity_dxy_max_m"],
                    ),
                    "continuity_dhdg_max_deg": _env_float(
                        "UP_QUARANTINE_CONTINUITY_DHDG",
                        DEFAULT_THRESHOLDS["continuity_dhdg_max_deg"],
                    ),
                    "heading_jump_max_deg": _env_float(
                        "UP_QUARANTINE_HEADING_JUMP_DEG",
                        DEFAULT_THRESHOLDS["heading_jump_max_deg"],
                    ),
                    "curvature_abs_max": _env_float(
                        "UP_QUARANTINE_CURVATURE_ABS",
                        DEFAULT_THRESHOLDS["curvature_abs_max"],
                    ),
                    "curvature_jump_max": _env_float(
                        "UP_QUARANTINE_CURVATURE_JUMP",
                        DEFAULT_THRESHOLDS["curvature_jump_max"],
                    ),
                }
                max_fraction = _env_float("UP_QUARANTINE_MAX_FRACTION", 0.008)

                quarantine_report = quarantine_bad_roads(
                    cont_out,
                    cont_out,
                    continuity_report=continuity_report,
                    max_fraction=max_fraction,
                    thresholds=thresholds,
                )
                quarantine_report["continuity_issues"] = continuity_report.get(
                    "num_issues"
                )
                quarantine_report["max_fraction"] = max_fraction
                quarantine_path = os.path.join(
                    self.out_dir, "roads_quarantined.json"
                )
                write_quarantine_report(quarantine_path, quarantine_report)
                print(f"[STEP 6] Wrote roads_quarantined.json -> {quarantine_path}")

                self._stage_gate(
                    "06_continuity",
                    "road_quarantine",
                    lambda: quarantine_report,
                )
                self._stage_gate(
                    "06_continuity_quarantine",
                    "geometric_continuity",
                    lambda: self.qgate.gate_geometric_continuity(cont_out),
                )
            except Exception as e:
                print(f"[STEP 6] Quarantine failed (continuing): {e}")

    # continuity_debug.json
    debug_path = os.path.join(self.out_dir, "continuity_debug.json")
    try:
        r = MeshContinuityRepairer(cont_out)
        scan = r.scan_roads()
        with open(debug_path, "w", encoding="utf-8") as f:
            json.dump(scan, f, indent=2)
        print(f"✅ continuity_debug.json written → {debug_path}")
    except Exception as e:
        print(f"⚠️ Could not create continuity debug file: {e}")

    # 7) micro-prune after continuity
    if unsafe:
        print("⚙️ Running Micro-Pruning on continuity output…")
        tree_mp, root_mp = load_xodr(cont_out)
        PlanViewSmoother.merge_small_geometries(
            root_mp, min_length=0.05, max_merged_length=s.MAX_SEGMENT_LENGTH_FIX
        )
        PlanViewSmoother.merge_short_segments(root_mp, min_len=0.25)
        # Merge/prune can leave stale x/y/hdg starts; chain starts deterministically.
        micro_prune_start_fixes = int(PlanViewSmoother.recompute_geometry_starts(root_mp))
        PlanViewSmoother.recompute_s_values(root_mp)
        save_xodr(tree_mp, cont_out)
        print(
            "✅ Micro-Pruning after continuity complete. "
            f"(geometry starts recomputed: {micro_prune_start_fixes})"
        )
    else:
        print("⏭️ Micro-Pruning disabled (ENABLE_UNSAFE_PLANVIEW_MUTATIONS=0).")
        micro_prune_start_fixes = 0

    if os.getenv("UP_ENABLE_PLANVIEW_SEAM_GATE", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        from ultimate_pipeline.quality.check_geometric_continuity import (
            auto_repair_tiny_planview_seams_in_file,
            check_planview_internal_seams,
        )

        seam_eps = float(os.getenv("UP_PLANVIEW_SEAM_EPS_M", "0.2"))
        try:
            large_seam_threshold_m = float(
                os.getenv("UP_PLANVIEW_LARGE_SEAM_THRESHOLD_M", "1.0")
            )
        except Exception:
            large_seam_threshold_m = 1.0

        precheck_report = check_planview_internal_seams(cont_out, eps_xy=seam_eps)
        precheck_max_seam_m = float(precheck_report.get("max_seam_m", 0.0) or 0.0)
        root_cause_recompute: Dict[str, Any] = {
            "applied": False,
            "trigger_max_seam_m": float(precheck_max_seam_m),
            "threshold_m": float(large_seam_threshold_m),
            "updated_geometry_starts": 0,
            "micro_prune_geometry_starts_recomputed": int(micro_prune_start_fixes),
        }
        if precheck_max_seam_m > large_seam_threshold_m:
            try:
                tree_fix, root_fix = load_xodr(cont_out)
                updated_starts = int(
                    PlanViewSmoother.recompute_geometry_starts(root_fix)
                )
                if updated_starts > 0:
                    PlanViewSmoother.recompute_s_values(root_fix)
                    save_xodr(tree_fix, cont_out)
                    root_cause_recompute["applied"] = True
                    root_cause_recompute["updated_geometry_starts"] = updated_starts
                print(
                    "[STEP 6] Large planView seams detected before gate "
                    f"(max={precheck_max_seam_m:.3f}m > {large_seam_threshold_m:.3f}m); "
                    f"recomputed geometry starts: {updated_starts}"
                )
            except Exception as e:
                print(
                    f"[STEP 6] Large-seam root-cause recompute failed (continuing): {e}"
                )

        seam_report = self._stage_gate(
            "06_continuity",
            "planview_internal_seams",
            lambda: check_planview_internal_seams(cont_out, eps_xy=seam_eps),
        )
        if isinstance(seam_report, dict):
            seam_report["root_cause_recompute"] = root_cause_recompute
            seam_report["precheck_max_seam_m"] = float(precheck_max_seam_m)
            seam_report["precheck_ok"] = bool(precheck_report.get("ok", False))
        strict_quality = os.getenv(
            "UP_STRICT_QUALITY_GATES", "0"
        ).strip().lower() in ("1", "true", "yes", "on")
        auto_repair_enabled = str(
            os.getenv(
                "UP_ENABLE_PLANVIEW_SEAM_AUTO_REPAIR",
                "1"
                if bool(
                    getattr(self.settings, "ENABLE_PLANVIEW_SEAM_AUTO_REPAIR", True)
                )
                else "0",
            )
        ).strip().lower() in ("1", "true", "yes", "on")
        auto_repair_max = _resolve_planview_auto_repair_max_m(self.settings)
        if (
            (not strict_quality)
            and auto_repair_enabled
            and isinstance(seam_report, dict)
            and not seam_report.get("ok", True)
        ):
            repair_report = auto_repair_tiny_planview_seams_in_file(
                cont_out,
                eps_xy=seam_eps,
                max_repair_seam_m=auto_repair_max,
            )
            seam_report["auto_repair"] = repair_report
            if repair_report.get("fixed", False):
                seam_report = repair_report.get("after", seam_report)
            try:
                repair_path = os.path.join(
                    self.out_dir, "planview_internal_seams_step6_autorepair.json"
                )
                with open(repair_path, "w", encoding="utf-8") as f:
                    json.dump(
                        repair_report,
                        f,
                        indent=2,
                        default=str,
                        ensure_ascii=True,
                        sort_keys=True,
                    )
            except Exception as e:
                print(
                    f"[STEP 6] planView seam auto-repair report write skipped: {e}"
                )
        try:
            seam_report_path = os.path.join(
                self.out_dir, "planview_internal_seams_step6.json"
            )
            with open(seam_report_path, "w", encoding="utf-8") as f:
                json.dump(
                    seam_report,
                    f,
                    indent=2,
                    default=str,
                    ensure_ascii=True,
                    sort_keys=True,
                )
        except Exception as e:
            print(f"[STEP 6] planView seam report write skipped: {e}")

    # 8) quality checks
    tree, root = load_xodr(cont_out)
    MeshChecker.quick_check(root)
    self.qgate.gate_physics_feasibility(root)
    self.qgate.gate_randomness_entropy(root)

    MapPlotter.save_preview(cont_out, self.out_dir, stage="05_continuity")

    heatmap_png = os.path.join(self.out_dir, "continuity_heatmap.png")
    continuity_debug_json = debug_path
    HeatmapGenerator.run(
        cont_out,
        heatmap_png,
        debug_json=continuity_debug_json,
    )

    print("🖼️ Generating post-continuity previews…")
    MapPlotter.save_preview(
        cont_out, self.out_dir, stage="06_post_continuity_planview"
    )

    before = os.path.join(self.out_dir, "map_preview_05_planview_merge.png")
    after = os.path.join(self.out_dir, "map_preview_05_continuity.png")
    gif_out = os.path.join(self.out_dir, "planview_continuity_diff.gif")

    if os.path.exists(before) and os.path.exists(after):
        AnimatedDiff.run(before, after, gif_out)
    else:
        print(
            f"⚠️ AnimatedDiff skipped (missing previews): "
            f"before={os.path.exists(before)} ({before}), "
            f"after={os.path.exists(after)} ({after})"
        )

    print("[DEBUG] Lanes after STEP 6:", _count_lanes(cont_out))
    self.semantic_state["has_planview"] = True

    return cont_out

# ---------------- 7) 🛣️ LANES + SIDEWALKS ----------------
