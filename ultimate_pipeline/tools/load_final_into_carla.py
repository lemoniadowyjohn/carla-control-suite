import sys
import time
import carla

from ultimate_pipeline.core.carla_opendrive_loader import load_opendrive_world

xodr_path = sys.argv[1]

client = carla.Client("127.0.0.1", 2000)

print("🚗 Loading final map into CARLA...")
xodr_text = open(xodr_path, "r", encoding="utf-8").read()

world = load_opendrive_world(
    client,
    xodr_text,
    params=None,
    timeout_s=180.0,
    retries=2,
    do_reload=True,
)

print("✅ Map loaded successfully.")
time.sleep(5)
