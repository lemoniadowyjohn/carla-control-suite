
import carla, time, json
from ultimate_pipeline.carla_tools.spawn_hardening import settle, spawn_ego

def run(host, port, out_dir):
    c=carla.Client(host,port); c.set_timeout(20.0)
    w=c.get_world()
    settle(w)
    bp=w.get_blueprint_library().find("vehicle.lincoln.mkz2017")
    ego=spawn_ego(w,bp,w.get_map().get_spawn_points())
    ego.set_autopilot(True)
    start=time.time(); dist0=ego.get_location()
    time.sleep(5)
    dist1=ego.get_location()
    ego.destroy()
    d=((dist1.x-dist0.x)**2+(dist1.y-dist0.y)**2)**0.5
    res={"moved_m":d}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir/"drivability.json").write_text(json.dumps(res,indent=2),encoding="utf-8")
    return res
