from __future__ import annotations

"""Autopilot diagnostics (CARLA required).

This module is intentionally import-safe on machines without the CARLA Python API
(e.g., HPC/CI). Functions that require CARLA call _require_carla() at runtime.

Design goals:
- Safe to import without CARLA installed (carla=None).
- No side effects at import time.
- Explicit cleanup of spawned actors/sensors.
"""

from typing import List, Optional, TYPE_CHECKING
import time
import random

try:
    import carla  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    carla = None  # type: ignore

from ultimate_pipeline.sensors.recorder import SensorRecorder

if TYPE_CHECKING:  # pragma: no cover
    import carla as carla_t  # type: ignore


def _require_carla() -> None:
    if carla is None:
        raise ModuleNotFoundError(
            "CARLA Python API is not installed. Autopilot diagnostics require CARLA."
        )


class AutopilotTest:
    @staticmethod
    def run(
        client: "carla_t.Client",
        vehicle_count: int = 10,
        seconds: float = 10.0,
        enable_recording: bool = True,
        logs_dir: Optional[str] = None,
    ) -> bool:
        """Spawn vehicles, enable autopilot, tick for N seconds, optionally record sensors."""
        _require_carla()

        print("\n[autopilot] spawning vehicles and running smoke test...")
        world = client.get_world()
        bp_lib = world.get_blueprint_library()
        vehicle_bps = bp_lib.filter("vehicle.*")

        if not vehicle_bps:
            print("[autopilot] no vehicle blueprints found")
            return False

        spawn_points: List["carla_t.Transform"] = world.get_map().get_spawn_points()
        if not spawn_points:
            print("[autopilot] no spawn points available")
            return False

        random.shuffle(spawn_points)
        vehicles: List["carla_t.Actor"] = []
        sensors: List["carla_t.Actor"] = []

        recorder: Optional[SensorRecorder] = None

        try:
            for i in range(min(vehicle_count, len(spawn_points))):
                bp = random.choice(vehicle_bps)
                transform = spawn_points[i]
                v = world.try_spawn_actor(bp, transform)
                if v is not None:
                    v.set_autopilot(True)
                    vehicles.append(v)

            print(f"[autopilot] spawned {len(vehicles)} vehicles")

            if enable_recording and logs_dir:
                recorder = SensorRecorder(world, logs_dir)
                # SensorRecorder API varies; keep this defensive.
                if hasattr(recorder, "attach_to_vehicles"):
                    sensors = recorder.attach_to_vehicles(vehicles)  # type: ignore

            t0 = time.time()
            while time.time() - t0 < seconds:
                world.tick()

            if recorder and hasattr(recorder, "stop"):
                recorder.stop()

            print("[autopilot] completed")
            return True

        except Exception as e:
            print(f"[autopilot] error: {e}")
            return False

        finally:
            # Cleanup sensors then vehicles
            for s in sensors:
                try:
                    if hasattr(s, "stop"):
                        s.stop()  # type: ignore
                except Exception:
                    pass
                try:
                    s.destroy()
                except Exception:
                    pass

            for v in vehicles:
                try:
                    v.destroy()
                except Exception:
                    pass
