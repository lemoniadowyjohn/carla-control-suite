import xml.etree.ElementTree as ET
from collections import Counter

p = r'campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr'
root = ET.parse(p).getroot()
roads = {r.get('id'): r for r in root.findall('road')}

# what the audit counted: roads referenced by junction connections
junction_roads = set()
for j in root.findall('junction'):
    for c in j.findall('connection'):
        for a in ('incomingRoad', 'connectingRoad'):
            if c.get(a):
                junction_roads.add(c.get(a))
print('roads total:', len(roads), 'junction-referenced:', len(junction_roads))

candidates = []
for rid, rd in roads.items():
    links = rd.find('./link')
    pred = links.find('predecessor') if links is not None else None
    succ = links.find('successor') if links is not None else None
    driving = 0
    for sec in rd.findall('./lanes/laneSection'):
        for side in ('left', 'right'):
            e = sec.find(side)
            if e is None:
                continue
            driving += sum(1 for l in e.findall('lane') if (l.get('type') or 'driving').lower() == 'driving')
    if driving == 0:
        continue
    has_link = pred is not None or succ is not None
    in_junction = rid in junction_roads
    if not has_link and not in_junction:
        candidates.append(rid, ) if False else candidates.append((rid, driving, len(rd.findall('laneSet'))))
print('orphan candidate (no link, no junction membership):', len(candidates))
n_ids = {'42367','43405','46369','46698','48129','51657'}
print('audit ids present among candidates:', [c for c in candidates if c[0] in n_ids])
# where are the audit's 6? check their links/junction refs
for rid in sorted(n_ids):
    rd = roads.get(rid)
    if rd is None:
        print(rid, 'ABSENT FROM MAP'); continue
    links = rd.find('./link')
    print(rid, 'pred:', links.find('predecessor').attrib if links is not None and links.find('predecessor') is not None else None,
          'succ:', links.find('successor').attrib if links is not None and links.find('successor') is not None else None,
          'in_junction:', rid in junction_roads)
