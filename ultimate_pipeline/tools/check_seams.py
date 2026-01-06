import os, json, glob, sys

out_dir = sys.argv[1]
seams_dir = os.path.join(out_dir, "seams")
manifest = os.path.join(seams_dir, "seams_manifest.json")
adj_path = os.path.join(out_dir, "tile_adjacency.json")

print("out_dir:", out_dir)
assert os.path.isdir(out_dir), "out_dir not found"
assert os.path.exists(adj_path), "tile_adjacency.json missing"
assert os.path.exists(manifest), "seams_manifest.json missing"

adj = json.load(open(adj_path, "r", encoding="utf-8"))
items = json.load(open(manifest, "r", encoding="utf-8")).get("items", [])

# Count directed edges from adjacency structure
# (supports a few common shapes)
edges = []
if isinstance(adj, dict) and "edges" in adj:
    for e in adj["edges"]:
        a = e.get("a") or e.get("from") or e.get("u")
        b = e.get("b") or e.get("to") or e.get("v")
        if a and b:
            edges.append((a, b))
elif isinstance(adj, dict):
    # adjacency list: {tile: [neighbors...]}
    for a, nbrs in adj.items():
        if isinstance(nbrs, list):
            for b in nbrs:
                edges.append((a, b))

lane_items = [it for it in items if it.get("kind") == "lane_seam"]

print("Adjacency directed edges (approx):", len(edges))
print("Manifest lane_seam items:", len(lane_items))

reports = glob.glob(os.path.join(seams_dir, "lane_seam", "*.json"))
print("lane_seam report files:", len(reports))

# Basic coverage expectation:
if len(lane_items) == 0 or len(reports) == 0:
    raise SystemExit("No seam artifacts found → not operational.")

print("OK: seam artifacts exist.")
