import sys
sys.path.insert(0, 'tools')
from placement_control_anchor_assay import load_obj_groups
from pathlib import Path

td = Path('reports/production_readiness/20260924T100614Z_FULL_GRID_TILE_FBX_COOK/artifacts/tile_6_6')
g = load_obj_groups(td / 'Ingolstadt_Tile_6_6.obj')
V, G = g['verts'], g['groups']
print('total verts:', len(V))
print('groups:', len(G))
building_groups = [gn for gn in G if gn.startswith('Building')]
print('building groups:', len(building_groups))
print('first 5:', building_groups[:5])

for gn in building_groups[:3]:
    d = G[gn]
    print(f'{gn}: idx len={len(d["idx"])}, faces={len(d["faces"])}')

# Check idx collection
bldg_idx = []
for gn, d in G.items():
    if gn and gn.startswith("Building") and len(d["idx"]):
        pass  # would extend
print("Would collect indices for", sum(1 for gn, d in G.items() if gn and gn.startswith("Building") and len(d["idx"])), "building groups")