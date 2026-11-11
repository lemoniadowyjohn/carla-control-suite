"""Debug the validator."""
import tempfile
from pathlib import Path
from ultimate_pipeline.quality.junction_lane_continuity import JunctionLaneContinuityValidator

content = '''<?xml version="1.0"?>
<OpenDRIVE xmlns="http://sumo.dlr.de/generated" version="1.4">
  <road id="road1" length="100.0" angle="0.0" type="traffic_way">
    <planView>
      <geometry length="100.0">
        <line />
      </geometry>
    </planView>
    <lanes>
      <lane id="1" type="driving" width="3.5">
        <offset>0.0</offset>
        <direction>forward</direction>
      </lane>
    </lanes>
  </road>
</OpenDRIVE>'''

with tempfile.NamedTemporaryFile(suffix=".xodr", mode="w", delete=False) as f:
    f.write(content)
    tmppath = f.name

v = JunctionLaneContinuityValidator(input_path=str(Path(tmppath)))
print("Roads:", v.roads)
print("Lanes:", v.lanes)
center = v._lane_center("road1", 1, s=0.0)
print("Center status:", center.status)
print("Center:", center)
