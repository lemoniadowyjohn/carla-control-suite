import json, math
import numpy as np
from pathlib import Path

from ultimate_pipeline.sensors.dominik_sensor_setup import DominikSensorSetup, _matrix_to_transform
import ultimate_pipeline.sensors.rig_transforms as rt

calib_path = Path("calib_data.json")
calib = json.loads(calib_path.read_text(encoding="utf-8"))

setup = DominikSensorSetup(
    str(calib_path),
    flip_vehicle_y=True,
    opencv_camera_axes=True,
    lidar_axes_mode="auto",
)

# pick one camera + lidar
cam_name, cam_data = next(iter(calib["cameras"].items()))
lid_name, lid_data = next(iter(calib["lidars"].items()))

# expected from canonical helper
Tc = rt.camera_attachment_T_from_cTv(np.array(cam_data["cTv"], dtype=np.float64),
                                     flip_vehicle_y=True, opencv_camera_axes=True)
Tl = rt.lidar_attachment_T_from_vTl(np.array(lid_data["vTl"], dtype=np.float64),
                                    flip_vehicle_y=True)

exp_cam = _matrix_to_transform(Tc)
exp_lid = _matrix_to_transform(Tl)

# actual from DominikSensorSetup path
act_cam = setup._parse_camera_transform(cam_data)
act_lid = setup._parse_lidar_transform(lid_data)

def close(a,b, tol): return abs(float(a)-float(b)) <= tol

def check(name, exp, act):
    errs=[]
    for k,tol in [("x",1e-3),("y",1e-3),("z",1e-3),("roll",1e-2),("pitch",1e-2),("yaw",1e-2)]:
        if not close(exp[k], act[k], tol):
            errs.append((k, exp[k], act[k]))
    if errs:
        print(f"FAIL {name}:")
        for e in errs:
            print(" ", e)
        raise SystemExit(2)
    print(f"OK   {name}")

check(f"camera {cam_name}", exp_cam, act_cam)
check(f"lidar  {lid_name}", exp_lid, act_lid)
print("All OK.")

