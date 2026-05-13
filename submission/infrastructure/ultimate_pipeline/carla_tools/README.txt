Fixed modules for ultimate_pipeline main_pipeline compatibility

Key fixes included:
- carla_sim_consolidated.py: pygame optional at import-time (HPC-safe), fixed event handling,
  removed stray global load_single_tile(), added CarlaSimulation.load_single_tile().
- screenshot_generator.py: pygame optional at import-time; headless save_to_disk fallback.
- carla_recovery.py + local/perception runners: fixed SETTINGS import path.
- tile_world_runner.py: provides TileWorldRunner class expected by perception_runner_hpc.py.
- perception_runner_hpc.py: resolves tile ids to paths; refreshes world/map after tile load.
- road_defect_detector.py: TrafficManager is optional; safer autopilot setup.
- carla_final_test.py: robust autostart/connect flow; optional client injection.

Where to place:
  ultimate_pipeline/carla_tools/<file>.py  (replace existing files)

Notes:
  - These are drop-in replacements; no main_pipeline edits required.
