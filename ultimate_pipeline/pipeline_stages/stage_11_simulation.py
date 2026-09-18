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

# ---------------- 12) 📊 DOMAIN GAP ----------------

