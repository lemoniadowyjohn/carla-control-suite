import sys
sys.path.insert(0, 'tools')
from placement_control_anchor_assay import load_tile_osm, load_full_osm_buildings
from pathlib import Path
import math

full = load_full_osm_buildings(Path('campaigns/ingolstadt_cooked_perception_v1/source/ingolstadt_authoritative.osm'))
tw = load_tile_osm(Path('reports/production_readiness/20260924T100614Z_FULL_GRID_TILE_FBX_COOK/artifacts/tile_6_6/Ingolstadt_Tile_6_6.osm'))

print('Full buildings:', len(full))
print('Tile ways:', len(tw))

# Check native centroids
for tw in tw[:5]:
    best_d = 1e9
    for fw in full[:100]:
        dx = tw['centroid_native'][0] - fw['centroid_native'][0]
        dy = tw['centroid_native'][1] - fw['centroid_native'][1]
        d = math.hypot(dx, dy)
        if d < best_d:
            best_d = d
    print(f'Tile way centroid_native: {tw["centroid_native"]} -> best dist: {best_d:.1f}m')

# Also check full OSM building centroids
print('--- Full OSM sample ---')
for fw in full[:5]:
    print(f'Full building centroid_native: {fw["centroid_native"]}')