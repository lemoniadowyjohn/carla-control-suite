import xml.etree.ElementTree as ET
from collections import Counter

p = r'campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr'
root = ET.parse(p).getroot()
roads = {r.get('id'): r for r in root.findall('road')}

junction_ids = {j.get('id') for j in root.findall('junction')}
# each junction's referenced roads
conn_in = {rid: set() for rid in roads}
conn_out = {rid: set() for rid in roads}
for j in root.findall('junction'):
    for c in j.findall('connection'):
        i, o = c.get('incomingRoad'), c.get('connectingRoad')
        if i in conn_in: conn_in[i].add(j.get('id'))
        if o in conn_in: conn_in[o].add(j.get('id'))

no_damage = []
stats = Counter()
records = []
for rid, rd in roads.items():
    driving = 0
    for sec in rd.findall('./lanes/laneSection'):
        for side in ('left', 'right'):
            e = sec.find(side)
            if e is None: continue
            driving += sum(1 for l in e.findall('lane') if (l.get('type') or 'driving').lower() == 'driving')
    links = rd.find('./link')
    pred = links.find('predecessor') if links is not None else None
    succ = links.find('successor') if links is not None else None
    in_junc = bool(conn_in.get(rid))
    if in_junc:
        continue
    et_p = (pred.get('elementType') or '?') if pred is not None else None
    et_s = (succ.get('elementType') or '?') if succ is not None else None
    stats[(et_p, et_s, 'driving' if driving else 'other')] += 1
    if driving:
        records.append((rid, et_p, et_s, len(rd.findall('laneSet'))))
print('roads with junction membership:', sum(1 for v in conn_in.values() if v))
for k, v in stats.most_common(8): print(k, v)
print('no-membership roads total:', sum(stats.values()))
print('no-membership driving:', len(records))
print('sample:', records[:12])
