import xml.etree.ElementTree as ET
import json
from collections import Counter
from ultimate_pipeline.quality.check_lane_connectivity import find_broken_lanes_detailed

p = r'campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr'
root = ET.parse(p).getroot()
for allow in (False, True):
    rep = find_broken_lanes_detailed(root, allow_dead_ends=allow)
    print('allow_dead_ends=', allow, 'total_broken=', len(rep))
    c = Counter()
    sample = []
    for i in rep:
        if isinstance(i, dict):
            key = i.get('reason') or i.get('type') or json.dumps(i)[:60]
            c[key] += 1
            if len(sample) < 5:
                sample.append(i)
        else:
            c[str(i)[:60]] += 1
    print('by reason:', dict(c))
    for s in sample[:3]:
        print('  sample:', json.dumps(s)[:300])
