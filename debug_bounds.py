import xml.etree.ElementTree as ET
from ultimate_pipeline.tiling.tile_equivalence import road_bounds_curve_aware

xml = '<OpenDRIVE><road id="1" length="10"><planView><geometry s="0" x="0" y="0" hdg="0" length="10"/></planView><lanes><laneSection s="0"><right><lane id="-1" type="driving"><width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane></right></laneSection></lanes></road><road id="2" length="10"><planView><geometry s="0" x="10" y="20" hdg="0" length="10"/></planView><lanes><laneSection s="0"><right><lane id="-1" type="driving"><width sOffset="0" a="3.5" b="0" c="0" d="0"/></lane></right></laneSection></lanes></road></OpenDRIVE>'

root = ET.fromstring(xml)
for road in root.findall('road'):
    rid = road.get('id')
    b = road_bounds_curve_aware(road)
    print(f'Road {rid}: {b}')