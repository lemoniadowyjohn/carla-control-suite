import xml.etree.ElementTree as ET
import json
from collections import Counter
from ultimate_pipeline.quality.map_realism_p0_oracle import scan_structure_terrain_separation
from ultimate_pipeline.enrichment.structure_classifier import classify_xodr_roads
from ultimate_pipeline.enrichment.elevation_importer import ElevationImporter

xodr = r'campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260916_232831.xodr'
osm = r'campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm'
dem = r'cities/ingolstadt/dem/dem_ing.tif'
classification = classify_xodr_roads(xodr, osm_path=osm)
rc = {rid: rec.get('class') for rid, rec in classification.get('per_road', {}).items()}
print('class counts:', Counter(rc.values()))
sampler = ElevationImporter.make_raster_sampler(dem, xodr, osm_path=osm)
root = ET.fromstring(open(xodr, 'rb').read(200000000))
rep = scan_structure_terrain_separation(root, sampler, rc)
print('classified:', rep.get('classified_structure_roads'), 'violations:', rep.get('violations'))
c = Counter((r['class'], r['violated']) for r in rep['records'])
for k, v in sorted(c.items()):
    print(k, v)
print('worst below:', [(r['road_id'], r['class'], r['worst_dz']) for r in sorted(rep['records'], key=lambda r: r['worst_dz'])[:6]])
print('worst above:', [(r['road_id'], r['class'], r['worst_dz']) for r in sorted(rep['records'], key=lambda r: -r['worst_dz'])[:6]])
json_path = r'stage8_rca_output/p0_before_structure.json'
json.dump(rep, open(json_path, 'w', encoding='utf-8'), indent=1, default=str)
print('written', json_path)
