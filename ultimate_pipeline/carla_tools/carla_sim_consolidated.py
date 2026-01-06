#!/usr/bin/env python3
"""
Consolidated CARLA Simulator
----------------------------
Clean + corrected version with:
- Tile streaming
- Mesh streaming
- Actor streaming
- Scenario manager (using FixedTrafficManager)
- MANUAL / AUTO ego control
- Fully synchronous-safe tick()
- Top-down camera for tile inspection
"""

from __future__ import annotations

import math
import random
import time
from typing import Optional

import numpy as np

# NOTE: main_pipeline imports this module unconditionally.
# pygame must therefore be optional at import-time (e.g., headless HPC nodes).
try:
    import pygame  # type: ignore
    _PYGAME_AVAILABLE = True
except Exception:  # pragma: no cover
    pygame = None  # type: ignore
    _PYGAME_AVAILABLE = False

try:
    import carla
except ImportError:
    raise RuntimeError("CARLA PythonAPI not found. Ensure it's on PYTHONPATH.")

from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world

# external managers
from ultimate_pipeline.carla_tools.tile_streamer import TileStreamer
from ultimate_pipeline.carla_tools.mesh_streamer import MeshStreamer
from ultimate_pipeline.carla_tools.actor_stream_manager import ActorStreamManager
from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.carla_tools.fixed_traffic_manager import create_traffic_manager


# =====================================================================
# Utility helpers
# =====================================================================

def carla_vec_to_kmh(v) -> float:
    return 3.6 * math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)


# =====================================================================
# Scenario Manager (thin wrapper around FixedTrafficManager)
# =====================================================================

class ScenarioManager:
    """
    Lightweight scenario wrapper that uses FixedTrafficManager for:
    - spawning / clearing traffic
    - spawning / clearing pedestrians

    No direct calls to world.get_trafficmanager() → no crash.
    """

    def __init__(self, world: "carla.World", client: "carla.Client"):
        self.world = world
        self.client = client
        self.tm_wrapper = create_traffic_manager()
        # Safe: will just disable TM features if not available
        self.tm_wrapper.initialize(client, world)

    def create_busy_scenario(self) -> None:
        """Spawn a busy scenario with vehicles + pedestrians."""
        print("[Scenario] Creating busy scenario…")
        # Use your SETTINGS limits if you like, otherwise fixed numbers
        num_veh = getattr(SETTINGS, "STREAM_MAX_VEHICLES", 25)
        num_walk = getattr(SETTINGS, "STREAM_MAX_WALKERS", 25)

        self.tm_wrapper.spawn_vehicles(num_veh)
        self.tm_wrapper.spawn_pedestrians(num_walk)

        status = self.tm_wrapper.get_traffic_status()
        print(f"[Scenario] Busy scenario ready: {status}")

    def create_anomalies(self) -> None:
        """
        Simple anomaly scenario:
        - spawn traffic & pedestrians via FixedTrafficManager
        - add a stopped vehicle as anomaly, if possible
        """
        print("[Scenario] Creating anomaly scenario…")

        # First some “normal” traffic, but less than busy mode
        self.tm_wrapper.spawn_vehicles(10)
        self.tm_wrapper.spawn_pedestrians(8)

        # Try to spawn one stopped vehicle anomaly
        try:
            bp_lib = self.world.get_blueprint_library()
            veh_bps = bp_lib.filter("vehicle.*")
            spawn_points = self.world.get_map().get_spawn_points()

            if veh_bps and spawn_points:
                sp = random.choice(spawn_points)
                bp = random.choice(veh_bps)
                bp.set_attribute("role_name", "anomaly")

                v = self.world.try_spawn_actor(bp, sp)
                if v:
                    v.set_autopilot(False)
                    v.apply_control(carla.VehicleControl(throttle=0.0, brake=1.0))
                    print("[Scenario] Spawned stopped vehicle anomaly")
        except Exception as e:
            print(f"[Scenario] Failed to spawn anomaly vehicle: {e}")

        status = self.tm_wrapper.get_traffic_status()
        print(f"[Scenario] Anomaly scenario ready: {status}")

    def cleanup(self) -> None:
        """Clear all traffic and pedestrians spawned via FixedTrafficManager."""
        print("[Scenario] Cleaning up scenario actors...")
        self.tm_wrapper.clear_vehicles()
        self.tm_wrapper.clear_pedestrians()
        print("[Scenario] Cleanup done.")


