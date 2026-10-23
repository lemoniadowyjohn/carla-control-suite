"""Source-stage audit of OSM building rings: is any repair actually needed?

The governed repair policy is PASS / REPAIRED / REJECTED with provenance
(OSM source id, tile id, repair status, validation metrics). Before adding repair
logic it is worth knowing whether the pinned source actually contains rings that
need repairing -- adding a repairer that silently rewrites good geometry would be
worse than having none.

This script measures, per element, the defects that would produce degenerate
triangles after extrusion and triangulation:

  * fewer than 3 distinct vertices (cannot form a polygon)
  * consecutive duplicate points (zero-length edges)
  * non-consecutive duplicate points (self-touching rings)
  * unclosed ring where closure is required
  * collinear-only rings (zero enclosed area)

It writes reports/geometry/OSM_BUILDING_REPAIR_REPORT.json.

It does NOT modify the source, the tile assignment, the OpenDRIVE topology, or
any governed artifact.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from ultimate_pipeline.tiling.tile_fbx_generator import (  # noqa: E402
    TileGridSpec,
    assign_buildings_to_tiles,
    load_buildings_from_overpass_json,
)

HEADER_OFFSET = (832671.676, 5458671.104)
COLLINEAR_EPS = 1e-12


def _distinct(points):
    return len({(round(x, 12), round(y, 12)) for x, y in points})


def _signed_area(points):
    a = 0.0
    for i in range(len(points) - 1):
        x0, y0 = points[i]
        x1, y1 = points[i + 1]
        a += x0 * y1 - x1 * y0
    return 0.5 * a


def _is_collinear(points) -> bool:
    if len(points) < 3:
        return True
    x0, y0 = points[0]
    x1, y1 = points[1]
    ux, uy = x1 - x0, y1 - y0
    for x, y in points[2:]:
        if abs(ux * (y - y0) - uy * (x - x0)) > COLLINEAR_EPS:
            return False
    return True


def audit(path: Path) -> dict:
    buildings = load_buildings_from_overpass_json(str(path))
    grid = TileGridSpec(tile_size_m=1000.0, header_offset_xy=HEADER_OFFSET)
    assignment = assign_buildings_to_tiles(buildings, grid)

    issues: Counter = Counter()
    per_element = []
    tile_counts: Counter = Counter()

    for b in buildings:
        defects = []
        for pi, part in enumerate(b.parts):
            outer = list(part.outer)
            if not outer:
                defects.append("empty_outer_ring")
                continue
            closed = len(outer) > 1 and outer[0] == outer[-1]
            body = outer[:-1] if closed else outer
            if not closed:
                defects.append("unclosed_outer_ring")
            if _distinct(body) < 3:
                defects.append("fewer_than_3_distinct_vertices")
            # consecutive duplicates on the closed ring
            seq = body + body[:1]
            for i in range(len(seq) - 1):
                if seq[i] == seq[i + 1]:
                    defects.append("consecutive_duplicate_points")
                    break
            # non-consecutive duplicates (self-touching)
            seen = set()
            dup_nonconsec = False
            for pt in body:
                k = (round(pt[0], 12), round(pt[1], 12))
                if k in seen:
                    dup_nonconsec = True
                    break
                seen.add(k)
            if dup_nonconsec:
                defects.append("self_touching_ring")
            if abs(_signed_area(seq)) <= COLLINEAR_EPS or _is_collinear(body):
                defects.append("zero_enclosed_area")
            for inner in part.inners:
                ib = list(inner)
                if len(ib) > 1 and ib[0] == ib[-1]:
                    ib = ib[:-1]
                if _distinct(ib) < 3:
                    defects.append("courtyard_fewer_than_3_distinct_vertices")
                if abs(_signed_area(list(inner))) <= COLLINEAR_EPS:
                    defects.append("courtyard_zero_area")

        for d in set(defects):
            issues[d] += 1
        if defects:
            per_element.append({
                "source_id": b.source_id,
                "source_type": b.source_type,
                "parts": len(b.parts),
                "defects": sorted(set(defects)),
                "status": "REJECTED",
            })

    for (tx, ty), cell in assignment.tiles.items():
        tile_counts[f"{tx}_{ty}"] = len(cell)

    clean = len(buildings) - len(per_element)
    return {
        "schema": "osm_building_repair_report/v1",
        "source": str(path),
        "policy": {
            "statuses": ["PASS", "REPAIRED", "REJECTED"],
            "repair_is_not_performed_by_this_script": True,
            "rationale": "This script only measures. Whether to repair is a separate, "
                         "explicitly authorized decision: the governed rule is that "
                         "geometry is fixed at the generator stage and never silently "
                         "rewritten in a final artifact.",
            "note": "No source file, tile membership, OpenDRIVE topology or governed "
                    "artifact is modified by this audit.",
        },
        "totals": {
            "elements_loaded": len(buildings),
            "elements_clean": clean,
            "elements_with_defects": len(per_element),
            "placed": assignment.total_placed(),
            "unplaceable": len(assignment.unplaceable),
            "defect_histogram": dict(issues),
        },
        "tile_membership_counts": dict(sorted(tile_counts.items())),
        "defective_elements": per_element[:200],
        "defective_elements_truncated": len(per_element) > 200,
        "conclusion": (
            "No source-stage repair is required: every pinned building ring is "
            "geometrically valid." if not per_element else
            f"{len(per_element)} elements carry ring defects and require an explicit "
            "repair decision before extrusion."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source",
                    default="campaigns/ingolstadt_cooked_perception_v1/source/"
                            "ingolstadt_buildings_overpass.json")
    ap.add_argument("--out", default="reports/geometry/OSM_BUILDING_REPAIR_REPORT.json")
    args = ap.parse_args()

    report = audit(Path(args.source))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report["totals"], indent=2))
    print(report["conclusion"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())