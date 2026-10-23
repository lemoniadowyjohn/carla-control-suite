import json, xml.etree.ElementTree as ET, math

rep = json.load(open('stage8_rca_output/p0_before_terminal_ledger.json', encoding='utf-8'))
recs = [r for r in rep['records'] if r['classification'] == 'UNMAPPED']
print('UNMAPPED count:', len(recs))
print([r['road_id'] for r in recs[:10]])

root = ET.parse(r'campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr').getroot()
roads = {r.get('id'): r for r in root.findall('road')}

# for each UNMAPPED: compute end pose, then the nearest OSM node distance
import pyproj
REB = (832671.676, 5458671.104)
nat = "+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
t = pyproj.Transformer.from_crs(nat, 'EPSG:4326', always_xy=True)
osm = ET.parse(r'campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm').getroot()
lonlat = {}
for n in osm.findall('node'):
    if n.get('lon'):
        lonlat[n.get('id')] = (float(n.get('lon')), float(n.get('lat')))
# project once to local
ids = list(lonlat)
lons = [lonlat[i][0] for i in ids]; lats = [lonlat[i][1] for i in ids]
xs, ys = t.transform(lons, lats)
local = {ids[i]: (xs[i] - REB[0], ys[i] - REB[1]) for i in range(len(ids))}

def endpose(road):
    geoms = sorted(road.findall('./planView/geometry'), key=lambda g: float(g.get('s')))
    from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s, endpoint as ke
    g = geoms[-1]
    pose = ke(g)
    return float(pose.x), float(pose.y), float(pose.heading)

for r in recs[:6]:
    road = roads[r['road_id']]
    if road is None:
        print(r['road_id'], 'absent'); continue
    x, y, hdg = endpose(road)
    # nearest node
    import heapq
    best = min(((math.hypot(px-x, py-y), nid) for nid, (px, py) in local.items()))  # expensive but fine
    print(r['road_id'], f'end=({x:.1f},{y:.1f})', 'nearest node', best[1], f'd={best[0]:.2f}m')
