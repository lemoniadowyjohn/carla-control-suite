import carla
import time
import json
import sys

def run_liveness_gate(map_name, host='localhost', port=2000):
    client = carla.Client(host, port)
    client.set_timeout(30.0)
    
    print(f"Loading map: {map_name}")
    try:
        world = client.load_world(map_name)
        print(f"Loaded map: {world.get_map().name}")
    except Exception as e:
        print(f"Failed to load map: {e}")
        return False
    
    blueprint_lib = world.get_blueprint_library()
    
    # Spawn ego
    bp = blueprint_lib.find('vehicle.tesla.model3')
    spawn_points = world.get_map().get_spawn_points()
    if not spawn_points:
        print("No spawn points found")
        return False
    ego = world.spawn_actor(bp, spawn_points[0])
    
    # Attach RGB
    cam_bp = blueprint_lib.find('sensor.camera.rgb')
    cam_bp.set_attribute('image_size_x', '800')
    cam_bp.set_attribute('image_size_y', '600')
    cam = world.spawn_actor(cam_bp, carla.Transform(), attach_to=ego)
    
    results = {"callback_count": 0}
    def callback(image):
        results["callback_count"] += 1
        
    cam.listen(callback)
    
    # Run ticks
    for _ in range(20):
        world.tick()
        time.sleep(0.1)
        
    cam.stop()
    cam.destroy()
    ego.destroy()
    
    return results["callback_count"] > 0

if __name__ == '__main__':
    map_name = 'Grid0828'
    try:
        success = run_liveness_gate(map_name)
        print(f"Liveness success: {success}")
    except Exception as e:
        print(f"Liveness failed: {e}")
