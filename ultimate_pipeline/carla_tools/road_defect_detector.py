# ultimate_pipeline/carla_tools/road_defect_detector.py

from __future__ import annotations
import carla
import time
import math
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional


@dataclass
class DefectEvent:
    """
    A single detected road defect event.
    """
    type: str               # "stuck", "collision", "z_jump"
    timestamp: float
    location_x: float
    location_y: float
    location_z: float
    speed: float
    extra: Dict


class RoadDefectDetector:
    """
    Sensor-based road defect detector.

    Uses:
      - vehicle speed over time → 'stuck' detection
      - collision sensor → collision hot-spots
      - z-position monitoring → elevation jumps

    Intended usage:
      1) Load tile or full map in CARLA.
      2) Run RoadDefectDetector.scan_world(...) for N seconds.
      3) Save defects to JSON / log.
    """

    def __init__(
        self,
        client: carla.Client,
        min_speed_threshold: float = 0.1,
        stuck_time_threshold: float = 5.0,
        z_jump_threshold: float = 0.5,
    ):
        self.client = client
        self.min_speed_threshold = min_speed_threshold
        self.stuck_time_threshold = stuck_time_threshold
        self.z_jump_threshold = z_jump_threshold

        self._collision_events: List[DefectEvent] = []
        self._vehicles: List[carla.Vehicle] = []
        self._coll_sensors: List[carla.Sensor] = []
        self._tick_data: Dict[int, List[tuple[float, float, float]]] = {}
        self._last_z: Dict[int, float] = {}
        self._stuck_start: Dict[int, float] = {}
        self._defects: List[DefectEvent] = []

    # --------------------------------------------
    # Collision callback
    # --------------------------------------------
    def _on_collision(self, event: carla.CollisionEvent):
        actor = event.actor
        if not actor or not isinstance(actor, carla.Vehicle):
            return

        loc = actor.get_transform().location
        speed = actor.get_velocity().length()
        t = time.time()

        self._collision_events.append(
            DefectEvent(
                type="collision",
                timestamp=t,
                location_x=loc.x,
                location_y=loc.y,
                location_z=loc.z,
                speed=speed,
                extra={"other_actor": str(event.other_actor)}
            )
        )

    # --------------------------------------------
    # Vehicle spawn helpers
    # --------------------------------------------
    def _spawn_vehicles(self, world: carla.World, num: int = 5) -> None:
        bp_lib = world.get_blueprint_library()
        vehicle_bp = bp_lib.filter("vehicle.*")

        spawn_points = world.get_map().get_spawn_points()
        if not spawn_points:
            print("⚠️ No spawn points available for defect detector.")
            return

        count = min(num, len(spawn_points))
        tm = None
        try:
            tm = self.client.get_trafficmanager()
            tm.set_global_distance_to_leading_vehicle(2.0)
            tm.set_synchronous_mode(False)
        except Exception:
            # OpenDRIVE standalone worlds sometimes don't have a TrafficManager
            # configured/available. We can still try autopilot without TM.
            tm = None

        for i in range(count):
            bp = vehicle_bp[i % len(vehicle_bp)]
            sp = spawn_points[i]
            v = world.try_spawn_actor(bp, sp)
            if not v:
                continue

            try:
                if tm is not None:
                    v.set_autopilot(True, tm.get_port())
                else:
                    v.set_autopilot(True)
            except Exception:
                # Worst case: leave it spawned but not on autopilot
                pass
            self._vehicles.append(v)

            # Attach collision sensor
            coll_bp = bp_lib.find("sensor.other.collision")
            coll = world.spawn_actor(coll_bp, carla.Transform(), attach_to=v)
            coll.listen(self._on_collision)
            self._coll_sensors.append(coll)

            # init tracking
            self._tick_data[v.id] = []
            self._last_z[v.id] = v.get_transform().location.z

        print(f"🚗 RoadDefectDetector spawned {len(self._vehicles)} vehicles for scanning.")

    def _destroy_actors(self):
        for s in self._coll_sensors:
            if s.is_alive:
                s.stop()
                s.destroy()
        for v in self._vehicles:
            if v.is_alive:
                v.set_autopilot(False)
                v.destroy()

        self._vehicles.clear()
        self._coll_sensors.clear()
        self._tick_data.clear()
        self._last_z.clear()
        self._stuck_start.clear()

    # --------------------------------------------
    # Main scan loop
    # --------------------------------------------
    def _update_vehicle_state(self, v: carla.Vehicle, now: float):
        vel = v.get_velocity()
        speed = math.sqrt(vel.x ** 2 + vel.y ** 2 + vel.z ** 2)
        loc = v.get_transform().location

        self._tick_data[v.id].append((now, speed, loc.z))

        # Z jump detection
        last_z = self._last_z.get(v.id, loc.z)
        if abs(loc.z - last_z) > self.z_jump_threshold:
            self._defects.append(
                DefectEvent(
                    type="z_jump",
                    timestamp=now,
                    location_x=loc.x,
                    location_y=loc.y,
                    location_z=loc.z,
                    speed=speed,
                    extra={"delta_z": loc.z - last_z}
                )
            )
        self._last_z[v.id] = loc.z

        # Stuck detection
        if speed < self.min_speed_threshold:
            if v.id not in self._stuck_start:
                self._stuck_start[v.id] = now
            else:
                dt = now - self._stuck_start[v.id]
                if dt >= self.stuck_time_threshold:
                    self._defects.append(
                        DefectEvent(
                            type="stuck",
                            timestamp=now,
                            location_x=loc.x,
                            location_y=loc.y,
                            location_z=loc.z,
                            speed=speed,
                            extra={"stuck_duration": dt}
                        )
                    )
                    # reset so we don't spam
                    self._stuck_start[v.id] = now
        else:
            # reset stuck timer when moving
            if v.id in self._stuck_start:
                del self._stuck_start[v.id]

    def scan_world(
        self,
        world: carla.World,
        duration_sec: float = 60.0,
        num_vehicles: int = 5,
    ) -> List[DefectEvent]:
        """
        Run a scan on the current world instance.
        """
        print(f"🧪 Starting road defect scan for {duration_sec} seconds...")
        self._defects.clear()
        self._collision_events.clear()

        self._spawn_vehicles(world, num_vehicles)

        start = time.time()
        try:
            while time.time() - start < duration_sec:
                world.tick()
                now = time.time()
                for v in self._vehicles:
                    if not v.is_alive:
                        continue
                    self._update_vehicle_state(v, now)
        finally:
            self._destroy_actors()

        # Merge collision events into defects
        self._defects.extend(self._collision_events)
        print(f"✅ RoadDefectDetector found {len(self._defects)} potential defects.")
        return self._defects

    # --------------------------------------------
    # Helper to convert to serializable list
    # --------------------------------------------
    @staticmethod
    def defects_to_dict_list(defects: List[DefectEvent]) -> List[Dict]:
        return [asdict(d) for d in defects]
