import xml.etree.ElementTree as ET
import pyproj, math

p = r'campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr'
osm_path = r'campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm'
REB = (832671.676, 5458671.104)
NATIVE = "+proj=tmerc +lat_0=0 +lon_0=0 +k=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
tf_native = pyproj.Transformer.from_crs(NATIVE, 'EPSG:4326', always_xy=True)
tf_wgs = pyproj.Transformer.from_crs('EPSG:4326', NATIVE, always_xy=True)

root = ET.parse(p).getroot()
roads = {r.get('id'): r for r in root.findall('road')}

def endpoint_local(road, at_start):
    geoms = sorted(road.findall('./planView/geometry'), key=lambda g: float(g.get('s')))
    from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s, endpoint as ke
    g = geoms[0] if at_start else geoms[-1]
    pose = pose_at_s(g, 0.0) if at_start else ke(g)
    return float(pose.x), float(pose.y), float(pose.heading)

print('parsing osm...')
osm = ET.parse(osm_path).getroot()
lonlat = {}
ways = []
for node in osm.findall('node'):
    if node.get('lon'): lonlat[node.get('id')] = (float(node.get('lon')), float(node.get('lat')))
for way in osm.findall('way'):
    tag = way.find('tag[@k="highway"]')
    if tag is None: continue
    nds = [n.get('ref') for n in way.findall('nd') if n.get('ref') in lonlat]
    if len(nds) >= 2: ways.append((way.get('id'), nds))
print('ways:', len(ways))
node_to_ways = {}
for wid, nds in ways:
    for n in set(nds):
        node_to_ways.setdefault(n, []).append(wid)
jl = osm.find('tag') # bbox from bounds
b = osm.find('bounds')
if b is not None:
    print('osm bounds lat/lon:', b.attrib)

# endpoints of OSM ways in local coords
def n2local(nid):
    lon, lat = lonlat[nid]
    x, y = tf_wgs.transform(lon, lat)
    return x - REB[0], y - REB[1]
way_local = {}
for wid, nds in ways:
    way_local[wid] = [n2local(n) for n in nds]

END_RADIUS = 2.0
def classify(math_end, heading):
    x0, y0 = math_end[0], math_end[1]
    matched = []
    for wid, pts in way_local.items():
        # bounding quick reject
        for i, px in enumerate(pts):
            dx = px[0] - x0; dy = px[1] - y0
            if dx*dx + dy*dy <= END_RADIUS*END_RADIUS:
                matched.append((wid, i))
    return matched

# test 6 dead-end roads
de = [r for r in roads.values() if (r.find('./link') is not None and r.find('./link').find('predecessor') is not None and (r.find('./link').find('predecessor').get('elementType')=='junction') and (r.find('./link').find('successor') is None))]
import itertools
for r in de[:6]:
    rid = r.get('id')
    x, y, hdg = endpoint_local(r, at_start=False)  # dead end at successor side (no successor) => end
    hits = classify((x, y), hdg)
    near = []
    for wid, i in itertools.chain(hits, ((w, len(pts)-1) for w, pts in [])):
        way_node_ids = next(nds for w, nds in ways if w == wid)
        other_nodes = [n for n in way_node_ids if n != way_node_ids[i]]
        ndeg = []
        for n, w2s in node_to_ways.items():
            pass
        near.append((wid, i, way_node_ids[i]))
    print(rid, 'end@local', round(x,1), round(y,1), 'heading', round(math.degrees(hdg),1), 'osm ways within 2m:', [h[0] for h in hits][:12])
