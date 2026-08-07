"""DEPRECATED. Use the canonical loader entry point instead.

Replaced by:
  - `ultimate_pipeline.tools.start_carla_load_xodr` (CLI with autostart,
    configurable host/port/timeout/retries)
  - `ultimate_pipeline.core.carla_opendrive_loader.load_opendrive_world_from_file`

This thin wrapper hardcoded 127.0.0.1:2000, used emoji stdout (Windows-unstable)
and added no behavior beyond the canonical loader. Kept only for backwards
compatibility; it will be removed once no caller references it.
"""
import sys
import time
import carla

from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world_from_file

xodr_path = sys.argv[1]

client = carla.Client("127.0.0.1", 2000)

print("Loading final map into CARLA (DEPRECATED entry point)...")
world = load_opendrive_world_from_file(
    client,
    xodr_path,
    params=None,
    timeout_s=180.0,
    retries=2,
    do_reload=True,
    fallback_enabled=False,
)

print("Map loaded successfully.")
time.sleep(5)
