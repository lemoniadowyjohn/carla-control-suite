import xml.etree.ElementTree as ET
import math, pyproj

p = r'campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr'
root = ET.parse(p).getroot()
roads = {r.get('id'): r for r in root.findall('road')}

from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s, endpoint as ke

def dump(rid):
    r = roads[rid]
    lnk = r.find('./link')
    pred = lnk.find('predecessor') if lnk is not None else None
    succ = lnk.find('successor') if lnk is not None else None
    geoms = sorted(r.findall('./planView/geometry'), key=lambda g: float(g.get('s')))
    tot = sum(float(g.get('length')) for g in geoms)
    start = pose_at_s(geoms[0], 0.0)
    end = ke(geoms[-1])
    print(rid, 'pred:', pred.attrib if pred is not None else None, 'succ:', succ.attrib if succ is not None else None)
    print('  len', round(tot,1), 'start', (round(start.x,1), round(start.y,1), round(math.degrees(start.heading),1)),
          'end', (round(end.x,1), round(end.y,1), round(math.degrees(end.heading),1)))

dump('46643')
dump('42335')

# OSM way 101731858 nodes in local coords
REB = (832671.676, 5458671.104)
nat = "+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
t = pyproj.Transformer.from_crs('EPSG:4326', nat, always_xy=True)
osm = ET.parse(r'campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm').getroot()
lonlat = {}
for n in osm.findall('node'):
    if n.get('lon'):
        lonlat[n.get('id')] = (float(n.get('lon')), float(n.get('lat')))
for wid in ('101731858',):
    way = next(w for w in osm.findall('way') if w.get('id')==wid)
    refs = [nd.get('ref') for nd in way.findall('nd')]
    print(wid, 'refs:', refs, 'tags:', [(tg.get('k'),tg.get('v')) for tg in way.findall('tag')])
    pts = [t.transform(*lonlat[r]) for r in refs if r in lonlat]
    loc = [(x-REB[0], y-REB[1]) for x,y in pts]
    for i, (x,y) in enumerate(loc):
        b = ''
        if i+1 < len(loc):
            dx, dy = loc[i+1][0]-x, loc[i+1][1]-y
            b = '->' + str(round(math.degrees(math.atan2(dy,dx))%360,1))
        print('  node', refs[i], (round(x,1), round(y,1)), b)
