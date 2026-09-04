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


def _step7_lanes_sidewalks(self, cont_out: str, lanes_out: str) -> str:
    _inject_main_pipeline_globals()
    s = self.settings
    print("\n============== 🛣️ STEP 7: Lane, Offset, Cross-section ==============")

    tree, root = load_xodr(cont_out)
    self._assert_geometry_frozen(root, "STEP 7")
    osm_meta = {}
    try:
        osm_file = getattr(s, "OSM_FILE", "")
        if osm_file and os.path.exists(osm_file):
            from ultimate_pipeline.enrichment.osm_meta_index import build_osm_meta_index

            osm_meta = build_osm_meta_index(osm_file)
            print(f"[STEP 7] Lane-width OSM metadata: {len(osm_meta)} indexed ways.")
        else:
            print("[STEP 7] Lane-width OSM metadata unavailable; using documented fallback widths.")
    except Exception as e:
        osm_meta = {}
        print(f"⚠️ Lane-width OSM metadata failed: {e}; using documented fallback widths.")

    # --- Ensure driving lanes exist ---
    created_lanes = LaneGenerator.ensure_lanes(root, verbose=True, osm_meta=osm_meta)
    if created_lanes:
        print(
            f"[STEP 7] LaneGenerator created driving lanes for {created_lanes} roads."
        )
    else:
        print("[STEP 7] All roads already had driving lanes.")

    # --- Optional ML-based lane refinement (non-destructive) ---
    if getattr(SETTINGS, "ENABLE_LANE_GNN_REFINER", False):
        print("🧠 LaneGNNRefiner: running ML-based lane sanity pass...")
        model_path = getattr(SETTINGS, "LANE_GNN_WEIGHTS_PATH", None)

        if not model_path or not os.path.exists(model_path):
            print("⚠️ LaneGNNRefiner skipped (no model weights found).")
        else:
            try:
                from ultimate_pipeline.ml.lane_gnn_refiner import LaneGNNRefiner
            except ImportError as e:
                print(
                    f"⚠️ LaneGNNRefiner module missing — skipping ML lane refinement ({e})"
                )
            else:
                LaneGNNRefiner.run_inplace(
                    root,
                    model_path=model_path,
                    device=getattr(SETTINGS, "LANE_GNN_DEVICE", "cpu"),
                    confidence_thresh=0.7,
                )
                print("✅ LaneGNNRefiner applied probabilistic hints.")
    else:
        print("⏭️ LaneGNNRefiner disabled by settings.")

    driving_lanes = root.findall(".//lane[@type='driving']")
    lane_count = len(driving_lanes)
    print(f"[STEP 7] Driving lane count after generation: {lane_count}")
    if lane_count == 0:
        raise RuntimeError(
            "❌ STEP 7 FAILED: No driving lanes generated. "
            "Pipeline aborted before CARLA load."
        )

    LaneSectionBoundaryFixer.fix(root)
    lane_width_policy_report = LaneRepair.standardize(root, osm_meta=osm_meta)
    lane_width_policy_path = os.path.join(self.out_dir, "lane_width_policy_report.json")
    try:
        with open(lane_width_policy_path, "w", encoding="utf-8") as f:
            json.dump(
                lane_width_policy_report,
                f,
                indent=2,
                ensure_ascii=True,
                sort_keys=True,
            )
        self.vreport.add_dict("lane_width_policy", lane_width_policy_report)
        print(
            "[STEP 7] Lane-width policy: "
            f"updated={lane_width_policy_report.get('totals', {}).get('driving_widths_updated', 0)} "
            f"six_meter={lane_width_policy_report.get('totals', {}).get('six_meter_placeholders_found', 0)} "
            f"-> {lane_width_policy_path}"
        )
    except Exception as e:
        print(f"⚠️ Failed to write lane-width policy report: {e}")
    LaneRepair.enforce_width_continuity(root)

    LaneOffsetSmoother.smooth(root)
    LaneOffsetNormalizer.normalize(root)
    laneoffset_qc = normalize_junction_laneoffsets(root, max_abs_a=0.5)
    laneoffset_qc_path = os.path.join(self.out_dir, "junction_laneoffset_qc.json")
    try:
        with open(laneoffset_qc_path, "w", encoding="utf-8") as f:
            json.dump(laneoffset_qc, f, indent=2, ensure_ascii=True, sort_keys=True)
    except Exception as e:
        print(f"⚠️ Failed to write junction laneOffset QC report: {e}")
    print(
        "[STEP 7] Junction laneOffset QC: "
        f"checked={laneoffset_qc.get('num_checked', 0)} "
        f"fixed={laneoffset_qc.get('num_fixed', 0)} "
        f"remaining={laneoffset_qc.get('num_remaining_violations', 0)} "
        f"→ {laneoffset_qc_path}"
    )
    self.vreport.add_dict("junction_laneoffset_qc", laneoffset_qc)
    strict_quality = os.getenv("UP_STRICT_QUALITY_GATES", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if strict_quality and int(laneoffset_qc.get("num_remaining_violations", 0)) > 0:
        raise RuntimeError(
            "Junction laneOffset QC failed in strict mode: "
            f"{laneoffset_qc.get('num_remaining_violations')} remaining violations "
            f"(see {laneoffset_qc_path})"
        )
    CrossSectionRepair.enforce(root)
    LaneWidthClamp.clamp(root)

    save_xodr(tree, lanes_out)
    print(f"✅ Lane & cross-section repaired → {lanes_out}")
    if s.QA_AUTOVIS and not s.ENABLE_CARLA_TEST_EARLY:
        print("⏭️ CARLA load skipped (QA): map not semantically complete")
    PipelineDiagnostics.check_lane_widths(root, "after_lane_crosssection_repair")

    # optional CARLA load
    if s.ENABLE_CARLA_TEST_EARLY:
        stage_name = "after_lane_repair"
        if self._carla_isolation_enabled():
            smoke = self._carla_smoke_load_subprocess(
                xodr_path=lanes_out,
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
            if not (
                isinstance(smoke.get("payload"), dict)
                and smoke["payload"].get("load_ok", False)
            ):
                raise RuntimeError(
                    f"CARLA cannot load file {lanes_out} (isolation mode). See: {smoke.get('payload_path')}"
                )
        else:
            loaded, self.client = carla_load_xodr_with_restart(
                self.client, lanes_out, stage_name
            )
            if not loaded:
                print(f"❌ CARLA load failed in {stage_name}, attempting restart…")
                ensure_carla_ready(self.client)
                loaded, self.client = carla_load_xodr_with_restart(
                    self.client, lanes_out, stage_name
                )
                if not loaded:
                    raise RuntimeError(f"CARLA cannot load file {lanes_out}")

    MapPlotter.save_preview(lanes_out, self.out_dir, stage="06_lanes")
    print("🖼️ Generating lane-geometry preview…")
    MapPlotter.save_preview(lanes_out, self.out_dir, stage="07_lanes_full")

    # sidewalks
    if getattr(s, "ENABLE_SIDEWALKS", True):
        print("Adding sidewalks...")
        tree, root = load_xodr(lanes_out)
        sidewalks_added = SidewalkBuilder.add_sidewalks(root, osm_meta=osm_meta)
        save_xodr(tree, lanes_out)
        MapPlotter.save_preview(lanes_out, self.out_dir, stage="06_sidewalks")
        self.vreport.add("enrichment", "sidewalks_added", str(sidewalks_added))
        if sidewalks_added == 0:
            self.vreport.add("warning", "sidewalks", "no_sidewalks_added")
            print(
                "⚠️ WARNING: No sidewalk lanes added. Check OSM hints or lane counts."
            )

    print("Generating post-sidewalk preview...")
    MapPlotter.save_preview(lanes_out, self.out_dir, stage="07_sidewalks_final")

    # --- Lane-width invariants (CARLA stability guard) ---
    # CARLA may crash or import unstable maps if non-center lanes (id != 0)
    # are missing a <width> record (seen especially on connector roads).
    tree, root = load_xodr(lanes_out)
    lw_report = enforce_lane_width_invariants_on_root(root)
    lw_report_path = write_lane_width_invariants_report(
        lw_report, Path(self.out_dir)
    )
    missing_found = int(lw_report["totals"]["missing_width_lanes_found"])
    missing_fixed = int(lw_report["totals"]["missing_width_lanes_fixed"])
    print(
        f"🛣️ Lane width invariants: found {missing_found}, fixed {missing_fixed} → {lw_report_path}"
    )
    if missing_fixed > 0:
        save_xodr(tree, lanes_out)
    if lw_report.get("severity") == "fail":
        raise RuntimeError(
            "❌ Lane width invariant enforcement failed (missing widths found but not fixed). "
            f"See report: {lw_report_path}"
        )

    # semantic overlap gate
    tree, root = load_xodr(lanes_out)
    self.qgate.gate_semantic_overlap(root)

    lane_overlay_png = os.path.join(self.out_dir, "lane_overlay.png")
    LaneOverlay.run(lanes_out, lane_overlay_png)

    cs_png = os.path.join(self.out_dir, "cross_sections.png")
    CrossSectionVisualizer.run(lanes_out, cs_png, max_roads=200)
    self.semantic_state["has_lanes"] = True
    print(
        "✅ STEP 7 complete — lane semantics established (CARLA-drivable semantics now exist)"
    )

    return lanes_out

# ---------------- 8A) 🎨 MARKING SUMMARY ----------------

