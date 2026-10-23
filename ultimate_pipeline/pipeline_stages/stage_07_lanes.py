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


def _build_structural_osm_metadata(root, osm_path: str) -> tuple[dict, dict]:
    """Resolve lane-structure tags through fail-closed spatial matching.

    The existing name index remains available for broad street-level width
    policy. Lane-count, turn-lane, and cycle-lane geometry instead receives
    only a road-ID keyed map derived from EXACT/HIGH OSM-XODR matches.
    """
    from pathlib import Path

    if not osm_path or not Path(osm_path).is_file():
        return {}, {
            "status": "NOT_RUN",
            "reason": "osm_source_unavailable",
            "eligible_road_count": 0,
        }
    try:
        from ultimate_pipeline.enrichment.osm_meta_index import (
            extract_structural_osm_lane_metadata_ways,
            project_positioned_osm_metadata_ways,
        )
        from ultimate_pipeline.enrichment.osm_xodr_correspondence import (
            build_metadata_associations,
        )

        source_ways = extract_structural_osm_lane_metadata_ways(osm_path)
        positioned_ways = project_positioned_osm_metadata_ways(source_ways, root)
        associations, report = build_metadata_associations(positioned_ways, root)
        structural_osm_meta = {
            road_id: dict(association["metadata"])
            for road_id, association in sorted(associations.items())
            if association.get("class") in {"EXACT", "HIGH"}
        }
        return structural_osm_meta, {
            "status": "PASS",
            "source_way_count": len(source_ways),
            "projected_way_count": len(positioned_ways),
            "eligible_road_count": len(structural_osm_meta),
            "correspondence": report,
        }
    except Exception as exc:
        return {}, {
            "status": "INCOMPLETE",
            "reason": f"structural_osm_correspondence_failed:{exc}",
            "eligible_road_count": 0,
        }


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

    structural_osm_meta, structural_osm_report = _build_structural_osm_metadata(
        root, str(getattr(s, "OSM_FILE", "") or "")
    )
    structural_osm_report_path = os.path.join(
        self.out_dir, "structural_osm_lane_correspondence.json"
    )
    with open(structural_osm_report_path, "w", encoding="utf-8") as handle:
        json.dump(structural_osm_report, handle, indent=2, sort_keys=True)
    self.vreport.add_dict("structural_osm_lane_correspondence", structural_osm_report)
    print(
        "[STEP 7] Structural OSM lane correspondence: "
        f"{structural_osm_report['status']}, "
        f"eligible_roads={structural_osm_report['eligible_road_count']}"
    )

    # --- Ensure driving lanes exist ---
    lane_provenance_path = os.path.join(self.out_dir, "lane_provenance_report.json")
    created_lanes = LaneGenerator.ensure_lanes(
        root,
        verbose=True,
        osm_meta=osm_meta,
        structural_osm_meta=structural_osm_meta,
        provenance_report_path=lane_provenance_path,
    )
    self.vreport.add("lanes", "lane_provenance_report", lane_provenance_path)
    if created_lanes:
        print(
            f"[STEP 7] LaneGenerator created driving lanes for {created_lanes} roads."
        )
    else:
        print("[STEP 7] All roads already had driving lanes.")

    # --- Source-stage lane structure normalization (moved from Stage 8) ---
    # Driving lanes with id=0 are illegal for CARLA; every driving lane needs
    # a <link> node for the topology repairs below. Both are structural
    # prerequisites repaired HERE so Stage 8 stays validation-only.
    import xml.etree.ElementTree as _ET

    _parent_map = {child: parent for parent in root.iter() for child in list(parent)}
    _removed_zero = 0
    for _lane in root.findall(".//lane[@type='driving'][@id='0']"):
        _parent = _parent_map.get(_lane)
        if _parent is not None:
            _parent.remove(_lane)
            _removed_zero += 1
    if _removed_zero:
        print(f"[STEP 7] Removed {_removed_zero} illegal driving lane(s) with id=0")
    _created_links = 0
    for _lane in root.findall(".//lane[@type='driving']"):
        if _lane.find("link") is None:
            _ET.SubElement(_lane, "link")
            _created_links += 1
    if _created_links:
        print(f"[STEP 7] Added missing <link> nodes to {_created_links} driving lanes")
    self.vreport.add_dict(
        "lane_structure_normalization",
        {"removed_id_zero_driving_lanes": _removed_zero, "created_link_nodes": _created_links},
    )

    # NOTE (GAP-048 closure): lane-successor inference moved LATE in Stage 7
    # (after lane-width invariants, just before the semantic overlap gate).
    # An early inference here validated against lane sets that later stages
    # still mutate (LaneRepair.standardize, sidewalks, width invariants),
    # leaving lanes added/changed afterwards without successors (e.g. fresh
    # regen roads 74521/74526/74531/74536 lane -1: road successor existed but
    # the target lane post-dated the inference). See the topology-finalization
    # segment below.

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

    # --- GAP-026: harmonize junction connector lane widths (source stage) ---
    # Inherits each linked connector lane's width from its matched incoming
    # lane. Geometry, contactPoint, from/to mapping, and thresholds untouched.
    try:
        from ultimate_pipeline.lanes.junction_lane_width_harmonizer import (
            harmonize_junction_lane_widths,
        )

        gap026_width_report = harmonize_junction_lane_widths(root)
        self.vreport.add_dict("gap026_width_harmonization", gap026_width_report)
        print(
            "[STEP 7] GAP-026 width harmonization: "
            f"checked={gap026_width_report.get('checked_lane_links', 0)} "
            f"harmonized={gap026_width_report.get('harmonized_widths', 0)} "
            f"skipped={gap026_width_report.get('skipped_missing', 0)}"
        )
    except Exception as e:
        print(f"⚠️ GAP-026 width harmonization failed (non-fatal): {e}")

    # --- GAP-026: inner-first junction laneLink remap (source stage) ---
    # Junction <laneLink> sets arrive from the SUMO import and are never
    # regenerated (Stage 8 is VALIDATION_ONLY for lane topology).  This is
    # POSITIVE construction: a connection is rewritten only when the
    # deterministic inner-first pairing strictly reduces failing links under
    # the production checker's own (unchanged) tolerances.  An empty
    # inner-first set never replaces a non-empty original, so no connection
    # is driven to zero laneLinks.  No tolerance, oracle, or Stage-8 check
    # is modified.
    try:
        from ultimate_pipeline.lanes.junction_lanelink_inner_first import (
            repair_outer_to_inner_mispaired_lane_links,
        )

        gap026_lanelink_report = repair_outer_to_inner_mispaired_lane_links(
            root, verbose=True
        )
        self.vreport.add_dict("gap026_lanelink_inner_first", {
            k: v for k, v in gap026_lanelink_report.items() if k != "remap_log"
        })
        print(
            "[STEP 7] GAP-026 inner-first laneLink remap: "
            f"evaluated={gap026_lanelink_report.get('evaluated_connections', 0)} "
            f"remapped={gap026_lanelink_report.get('remapped_connections', 0)} "
            f"kept={gap026_lanelink_report.get('kept_connections', 0)}"
        )
    except Exception as e:
        print(f"⚠️ GAP-026 inner-first laneLink remap failed (non-fatal): {e}")

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

    # --- Topology finalization: intra-road repair, then lane-successor
    # inference (both moved here from early-Stage-7 / Stage-8) ---
    # Order matters and is load-bearing:
    #   1. intra-road repair first: fixes non-terminal section successors
    #      AND reclassifies linked none/restricted lanes to driving (which
    #      may create new driving lanes needing successors below);
    #   2. lane-successor inference second: validates against the FINAL lane
    #      sets (an early inference validated stale sets and missed lanes
    #      added by LaneRepair/sidewalks/invariants, e.g. fresh-regen roads
    #      74521/74526/74531/74536 lane -1).
    # Both run HERE at source stage so Stage 8 stays validation-only.
    from ultimate_pipeline.quality.check_lane_section_successors import (
        repair_and_assert_lane_section_successors,
    )

    intraroad_report = repair_and_assert_lane_section_successors(
        xodr_path=lanes_out,
        out_path=lanes_out,
        lane_types=("driving",),
        strict=True,
    )
    self.vreport.add_dict("lane_section_successor_repair", intraroad_report)
    print(
        "[STEP 7] Intra-road laneSection successor repair: "
        f"repairs={intraroad_report.get('repairs', 0)} "
        f"failures={len(intraroad_report.get('failures', []))} "
        f"reclassified={intraroad_report.get('reclassified_none_or_restricted_lanes', 0)}"
    )

    # --- P0-A source-stage fix: regenerate junction laneLinks from topology ---
    # LaneLinkBuilder runs HERE at source stage (Stage 7), before lane-successor
    # inference, so that `infer_lane_successors_from_topology` sees fully
    # populated junction laneLinks.  GAP-048: no fallback pairing — unlinked
    # incoming lanes are classified as residuals (never guessed).
    # This replaces the earlier GAP-026 remap which only PRUNED mispaired
    # links but never generated missing ones.
    tree, root = load_xodr(lanes_out)
    try:
        from ultimate_pipeline.lanes.lanelink_builder import LaneLinkBuilder
        LaneLinkBuilder.regenerate_lane_links(root, verbose=True)
        ll_report = LaneLinkBuilder.last_failure_report
        self.vreport.add_dict("lane_link_regenerate", ll_report)
        print(
            "[STEP 7] LaneLinkBuilder.regenerate_lane_links: "
            f"connections={ll_report.get('connections_total', 0)} "
            f"laneLinks={ll_report.get('lane_links_emitted', 0)} "
            f"unlinked={sum(v for k, v in ll_report.get('summary', {}).items() if not k.endswith('_for') or True) or 'see report'}"
        )
    except Exception as e:
        print(f"⚠️ LaneLinkBuilder.regenerate_lane_links failed (non-fatal): {e}")

    # --- Infer lane-level successors from road topology (generator stage) ---
    # Runs HERE at source stage using now-populated junction laneLinks.
    # Unique-proof only (terminal sections for junction targets); ambiguous
    # or unproven cases stay unresolved and are reported (never guessed).
    from ultimate_pipeline.enrichment.lane_successor_topology import infer_lane_successors_from_topology
    successor_report = infer_lane_successors_from_topology(root)
    print(
        f"[STEP 7] Lane successors from topology: inferred={successor_report['inferred_count']} "
        f"through_junction={successor_report['through_junction_count']} "
        f"junction_mapped={successor_report['junction_mapped_count']} "
        f"no_topology={successor_report['lanes_without_topology']}"
    )
    self.vreport.add_dict("lane_successor_topology", successor_report)
    save_xodr(tree, lanes_out)

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

