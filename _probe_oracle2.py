import json
o = json.load(open('stage8_rca_output/p0_before_oracle.json', encoding='utf-8'))
c = o['connector_lane_interface_dz']
for k in ('interface_links', 'connections_total', 'connection_interfaces', 'bad_seams', 'bad_connections', 'worst_dz', 'conn_class_counts'):
    print(k, ':', c.get(k))
print('worst_record:', c.get('worst_record'))
g = o['georeference']
print('georef:', {k: g.get(k) for k in ('has_geo_reference','has_absolute_origin','lat_0','lon_0','has_offset','offset','duplicate_offset_in_georef')})
d = o['dangling_mandatory_lane_successors']
print('dangling:', d['dangling_mandatory_lane_successors'], d['dangling_by_class'])
print('dangling records:', d['dangling_records'][:5])
s = o.get('structure_terrain_separation')
if isinstance(s, dict):
    print('structure keys:', list(s.keys())[:10])
    print({k: s.get(k) for k in ('INCOMPLETE','classified_structure_roads','violations','ok') if k in s})
    vrs = s.get('records') or []
    vv = [r for r in vrs if r.get('violated')][:10]
    print('violated sample:', [(r['road_id'], r['class'], r['worst_dz']) for r in vv])
else:
    print('structure INCOMPLETE:', s)
