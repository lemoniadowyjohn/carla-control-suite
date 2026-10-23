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


def _step3_topology_repair(
    self, working_topology_input: str, topo_fixed: str
) -> str:
    _inject_main_pipeline_globals()
    s = self.settings
    print("\n============== 🔧 STEP 3: Topology Repair ==============")

    tree, root = load_xodr(working_topology_input)

    # P0-B source-stage fix: connect orphan roads within snap distance
    orphan_snap_m = float(os.getenv("UP_ORPHAN_SNAP_M", "25.0"))
    try:
        from ultimate_pipeline.topology.orphan_road_repair import repair_orphan_roads
        orphan_report = repair_orphan_roads(root, max_snap_m=orphan_snap_m)
        self.vreport.add_dict("p0b_orphan_repair", orphan_report)
        print(
            "[STEP 3] P0-B orphan road connection repair: "
            f"found={orphan_report['orphan_roads_found']} "
            f"repaired={orphan_report['repaired_connections']} "
            f"residual={orphan_report['residual_unconnected']}"
        )
    except Exception as e:
        print(f"⚠️ P0-B orphan repair failed (non-fatal): {e}")

    TopologyRepair.run(root)
    save_xodr(tree, topo_fixed)
    print(f"✅ TopologyRepair → {topo_fixed}")

    stage_name = "topology_repair"
    if s.ENABLE_CARLA_TEST_EARLY:
        # Lane width invariant guard (CARLA compatibility):
        # Ensure the exact XODR being imported has <width> for all non-center lanes.
        try:
            _rep_path = default_report_path(self.out_dir, "10_full_map_import")
            _rep = enforce_lane_width_invariants(
                topo_fixed, report_path=_rep_path, stage="10_full_map_import"
            )
            _tot = _rep.get("totals", {})
            print(
                f"🛣️ Lane width invariants (full map): found {_tot.get('missing_width_lanes_found', 0)}, fixed {_tot.get('missing_width_lanes_fixed', 0)} → {_rep_path}"
            )
        except Exception as _e:
            print(f"⚠️ Lane width invariant guard failed (full map): {_e}")
        if self._carla_isolation_enabled():
            smoke = self._carla_smoke_load_subprocess(
                xodr_path=topo_fixed,
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
                    f"CARLA cannot load file {topo_fixed} (isolation mode). See: {smoke.get('payload_path')}"
                )
            self.vreport.log_success(stage_name)
        else:
            loaded, self.client = carla_load_xodr_with_restart(
                self.client, topo_fixed, stage_name
            )
            if not loaded:
                print(f"❌ CARLA load failed in {stage_name}, attempting restart…")
                ensure_carla_ready(self.client)
                loaded, self.client = carla_load_xodr_with_restart(
                    self.client, topo_fixed, stage_name
                )
                if not loaded:
                    raise RuntimeError(f"CARLA cannot load file {topo_fixed}")
            self.vreport.log_success(stage_name)
    else:
        self.vreport.log_skipped(stage_name)
        print("⏭️ Skipped CARLA test:", stage_name)

    MapPlotter.save_preview(topo_fixed, self.out_dir, stage="03_topology_repair")

    # Junction integrity gate after topology repair
    self._stage_gate(
        "03_topology_repair",
        "junction_integrity",
        lambda: self.qgate.gate_junction_integrity(
            topo_fixed, stage="03_topology_repair"
        ),
    )

    return topo_fixed

# ---------------- 4) 🏗️ ENRICHMENT ----------------

