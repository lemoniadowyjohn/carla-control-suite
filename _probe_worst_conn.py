import xml.etree.ElementTree as ET

p = r'campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr'
root = ET.parse(p).getroot()
roads = {r.get('id'): r for r in root.findall('road')}

def zprof(rid):
    r = roads[rid]
    prof = r.find('elevationProfile')
    geoms = r.findall('./planView/geometry')
    tot = sum(float(g.get('length')) for g in geoms)
    if prof is None:
        return rid, tot, 'NO_PROFILE'
    return rid, tot, [ (e.get('s'), {k: e.get(k) for k in ('a','b','c','d')}) for e in prof.findall('elevation') ]

# find the worst records from the oracle output
import json
o = json.load(open('stage8_rca_output/p0_before_oracle.json', encoding='utf-8'))
bad = o['connector_lane_interface_dz']['bad_examples']
print('interface total:', o['connector_lane_interface_dz']['interface_links'])
print('oracle says:', o['connector_lane_interface_dz']['bad_seams'], 'bad, worst', o['connector_lane_interface_dz']['worst_dz'])
print()
seen = set()
for jd, rec in enumerate(bad):
    inc_rec = None
    # re-find incoming road via connection
    for j in root.findall('junction'):
        if j.get('id') != rec['junction_id']: continue
        for c in j.findall('connection'):
            if c.get('connectingRoad') == rec['connector_road']:
                inr = c.get('incomingRoad')
                print('junction', rec['junction_id'], 'conn', c.get('id'), 'incoming', inr, 'connRoad', rec['connector_road'], 'contact', c.get('contactPoint'), 'laneLink', rec['from'], '->', rec['to'])
                print('  incoming  ', zprof(inr))
                print('  connector ', zprof(rec['connector_road']))
                sr = roads[rec['connector_road']].find('./link/successor')
                print('  connector successor link:', sr.attrib if sr is not None else None)
                break
    if jd > 6: break
