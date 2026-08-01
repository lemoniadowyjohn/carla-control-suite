# REFAC_VERSION = "v4_2026-02-21"
# Auto-generated stage module extracted from ultimate_pipeline.main_pipeline
from __future__ import annotations

def _inject_main_pipeline_globals() -> None:
    """Populate this module's globals with symbols from ultimate_pipeline.main_pipeline.

    This avoids duplicating the monolith's import surface while keeping stage code unchanged.
    Import is performed lazily at runtime (after main_pipeline is loaded).
    """
    g = globals()
    if g.get("_UP_STAGE_GLOBALS_INJECTED"):
        return
    from ultimate_pipeline import main_pipeline as _mp
    for k, v in _mp.__dict__.items():
        if k not in g:
            g[k] = v
    g["_UP_STAGE_GLOBALS_INJECTED"] = True



def _step11_simulation(self, final_out: str, graph_path: Optional[str]) -> None:
    _inject_main_pipeline_globals()
    s = self.settings
    if not getattr(s, "ENABLE_SIMULATION_GATE", False):
        print("\n⏭️ Simulation gate disabled in settings.")
        return
    interactive_env = os.getenv("UP_INTERACTIVE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if not interactive_env:
        print("\n⏭️ Interactive simulation skipped (set UP_INTERACTIVE=1 to run).")
        return

    print("\n============== 🎮 STEP 11: Interactive Simulator ==============")

    # Local imports: keep orchestrator CARLA-free unless interactive simulation is requested.
    from ultimate_pipeline.carla_tools.carla_sim_consolidated import CarlaSimulation
    from ultimate_pipeline.carla_tools.actor_stream_manager import (
        ActorStreamManager,
    )
    from ultimate_pipeline.carla_tools.tile_streamer import TileStreamer
    from ultimate_pipeline.carla_tools.mesh_streamer import MeshStreamer

    if self.client is None:
        # In non-interactive runs we may have used isolation mode and skipped connecting.
        # For the interactive simulator we must connect in-process.
        self._connect_carla()
    if self.client is None:
        print("⚠️ Interactive simulator skipped: CARLA client unavailable.")
        return

    tile_streamer = None
    if getattr(s, "ENABLE_SIM_TILE_STREAMING", False) and graph_path:
        tiles_dir = os.path.join(self.out_dir, "tiles")
        tile_streamer = TileStreamer(
            client=self.client,
            tiles_dir=tiles_dir,
            adjacency_json=graph_path,
        )

    mesh_streamer = None
    if getattr(s, "ENABLE_MESH_STREAMING", False):
        mesh_streamer = MeshStreamer(self.client.get_world())

    actor_manager = None
    if tile_streamer:
        actor_manager = ActorStreamManager(
            client=self.client,
            tile_streamer=tile_streamer,  # ✅ required
            max_vehicles=s.STREAM_MAX_VEHICLES,
            max_walkers=s.STREAM_MAX_WALKERS,
        )

    print("🎮 Launching interactive simulation…")
    sim = CarlaSimulation(
        host=s.CARLA_HOST,
        port=s.CARLA_PORT,
        w=s.SIM_VIEWPORT_W,
        h=s.SIM_VIEWPORT_H,
        use_synchronous=True,
        use_scenarios=getattr(s, "ENABLE_SCENARIO_MANAGER", True),
        tile_streamer=tile_streamer,
        mesh_streamer=mesh_streamer,
        actor_manager=actor_manager,
    )
    try:
        sim.run()
    except Exception as e:
        print(f"❌ Simulator crashed: {e}")
        if ensure_carla_ready(self.client):
            print("🔄 CARLA restarted.")
        else:
            print("❌ Failed to restart CARLA.")


def _step12_domain_gap(self, final_out: str) -> None:
    _inject_main_pipeline_globals()
    s = self.settings
    if not getattr(s, "ENABLE_DOMAIN_GAP", False):
        print("\n⏭️ Domain-gap analysis disabled in settings.")
        return

    print("\n============== 📊 STEP 12: Domain Gap Analysis ==============")

    # Robust settings lookup (older settings.py may not define these attributes)
    manual_xodr = getattr(s, "MANUAL_MAP_XODR", None) or getattr(
        s, "MANUAL_REFERENCE_XODR", None
    )
    manual_tiles = (
        getattr(s, "MANUAL_TILES_DIR", None)
        or getattr(s, "MANUAL_TILES_ROOT", None)
        or ""
    )

    # Manual XODR is mandatory for any meaningful domain-gap computation.
    if not manual_xodr:
        print("⚠️ Domain gap ENABLED but MANUAL_MAP_XODR is not configured.")
        print("   → Skipping STEP 12. Set MANUAL_MAP_XODR in settings.py.")
        self.vreport.add("domain_gap", "skipped", "manual_xodr_not_configured")
        return

    if not os.path.exists(manual_xodr):
        print(f"⚠️ Manual reference XODR not found: {manual_xodr}")
        self.vreport.add("domain_gap", "skipped", "manual_xodr_missing")
        return

    # Tiles are optional: whole-map gaps work without per-tile comparisons.
    if manual_tiles and not os.path.isdir(manual_tiles):
        print(
            f"⚠️ Manual tiles directory not found (per-tile gaps will be skipped): {manual_tiles}"
        )
        manual_tiles = ""

    auto_xodr = final_out
    auto_tiles = os.path.join(self.out_dir, "tiles")
    auto_tiles_meta = ""
    if not os.path.isdir(auto_tiles):
        # Tiling may be disabled; run_full_domain_gap will skip per-tile stages.
        auto_tiles = ""
    else:
        try:
            auto_tiles_meta_path = (
                Path(auto_tiles).parent / "tile_metadata.json"
                if Path(auto_tiles).name.lower() == "tiles"
                else Path(auto_tiles) / "tile_metadata.json"
            )
            if not auto_tiles_meta_path.is_file():
                TileMetadata.generate_metadata(
                    str(auto_tiles), str(auto_tiles_meta_path)
                )
            if auto_tiles_meta_path.is_file():
                auto_tiles_meta = str(auto_tiles_meta_path)
        except Exception as _e:
            print(
                f"[STEP 12] Failed to prepare deterministic auto tile metadata: {_e}"
            )
    perception_manual = getattr(s, "PERCEPTION_MANUAL_JSON", None)
    perception_auto = getattr(s, "PERCEPTION_AUTO_JSON", None)

    gap_out_dir = os.path.join(
        self.out_dir, getattr(s, "DOMAIN_GAP_OUT_DIR", "domain_gap")
    )
    os.makedirs(gap_out_dir, exist_ok=True)

    # Thesis evidence: coordinate reports (manual vs auto)
    try:
        import subprocess as _subprocess
        import sys as _sys

        coord_manual = os.path.join(gap_out_dir, "coord_manual.json")
        coord_auto = os.path.join(gap_out_dir, "coord_auto.json")
        _subprocess.run(
            [
                _sys.executable,
                "-m",
                "ultimate_pipeline.tools.xodr_coordinate_report",
                "--xodr",
                str(manual_xodr),
                "--out",
                coord_manual,
            ],
            check=False,
        )
        _subprocess.run(
            [
                _sys.executable,
                "-m",
                "ultimate_pipeline.tools.xodr_coordinate_report",
                "--xodr",
                str(auto_xodr),
                "--out",
                coord_auto,
            ],
            check=False,
        )
        print(f"[STEP 12] coord_manual.json -> {coord_manual}")
        print(f"[STEP 12] coord_auto.json -> {coord_auto}")
    except Exception as _e:
        print(f"[STEP 12] coordinate report skipped: {_e}")

    try:
        if auto_tiles_meta:
            os.environ["UP_AUTO_META"] = auto_tiles_meta
            os.environ["UP_AUTO_META_SOURCE"] = "main_pipeline_step12"
        combined_gap = run_full_domain_gap(
            manual_xodr=manual_xodr,
            auto_xodr=auto_xodr,
            manual_tiles=manual_tiles,
            auto_tiles=auto_tiles,
            perception_manual_json=perception_manual,
            perception_auto_json=perception_auto,
            output_dir=gap_out_dir,
        )

        sdg = combined_gap.get("structural_domain_gap", {})
        pt = combined_gap.get("per_tile_structural_gap", {})

        summary = {
            "whole_geometry_gap": sdg.get("geometry", {}),
            "whole_curvature_gap": sdg.get("curvature", {}),
            "whole_intersection_gap": sdg.get("intersection", {}),
            "whole_semantic_gap": sdg.get("semantics", {}),
            "whole_road_class_gap": sdg.get("road_classification", {}),
            "per_tile_geometry_gap": pt.get("geometry", {}),
            "per_tile_curvature_gap": pt.get("curvature", {}),
            "tile_seam_statistics": self.vreport.data.get("seam_statistics", []),
        }

        # Persist summary to disk (artifact)
        gap_summary_path = os.path.join(gap_out_dir, "domain_gap_summary.json")
        with open(gap_summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        # Optional experiment tracking / artifact registry
        if hasattr(self, "artifact_recorder"):
            self.artifact_recorder.record(
                run_id=getattr(self, "run_id", None),
                artifact_type="domain_gap_summary",
                path=gap_summary_path,
            )

        # Also keep it inside ValidationReport (for final summary & LLM)
        self.vreport.add_dict("domain_gap_summary", summary)

        print(f"✅ Domain-gap analysis complete → {gap_summary_path}")

    except Exception as e:
        print(f"⚠️ Domain-gap analysis failed: {e}")
        self.vreport.add("domain_gap", "error", str(e))


