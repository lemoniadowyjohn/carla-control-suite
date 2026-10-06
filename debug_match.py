import sys
sys.path.insert(0, 'tools')
from placement_control_anchor_assay import load_tile_osm, load_full_osm_buildings
from pathlib import Path
import math

full = load_full_osm_buildings(Path('campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm'))
tw = load_tile_osm(Path('reports/production_readiness/20260924T100614Z_FULL_GRID_TILE_FBX_COOK/artifacts/tile_6_6/Ingolstadt_Tile_6_6.osm'))

print('Full buildings:', len(full))
print('Tile ways:', len(tw))

matched = 0
for tw_item in tw[:20]:
    best_d = 1e9
    best_fw = None
    for fw in full:
        dx = tw_item['centroid_native'][0] - fw['centroid_native'][0]
        dy = tw_item['centroid_native'][1] - fw['centroid_native'][1]
        d = math.hypot(dx, dy)
        if d < 2000:
            matched += 1
            print(f'MATCH: tw centroid={tw_item["centroid_native"]} -> fw centroid={fw["centroid_native"]} d={math.hypot(dx, dy):.1f}m')
            break

print(f'Total matched: {matched}')