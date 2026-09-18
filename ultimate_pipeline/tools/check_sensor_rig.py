import time
import os

from ultimate_pipeline.utils.bootstrap import bootstrap_console

bootstrap_console()

import carla
from ultimate_pipeline.carla_tools.sensor_rig import SensorRig

# CONFIG
CALIB_JSON = "calib_data.json"  # Point to your uploaded file
OUTPUT_DIR = "ultimate_pipeline_out/sensor_check"


def main():
    if not os.path.exists(CALIB_JSON):
        print(f"❌ Missing {CALIB_JSON} - cannot verify rig.")
        return

    client = carla.Client('localhost', 2000)
    client.set_timeout(10.0)
    world = client.get_world()

    # Spawn Ego
    bp = world.get_blueprint_library().find('vehicle.tesla.model3')
    spawn_point = world.get_map().get_spawn_points()[0]
    ego = world.spawn_actor(bp, spawn_point)
    print("🚗 Ego vehicle spawned.")

    # Attach Rig
    rig = SensorRig(CALIB_JSON)
    sensors = rig.spawn_rig(client, ego)

    # Callback to save data
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    def save_img(image, sensor_id):
        path = f"{OUTPUT_DIR}/{sensor_id}_{image.frame}.png"
        image.save_to_disk(path)
        print(f"📸 Captured {sensor_id}")

    for name, sensor in sensors.items():
        if 'camera' in sensor.type_id:
            sensor.listen(lambda img, n=name: save_img(img, n))

    # Tick
    ego.set_autopilot(True)
    print("⏳ Ticking simulation for 2 seconds...")
    time.sleep(2.0)

    # Cleanup
    for s in sensors.values():
        s.stop()
        s.destroy()
    ego.destroy()
    print(f"✅ Check complete. Inspect images in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