# =====================================================================
# Carla Simulation
# =====================================================================

class CarlaSimulation:

    def __init__(
        self,
        host: str = "localhost",
        port: int = 2000,
        w: int = 1280,
        h: int = 720,
        use_synchronous: bool = True,
        use_scenarios: bool = True,
        tile_streamer: Optional[TileStreamer] = None,
        mesh_streamer: Optional[MeshStreamer] = None,
        actor_manager: Optional[ActorStreamManager] = None,
    ):
        if not _PYGAME_AVAILABLE:
            raise RuntimeError(
                "pygame is required for CarlaSimulation (interactive simulator). "
                "Install pygame or disable Step 12 / interactive mode."
            )

        self.host = host
        self.port = port
        self.w = w
        self.h = h
        self.use_synchronous = use_synchronous
        self.use_scenarios = use_scenarios

        self.tile_streamer = tile_streamer
        self.mesh_streamer = mesh_streamer
        self.actor_manager = actor_manager

        pygame.init()
        self.display = pygame.display.set_mode((w, h))
        pygame.display.set_caption("CARLA Simulator – Tile Inspector")
        self.clock = pygame.time.Clock()
        self.running = True

        self.client = carla.Client(host, port)
        self.client.set_timeout(10.0)
        self.world = self.client.get_world()

        self.vehicle: Optional[carla.Vehicle] = None
        self.camera: Optional[carla.Sensor] = None
        self.camera_img = None
        # Camera mode handling
        self.camera_mode = "TOP"  # "TOP", "DRIVER", "CHASE"
        self.camera_bp = None  # store blueprint for re-use

        self.mode = "MANUAL"  # or "AUTO"
        self.scenario_manager: Optional[ScenarioManager] = None


        self._setup_world()
        self._spawn_vehicle()
        self._setup_camera()

        if self.use_scenarios and getattr(SETTINGS, "ENABLE_SCENARIO_MANAGER", True):
            self.scenario_manager = ScenarioManager(self.world, self.client)

        print("Controls:")
        print("  W/S/A/D   driving")
        print("  M         toggle MANUAL/AUTO")
        print("  B         busy traffic scenario")
        print("  N         anomaly scenario")
        print("  C         switch camera")
        print("  ESC       quit")

    # -------------------- Setup --------------------

    def _setup_world(self) -> None:
        settings = self.world.get_settings()
        if self.use_synchronous:
            settings.synchronous_mode = True
            settings.fixed_delta_seconds = 0.05
        else:
            settings.synchronous_mode = False
            settings.fixed_delta_seconds = None
        self.world.apply_settings(settings)
        print(f"[Sim] World synchronous={self.use_synchronous}")

    def load_single_tile(self, tile_xodr: str, sleep_sec: float = 1.0) -> None:
        """Load a single OpenDRIVE tile into CARLA.

        This is *not* used by the main pipeline directly, but is convenient for
        interactive debugging.

        NOTE: Loading a new world invalidates current actors. The caller should
        restart the simulation session afterwards or respawn actors.
        """
        print(f"🧩 Loading tile: {tile_xodr}")

        with open(tile_xodr, "r", encoding="utf-8") as f:
            data = f.read()

        params = carla.OpendriveGenerationParameters()
        params.map_layers = carla.MapLayer.NONE
        self.world = load_opendrive_world(
            self.client,
            data,
            params=params,
            timeout_s=180.0,
            retries=2,
            do_reload=True,
        )
        if sleep_sec > 0:
            time.sleep(sleep_sec)

        # Re-apply sync settings on the new world
        self._setup_world()

    def _spawn_vehicle(self) -> None:
        bps = self.world.get_blueprint_library().filter("vehicle.*")
        if not bps:
            raise RuntimeError("No vehicle blueprints available.")

        bp = random.choice(bps)
        bp.set_attribute("role_name", "ego")

        spawn_points = self.world.get_map().get_spawn_points()
        if not spawn_points:
            raise RuntimeError("No spawn points on map.")

        sp = random.choice(spawn_points)
        vehicle = self.world.try_spawn_actor(bp, sp)
        if not vehicle:
            raise RuntimeError("Failed to spawn ego vehicle.")
        self.vehicle = vehicle
        print("✓ Ego vehicle spawned")

    def _setup_camera(self) -> None:
        """
        Initial camera setup.
        Starts in top-down mode, but we can switch later.
        """
        bp = self.world.get_blueprint_library().find("sensor.camera.rgb")
        bp.set_attribute("image_size_x", str(self.w))
        bp.set_attribute("image_size_y", str(self.h))
        bp.set_attribute("fov", "90")  # fairly wide

        self.camera_bp = bp  # store for later reuse

        # Start in TOP mode
        cam_tf = carla.Transform(
            carla.Location(x=0.0, y=0.0, z=80.0),
            carla.Rotation(pitch=-90.0, yaw=0.0, roll=0.0),
        )
        self.camera_mode = "TOP"

        self.camera = self.world.spawn_actor(self.camera_bp, cam_tf, attach_to=self.vehicle)
        self.camera.listen(self._camera_callback)
        print("✓ Top-down camera attached above ego")

        # Optional: move spectator to match
        try:
            spectator = self.world.get_spectator()
            spectator.set_transform(
                carla.Transform(
                    self.vehicle.get_location() + carla.Location(z=80.0),
                    carla.Rotation(pitch=-90.0),
                )
            )
        except Exception as e:
            print(f"[Sim] Failed to move spectator: {e}")

    def _switch_camera(self) -> None:
        """
        Cycle camera between:
        - TOP     (80 m above)
        - DRIVER  (driver seat)
        - CHASE   (3rd person behind)
        """
        if not self.vehicle or not self.camera_bp:
            return

        # Decide next mode
        if self.camera_mode == "TOP":
            self.camera_mode = "DRIVER"
            cam_tf = carla.Transform(
                carla.Location(x=0.4, y=0.0, z=1.6),
                carla.Rotation(pitch=0.0, yaw=0.0, roll=0.0),
            )
        elif self.camera_mode == "DRIVER":
            self.camera_mode = "CHASE"
            cam_tf = carla.Transform(
                carla.Location(x=-6.0, y=0.0, z=2.5),
                carla.Rotation(pitch=-10.0, yaw=0.0, roll=0.0),
            )
        else:
            self.camera_mode = "TOP"
            cam_tf = carla.Transform(
                carla.Location(x=0.0, y=0.0, z=80.0),
                carla.Rotation(pitch=-90.0, yaw=0.0, roll=0.0),
            )

        # Destroy old camera safely
        try:
            if self.camera is not None:
                self.camera.stop()
                self.camera.destroy()
        except Exception:
            pass

        # Spawn new camera with updated transform
        self.camera = self.world.spawn_actor(self.camera_bp, cam_tf, attach_to=self.vehicle)
        self.camera.listen(self._camera_callback)

        print(f"[Sim] Camera mode → {self.camera_mode}")


    # -------------------- Camera --------------------

    def _camera_callback(self, image: "carla.Image") -> None:
        arr = np.frombuffer(image.raw_data, dtype=np.uint8)
        arr = arr.reshape((image.height, image.width, 4))[:, :, :3]
        self.camera_img = arr

    # -------------------- Player Control --------------------

    def _apply_manual_control(self, keys) -> None:
        ctrl = carla.VehicleControl(
            throttle=0.5 if keys[pygame.K_w] else 0.0,
            brake=0.6 if keys[pygame.K_s] else 0.0,
            steer=(-0.5 if keys[pygame.K_a] else 0.5 if keys[pygame.K_d] else 0.0),
        )
        self.vehicle.apply_control(ctrl)

    def _apply_auto_control(self) -> None:
        speed = carla_vec_to_kmh(self.vehicle.get_velocity())
        ctrl = carla.VehicleControl()
        ctrl.throttle = 0.4 if speed < 45 else 0.0
        # simple sine-wave steering just to see motion
        ctrl.steer = math.sin(time.time() * 0.3) * 0.25
        self.vehicle.apply_control(ctrl)

    # -------------------- Events --------------------

    def _handle_events(self) -> None:
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                self.running = False
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    self.running = False
                elif e.key == pygame.K_m:
                    self.mode = "AUTO" if self.mode == "MANUAL" else "MANUAL"
                    print(f"[Sim] Mode → {self.mode}")
                elif e.key == pygame.K_b and self.scenario_manager:
                    self.scenario_manager.create_busy_scenario()
                elif e.key == pygame.K_n and self.scenario_manager:
                    self.scenario_manager.create_anomalies()
                elif e.key == pygame.K_c:
                    self._switch_camera()

    # -------------------- Drawing --------------------

    def _draw_camera(self) -> None:
        if self.camera_img is None:
            self.display.fill((0, 0, 0))
        else:
            surf = pygame.surfarray.make_surface(self.camera_img.swapaxes(0, 1))
            self.display.blit(surf, (0, 0))

        font = pygame.font.Font(None, 32)
        text = font.render(self.mode, True,
                           (0, 255, 0) if self.mode == "AUTO" else (255, 255, 0))
        self.display.blit(text, (20, 20))
        cam_text = font.render(self.camera_mode, True, (255, 255, 255))
        self.display.blit(cam_text, (20, 50))

    # -------------------- Main tick --------------------

    def tick(self) -> None:
        # Advance CARLA world
        if self.use_synchronous:
            self.world.tick()
        else:
            self.world.wait_for_tick()

        # Tile streaming: load/unload tiles around ego
        if self.tile_streamer and self.vehicle:
            try:
                self.tile_streamer.stream_once(self.vehicle)
            except Exception as e:
                print(f"[TileStreamer] Error: {e}")

        # Mesh streaming: update visible static meshes
        if self.mesh_streamer:
            try:
                self.mesh_streamer.update()
            except Exception as e:
                print(f"[MeshStreamer] Error: {e}")

        # Actor streaming: spawn/despawn NPCs around ego
        if self.actor_manager and self.vehicle:
            try:
                self.actor_manager.update(self.vehicle)
            except Exception as e:
                print(f"[ActorStreamManager] Error: {e}")

        pygame.display.flip()
        self.clock.tick(30)

    # -------------------- Cleanup --------------------

    def cleanup(self) -> None:
        print("[Sim] Cleaning up...")
        if self.scenario_manager:
            self.scenario_manager.cleanup()
        if self.camera:
            try:
                self.camera.stop()
            except Exception:
                pass
            self.camera.destroy()
        if self.vehicle:
            self.vehicle.destroy()
        pygame.quit()
        print("[Sim] Cleanup finished.")

    # -------------------- Run --------------------

    def run(self) -> None:
        print("✓ Simulator running")

        while self.running:
            self._handle_events()
            keys = pygame.key.get_pressed()

            if self.vehicle:
                if self.mode == "MANUAL":
                    self._apply_manual_control(keys)
                else:
                    self._apply_auto_control()

            self._draw_camera()
            self.tick()

        self.cleanup()


# =====================================================================
# Entry
# =====================================================================

if __name__ == "__main__":
    sim = CarlaSimulation(
        host=SETTINGS.CARLA_HOST,
        port=SETTINGS.CARLA_PORT,
        w=SETTINGS.SIM_VIEWPORT_W,
        h=SETTINGS.SIM_VIEWPORT_H,
        use_synchronous=True,
        use_scenarios=getattr(SETTINGS, "ENABLE_SCENARIO_MANAGER", True),
    )
    sim.run()
