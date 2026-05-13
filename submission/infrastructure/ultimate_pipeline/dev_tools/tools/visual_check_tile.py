import sys
from ultimate_pipeline.carla_tools.carla_sim_consolidated import CarlaSimulation
from ultimate_pipeline.config.settings import SETTINGS

if len(sys.argv) < 2:
    print("Usage: python visual_check_tile.py <tile.xodr>")
    sys.exit(1)

sim = CarlaSimulation(
    host=SETTINGS.CARLA_HOST,
    port=SETTINGS.CARLA_PORT,
    w=1280,
    h=720,
    use_synchronous=False,
    use_scenarios=False,
)

sim.load_single_tile(sys.argv[1])
sim.run()
