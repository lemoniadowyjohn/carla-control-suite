import sys
from pathlib import Path

sys.path.insert(0, ".")
import carla

XODR = Path(sys.argv[1] if len(sys.argv) > 1 else "campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_final.xodr")
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 0

xodr_text = XODR.read_text(encoding="utf-8", errors="ignore")
m = carla.Map("probe", xodr_text)
print(f"map parsed: {m.name}")
wps = m.generate_waypoints(1.0)
print(f"generate_waypoints(1.0) OK count={len(wps)}")
if LIMIT:
    wps = wps[:LIMIT]
for i, wp in enumerate(wps):
    _ = wp.lane_width
    _ = wp.transform
    if i % 10000 == 0:
        print(f"  waypoint {i}/{len(wps)} road={wp.road_id} lane={wp.lane_id} s={wp.s:.3f}")
print("ALL LANE WIDTH QUERIES OK")