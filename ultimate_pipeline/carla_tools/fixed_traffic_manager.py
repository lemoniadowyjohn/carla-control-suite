# ultimate_pipeline/carla_tools/fixed_traffic_manager.py

import logging
import random
import time

logger = logging.getLogger(__name__)

# -----------------------------------------------------------
# CARLA availability check
# -----------------------------------------------------------
try:
    import carla
    CARLA_AVAILABLE = True
    print("✅ CARLA Python API available")
except ImportError:
    CARLA_AVAILABLE = False
    carla = None
    print("❌ CARLA Python API not available – using mock traffic manager")


# ===========================================================
# FIXED TRAFFIC MANAGER (SAFE FOR OPENDRIVE MAPS)
# ===========================================================
class FixedTrafficManager:
    """
    A safe traffic manager wrapper that:
    - gracefully disables TM features when unavailable
    - spawns vehicles/pedestrians without crashing
    - provides fallback AI for walkers
    """

    def __init__(self):
        self.vehicles = []
        self.pedestrians = []
        self.controllers = []
        self.vehicle_count = 0
        self.pedestrian_count = 0
        self.traffic_manager = None
        self.world = None
        self.client = None
        self.tm_available = False

    # -------------------------------------------------------
    # INITIALIZATION
    # -------------------------------------------------------
    def initialize(self, client, world, traffic_manager_port=8000):
        """Initialize TM if available. Always succeeds safely."""
        self.client = client
        self.world = world

        if not CARLA_AVAILABLE:
            print("⚠ No CARLA — using mock mode.")
            return False

        try:
            # Attempt TM retrieval (fails on OpenDRIVE)
            self.traffic_manager = self.client.get_trafficmanager(traffic_manager_port)
            self.traffic_manager.set_global_distance_to_leading_vehicle(2.0)
            self.traffic_manager.set_synchronous_mode(True)
            self.tm_available = True
            print("✅ Traffic Manager initialized")
            return True

        except Exception as e:
            # Safe fallback: no TM available
            print(f"⚠ Traffic Manager NOT available in this world: {e}")
            self.traffic_manager = None
            self.tm_available = False
            return False

    # -------------------------------------------------------
    # VEHICLE SPAWNING
    # -------------------------------------------------------
    def spawn_vehicles(self, count=20):
        """Spawn vehicles safely without requiring Traffic Manager."""
        if not CARLA_AVAILABLE or not self.world:
            print("❌ CARLA not available")
            return 0

        self.clear_vehicles()
        print(f"🚗 Spawning {count} vehicles...")

        spawn_points = self.world.get_map().get_spawn_points()
        blueprint_library = self.world.get_blueprint_library()

        vehicle_bps = [
            bp for bp in blueprint_library.filter("vehicle.*")
            if bp.has_attribute('number_of_wheels')
            and bp.get_attribute('number_of_wheels').as_int() == 4
        ]

        if not vehicle_bps:
            print("❌ No vehicle blueprints found")
            return 0

        batch = []

        for i in range(min(count, len(spawn_points))):
            bp = random.choice(vehicle_bps)
            sp = spawn_points[i]

            if self.tm_available:
                # Autopilot ONLY when TM exists
                cmd = carla.command.SpawnActor(bp, sp).then(
                    carla.command.SetAutopilot(
                        carla.command.FutureActor, True, self.traffic_manager.get_port()
                    )
                )
            else:
                # Simple spawn — NO autopilot
                cmd = carla.command.SpawnActor(bp, sp)

            batch.append(cmd)

        vehicles_spawned = 0
        for response in self.client.apply_batch_sync(batch):
            if response.error:
                print(f"❌ Vehicle spawn error: {response.error}")
            else:
                actor = self.world.get_actor(response.actor_id)
                if actor:
                    self.vehicles.append(actor)
                    vehicles_spawned += 1

        self.vehicle_count = vehicles_spawned
        print(f"✅ Spawned {vehicles_spawned} vehicles")
        return vehicles_spawned

    # -------------------------------------------------------
    # PEDESTRIAN SPAWNING
    # -------------------------------------------------------
    def spawn_pedestrians(self, count=10):
        if not CARLA_AVAILABLE or not self.world:
            print("❌ CARLA not available")
            return 0

        self.clear_pedestrians()
        print(f"🚶 Spawning {count} pedestrians...")

        blueprints = self.world.get_blueprint_library().filter("walker.pedestrian.*")

        if not blueprints:
            print("❌ No pedestrian blueprints found")
            return 0

        spawned = 0

        for i in range(count):
            try:
                loc = self.world.get_random_location_from_navigation()
                if not loc:
                    loc = carla.Location(
                        x=random.uniform(-50, 50),
                        y=random.uniform(-50, 50),
                        z=1.0
                    )

                transform = carla.Transform(loc)
                walker_bp = random.choice(blueprints)
                walker = self.world.try_spawn_actor(walker_bp, transform)

                if not walker:
                    continue

                controller_bp = self.world.get_blueprint_library().find(
                    "controller.ai.walker"
                )
                controller = self.world.try_spawn_actor(controller_bp, carla.Transform(), walker)

                if controller:
                    self.pedestrians.append(walker)
                    self.controllers.append(controller)
                    spawned += 1

            except Exception as e:
                print(f"⚠ Pedestrian spawn error: {e}")

        self.pedestrian_count = spawned
        self._start_pedestrian_ai()

        print(f"🎉 Spawned {spawned} pedestrians")
        return spawned

    # -------------------------------------------------------
    # UNIVERSAL PEDESTRIAN AI
    # -------------------------------------------------------
    def _start_pedestrian_ai(self):
        """Fallback walker AI that works in ALL CARLA worlds."""
        print("🤖 Starting pedestrian AI...")

        for ctrl in self.controllers:
            try:
                ctrl.start()
                dest = self.world.get_random_location_from_navigation()
                if dest:
                    ctrl.go_to_location(dest)
            except:
                pass

    # -------------------------------------------------------
    # CLEAR VEHICLES / PEDESTRIANS
    # -------------------------------------------------------
    def clear_vehicles(self):
        for a in self.vehicles:
            try:
                if a.is_alive:
                    a.destroy()
            except:
                pass

        print(f"🗑 Cleared {len(self.vehicles)} vehicles")
        self.vehicles = []
        self.vehicle_count = 0

    def clear_pedestrians(self):
        for c in self.controllers:
            try:
                if c.is_alive:
                    c.stop()
                    c.destroy()
            except:
                pass

        for p in self.pedestrians:
            try:
                if p.is_alive:
                    p.destroy()
            except:
                pass

        print(f"🗑 Cleared {len(self.pedestrians)} pedestrians")
        self.controllers = []
        self.pedestrians = []
        self.pedestrian_count = 0

    # -------------------------------------------------------
    # STATUS API
    # -------------------------------------------------------
    def get_traffic_status(self):
        return {
            "vehicles": self.vehicle_count,
            "pedestrians": self.pedestrian_count,
            "total": self.vehicle_count + self.pedestrian_count
        }


# ===========================================================
# FACTORY
# ===========================================================
def create_traffic_manager():
    """Factory that returns a real or mock TM."""
    if CARLA_AVAILABLE:
        return FixedTrafficManager()

    class MockTM:
        def initialize(self, *args, **kwargs): return True
        def spawn_vehicles(self, count=20): print("Mock vehicles:", count)
        def spawn_pedestrians(self, count=10): print("Mock walkers:", count)
        def clear_vehicles(self): pass
        def clear_pedestrians(self): pass
        def get_traffic_status(self): return {}

    return MockTM()
