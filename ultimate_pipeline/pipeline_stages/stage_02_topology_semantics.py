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


def _step2_topology_semantics(self, sanitized: str, sumo_fixed: str) -> str:
    _inject_main_pipeline_globals()
    s = self.settings
    print("\n============== 🕸️ STEP 2: Topology Lint & SUMO Repair ==============")
    sumo_repair_meta = {"enabled": False}

    tree, root = load_xodr(sanitized)

    # Handle geoReference with provenance tracking (academic validity)
    # Check ORIGINAL input file to determine policy:
    # - If original had valid geoReference: preserve it (academic provenance)
    # - If original had none: use coordinates.json (maintains backward compat)
    # This is important because the sanitizer may create a default UTM32
    # that shouldn't be preserved if the original map had no geoReference.
    original_had_georef = check_original_has_valid_georeference(s.INPUT_XODR)
    georef_policy = "preserve" if original_had_georef else "force"
    georef_decision = handle_georeference(root, policy=georef_policy)

    # Save changes only if geoReference was modified
    if georef_decision["action"] != "kept":
        save_xodr(tree, sanitized)

    # Log truthful message based on what actually happened
    if georef_decision["action"] == "kept":
        print(
            f"[OK] Preserved existing geoReference (reason={georef_decision['reason']})"
        )
    elif georef_decision["action"] == "created":
        print(
            f"[OK] Created geoReference from coordinates.json (reason={georef_decision['reason']})"
        )
    else:  # patched
        print(
            f"[OK] Patched geoReference from coordinates.json (reason={georef_decision['reason']})"
        )

    # Write provenance record for academic reproducibility
    provenance_path = write_georeference_provenance(
        decision=georef_decision,
        output_dir=s.output_dir(),
        input_xodr_path=s.INPUT_XODR,
        output_xodr_path=sanitized,
        coordinates_json_path=s.COORDINATES_JSON,
        original_had_valid_georef=original_had_georef,
        policy_used=georef_policy,
    )
    print(f"📝 geoReference provenance → {provenance_path}")

    # Write CRS comparability report (manual vs auto alignment check)
    crs_path = self._write_crs_comparability(
        auto_xodr=sanitized,
        policy_used=georef_policy,
        georef_decision=georef_decision,
    )
    if crs_path:
        print(f"📐 CRS comparability report → {crs_path}")

    # 2A-pre: Repair invalid junction references BEFORE linting
    # This removes <link><predecessor|successor elementType="junction" elementId="X">
    # where junction X does not exist, preventing TL-003 errors.
    from ultimate_pipeline.topology.missing_junction_link_repair import (
        repair_missing_junction_links,
    )
    junction_repair_report = repair_missing_junction_links(root, logs_dir=s.logs_dir())
    if junction_repair_report["num_removed"] > 0:
        # Save changes back to file so downstream stages see the repaired XML
        save_xodr(tree, sanitized)
        print(
            f"🔧 Removed {junction_repair_report['num_removed']} invalid junction refs "
            f"from {junction_repair_report['num_roads_affected']} roads "
            f"(missing IDs: {junction_repair_report['missing_junction_ids_referenced'][:5]}...)"
        )
        self.vreport.add_dict("missing_junction_link_repair", junction_repair_report)
    else:
        print("✓ No missing junction references found.")

    # 2A: topology linter
    TopologyLinter.run(root, self.vreport)
    lint_path = os.path.join(s.logs_dir(), "topology_lint.json")
    self.vreport.save_json(lint_path)
    print(f"📊 Topology lint report saved → {lint_path}")

    # 2B: SUMO repair (global junctions)
    if s.ENABLE_SUMO_REPAIR:
        sumo_fixed_result = SUMORepair.repair(sanitized, sumo_fixed)
        if isinstance(getattr(sumo_fixed_result, "meta", None), dict):
            sumo_repair_meta = dict(sumo_fixed_result.meta)
        if sumo_fixed_result is None:
            # Checked on the raw result, BEFORE any str() coercion --
            # str(None) is the 4-character string "None", not the None
            # object, so checking `str(sumo_fixed_result) is None` (the
            # prior code) could never be true regardless of what
            # SUMORepair.repair() returns, silently skipping this
            # fallback path.
            print("⚠️ SUMO repair skipped/failed; continuing with sanitized file.")
            sumo_fixed_path = sanitized
        else:
            sumo_fixed_path = str(sumo_fixed_result)
            print(f"✅ SUMO repaired map → {sumo_fixed_path}")

        if s.QA_AUTOVIS and self._carla_allowed("pre_lane_preview"):
            if self._carla_isolation_enabled():
                print("⏭️ CARLA QA preview skipped (isolation mode).")
            else:
                from ultimate_pipeline.diagnostics.carla_quick_load import (
                    CarlaValidator,
                )

                CarlaValidator.quick_visual_check(
                    sumo_fixed_path, message="After STEP 2 — SUMO Repair"
                )
        else:
            if s.QA_AUTOVIS:
                print("⏭️ CARLA QA preview skipped (pre-lane stage).")

    else:
        sumo_fixed_path = sanitized
        print("⏭️ SUMO repair disabled by settings.")

    self._sumo_repair_meta = dict(sumo_repair_meta)
    sumo_meta_path = os.path.join(self.out_dir, "sumo_repair.json")
    try:
        with open(sumo_meta_path, "w", encoding="utf-8") as f:
            json.dump(self._sumo_repair_meta, f, indent=2)
        self.vreport.add_dict("sumo_repair", self._sumo_repair_meta)
        print(f"📝 SUMO repair metadata → {sumo_meta_path}")
    except Exception as exc:
        print(f"⚠️ Failed to persist SUMO repair metadata: {exc}")

    # Post-SUMO topology validation
    tree, root = load_xodr(sumo_fixed_path)
    print("🧪 Post-SUMO topology validation…")
    TopologyLinter.run(root, self.vreport)

    # Structure scan
    print("\n============== 🏗️ STEP 2C: Structural Scan ==============")
    struct_report = StructureScanner.analyze(root)
    StructureScanner.summarize(struct_report)
    self.vreport.add_dict("structure_scan", struct_report)

    working_topology_input = sumo_fixed_path

    if getattr(s, "ENABLE_AGGRESSIVE_STRUCTURE_PRUNE", False):
        print("⚠️ AGGRESSIVE STRUCTURE PRUNE ENABLED (legacy mode)")
        legacy_out, removed_ids = prune(working_topology_input)
        print(f"Legacy prune removed {len(removed_ids)} roads.")
        working_topology_input = legacy_out
    else:
        print("⏭️ Aggressive prune disabled.")

    MapPlotter.save_preview(
        working_topology_input, self.out_dir, stage="02_structure_clean"
    )

    # Semantic risk scan
    print("\n============== 🚨 STEP 2D: Semantic Risk Scan ==============")
    risk_map = SemanticVerifier.analyze_xodr(working_topology_input)
    SemanticVerifier.summarize(risk_map)
    self.vreport.add_dict("semantic_risk", risk_map)

    high_risk = SemanticVerifier.get_high_risk_roads(risk_map, threshold=8.0)
    risk_path = os.path.join(self.out_dir, "semantic_high_risk_roads.json")
    with open(risk_path, "w") as f:
        json.dump(high_risk, f, indent=2)

    print(f"⚠️ High-risk roads saved → {risk_path}")

    if high_risk:
        print(f"⚠️ High-risk roads detected: {len(high_risk)}")
    else:
        print("✅ No high-risk roads detected by semantic scan.")

    return working_topology_input

# ---------------- 3) 🔧 TOPOLOGY REPAIR ----------------
