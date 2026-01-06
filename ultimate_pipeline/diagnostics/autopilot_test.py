# ultimate_pipeline/diagnostics/autopilot_test.py

import time
import random
from typing import List

import carla

from ultimate_pipeline.sensors.recorder import SensorRecorder


class AutopilotTest:
    @staticmethod
    def run(client: carla.Client, vehicle_count: int = 10, seconds: float = 10.0,
            enable_recording: bool = True, logs_dir: str = None) -> bool:
        print("\n🚙 AutopilotTest: spawning vehicles and running smoke test...")
        world = client.get_world()
        bp_lib = world.get_blueprint_library()
        vehicle_bps = bp_lib.filter("vehicle.*")

        if not vehicle_bps:
            print("   ⚠ No vehicle blueprints found.")
            return False

        spawn_points: List[carla.Transform] = world.get_map().get_spawn_points()
        if not spawn_points:
            print("   ⚠ No spawn points available.")
            return False

        random.shuffle(spawn_points)
        vehicles = []
        sensors = []

        try:
            for i in range(min(vehicle_count, len(spawn_points))):
                bp = random.choice(vehicle_bps)
                transform = spawn_points[i]
                v = world.try_spawn_actor(bp, transform)
                if v is not None:
                    v.set_autopilot(True)
                    vehicles.append(v)

            print(f"   ✓ Spawned {len(vehicles)} vehicles.")
            recorder = None
            if enable_recording and logs_dir:
                recorder = SensorRecorder(world, logs_dir)
                sensors = recorder.attach_to_vehicles(vehicles)

            t0 = time.time()
            while time.time() - t0 < seconds:
                world.tick()

            if recorder:
                recorder.stop()
            print("   ✓ AutopilotTest completed.")
            return True
        except Exception as e:
            print(f"   ⚠ AutopilotTest error: {e}")
            return False
        finally:
            print("   Cleaning up actors...")
            for s in sensors:
                try:
                    s.stop()
                    s.destroy()
                except Exception:
                    pass
            for v in vehicles:
                try:
                    v.destroy()
                except Exception:
                    pass
