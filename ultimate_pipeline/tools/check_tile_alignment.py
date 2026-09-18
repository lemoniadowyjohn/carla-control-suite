import argparse
import json
import math
from pathlib import Path
from statistics import median

def load_meta(path: Path) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(d, dict) and "tiles" in d and isinstance(d["tiles"], dict):
        return d["tiles"]
    if isinstance(d, dict):
        return d
    raise ValueError(f"Unsupported metadata schema in {path}")

def bbox_center(tile_meta: dict):
    bb = tile_meta.get("core_bbox") or tile_meta.get("bbox") or tile_meta.get("bounds") or {}

    # list/tuple: [min_x, min_y, max_x, max_y]
    if isinstance(bb, (list, tuple)) and len(bb) >= 4:
        minx, miny, maxx, maxy = bb[0], bb[1], bb[2], bb[3]
        try:
            return (float(minx) + float(maxx)) / 2.0, (float(miny) + float(maxy)) / 2.0
        except Exception:
            return None

    # dict variants
    if isinstance(bb, dict) and "core" in bb and isinstance(bb.get("core"), dict):
        bb = bb["core"]

    # common schema: min_x,max_x,min_y,max_y
    minx = bb.get("min_x") if isinstance(bb, dict) else None
    maxx = bb.get("max_x") if isinstance(bb, dict) else None
    miny = bb.get("min_y") if isinstance(bb, dict) else None
    maxy = bb.get("max_y") if isinstance(bb, dict) else None

    # alternate schema: min/max arrays
    if None in (minx, maxx, miny, maxy) and isinstance(bb, dict):
        mn, mx = bb.get("min"), bb.get("max")
        if isinstance(mn, (list, tuple)) and isinstance(mx, (list, tuple)) and len(mn) >= 2 and len(mx) >= 2:
            minx, miny = mn[0], mn[1]
            maxx, maxy = mx[0], mx[1]

    if None in (minx, maxx, miny, maxy):
        return None
    return (minx + maxx) / 2.0, (miny + maxy) / 2.0

def percentile(sorted_vals, p: float):
    if not sorted_vals:
        return None
    idx = int(round((len(sorted_vals) - 1) * p))
    return sorted_vals[max(0, min(idx, len(sorted_vals) - 1))]

def main():
    ap = argparse.ArgumentParser(description="Compare tile grid alignment between auto and manual tile_metadata.json")
    ap.add_argument("--auto-meta", required=True)
    ap.add_argument("--manual-meta", required=True)
    args = ap.parse_args()

    auto_path = Path(args.auto_meta)
    manual_path = Path(args.manual_meta)

    if not manual_path.is_file():
        print(f"Manual meta not found: {manual_path}")
        print("Run tile_manual_xodr_windows.py first.")
        return 2
    if not auto_path.is_file():
        print(f"Auto meta not found: {auto_path}")
        print("Pick a valid auto run (tiles + tile_metadata.json).")
        return 2

    auto_meta = load_meta(auto_path)
    man_meta = load_meta(manual_path)

    Ak = set(auto_meta.keys())
    Mk = set(man_meta.keys())
    common = Ak & Mk

    print(f"Auto tiles:   {len(Ak)}")
    print(f"Manual tiles: {len(Mk)}")
    print(f"Common:       {len(common)}")
    print(f"Only auto:    {len(Ak - Mk)}")
    print(f"Only manual:  {len(Mk - Ak)}")

    dists = []
    missing_bbox = 0
    skips_printed = 0
    max_skips = 10
    for k in sorted(common):
        ca = bbox_center(auto_meta[k])
        cm = bbox_center(man_meta[k])
        if ca is None or cm is None:
            missing_bbox += 1
            if skips_printed < max_skips:
                auto_status = "missing" if ca is None else "ok"
                man_status = "missing" if cm is None else "ok"
                print(f"Skip: {k} missing bbox center (auto={auto_status}, manual={man_status})")
                skips_printed += 1
            continue
        dists.append(math.hypot(ca[0] - cm[0], ca[1] - cm[1]))

    if not dists:
        print("No comparable bbox centers found. Schema mismatch or bbox missing.")
        if common:
            any_key = next(iter(common))
            print("Example auto tile keys:", list(auto_meta[any_key].keys()))
            print("Example man tile keys:", list(man_meta[any_key].keys()))
        return 0

    dists.sort()
    print(f"Missing bbox centers in {missing_bbox} common tiles.")
    print("Center delta (m): "
          f"min={dists[0]:.3f} "
          f"median={median(dists):.3f} "
          f"p95={percentile(dists, 0.95):.3f} "
          f"max={dists[-1]:.3f}")

    if missing_bbox > max_skips:
        print(f"...and {missing_bbox - max_skips} more skipped due to missing bbox center.")

    # quick verdict
    if percentile(dists, 0.95) > 0.5:
        print("WARN: Likely grid-origin mismatch (p95 > 0.5m). Check tile origin/indexing.")
    else:
        print("OK: Tile grids look aligned (p95 <= 0.5m).")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
