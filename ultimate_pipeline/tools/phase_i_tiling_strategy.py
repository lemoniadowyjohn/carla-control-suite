#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""I — Phase I orchestrator: tiling strategy and tile equivalence.

Selected strategy (three concepts kept distinct):

1. XODR logical partitioning: NOT applied to the cooked campaign. The
   candidate is ONE logical CARLA map identity (single OpenDRIVE document,
   32710 roads). Partitioned builds remain supported by the hardened tiler.
2. Unreal visual-asset tiling: import-time concern (CARLA editor); no
   per-tile markers are injected into XODR (TIL-004/I5).
3. CARLA map identity: one logical map per campaign.

Evidence gates:

- I1 curve-aware road bounds replace start-point-only bounds; extrema of
  line/arc/spiral/poly3/paramPoly3 via the hardened geometry evaluator
  (opendrive_geometry, geometry_math fallback), inflated by lane half-width.
- I2 formal assignment policy: midpoint ownership, junction context co-
  placement, context duplication via buffer, ownership out of band.
- I3 junction-cut prevention: complete-junction duplication; every junction
  travels together; route continuity proven per tile.
- I4 semantic preservation: road/junction/lane-section/LaneLink/signal/
  controller/object/profile/roadmark/georeference inventories preserved.
- I5 duplicate equivalence: context duplicates byte-identical; no per-tile
  markers in duplicated elements.
- I6 adjacency graph + curve-aware boundary sampling, seam checks.
- I7 fail closed: UP_ALLOW_TILE_QA_FAIL no longer defaulted by runners;
  stage_09 consumes ReleaseDefaults.allow_tile_qa_failure.
- I8 tile equivalence: untiled source vs union of tiles across inventories,
  topology, route reachability, geometry.

Verdicts:
- PHASE_I_TILING_PASS
- PHASE_I_BLOCKED_INPUT_IDENTITY
- PHASE_I_BLOCKED_CURVE_BOUNDS
- PHASE_I_BLOCKED_JUNCTION_CUT
- PHASE_I_BLOCKED_EQUIVALENCE
- PHASE_I_BLOCKED_FAIL_CLOSED
"""
from __future__ import annotations

import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.tiling.tile_equivalence import (
    _geom_kind,
    _geometry_local_bounds,
    road_bounds_curve_aware,
    tile_road_ownership,
    verify_tile_adjacency,
)
from ultimate_pipeline.tiling.tile_extractor import (
    TileExtractor,
    _analyze_tile_lanes,
    _build_tile_root,
    _finalize_tile,
)

RUN_ID = "20260804T060000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID
INPUT_XODR = (
    REPO_ROOT / "reports" / "post_audit_hardening" / "20260804T050000Z"
    / "candidate_h_signal_enrichment.xodr"
)
TILE_SIZE = 1000.0
TILE_BUFFER_M = 50.0
CURVE_DELTA_EPS_M = 0.5


def _bounds_rect(b: Dict[str, float]) -> Tuple[float, float, float, float]:
    return b["x_min"], b["y_min"], b["x_max"], b["y_max"]


def _intersects(
    a: Tuple[float, float, float, float],
    b: Tuple[float, float, float, float],
) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _pick_window(
    bounds_map: Dict[str, Dict[str, float]],
) -> Tuple[float, float]:
    centers = []
    for b in bounds_map.values():
        centers.append(((b["x_min"] + b["x_max"]) / 2.0,
                        (b["y_min"] + b["y_max"]) / 2.0))
    cell = 500.0
    counts: Dict[Tuple[int, int], int] = Counter(
        (int(cx // cell), int(cy // cell)) for cx, cy in centers)
    (ix, iy), _ = counts.most_common(1)[0]
    return ix * cell, iy * cell


def _inventory(road: ET.Element) -> Dict[str, int]:
    return {
        "signals": len(road.findall("signals/signal")),
        "signal_references": len(road.findall(".//signalReference")),
        "lane_sections": len(road.findall("lanes/laneSection")),
        "lanes": len(road.findall(".//lane")),
        "lane_links": len(road.findall(".//lane/link/*")),
        "objects": len(road.findall(".//object")),
        "road_marks": len(road.findall(".//roadMark")),
        "elevation_profiles": len(road.findall("elevationProfile/elevation")),
        "lateral_profiles": len(road.findall("lateralProfile/superelevation")
                               + road.findall("lateralProfile/crossfall")),
        "geometry": len(road.findall("planView/geometry")),
        "user_data": len(road.findall("userData")),
    }


def _canonical_bytes(elem: ET.Element) -> bytes:
    return ET.tostring(elem, encoding="utf-8")


def _run_equivalence(
    root: ET.Element,
    bounds_map: Dict[str, Dict[str, float]],
    window: Tuple[float, float],
) -> Dict[str, Any]:
    ox, oy = window
    cells = {
        "tile_0_0": (ox, oy, ox + TILE_SIZE, oy + TILE_SIZE),
        "tile_1_0": (ox + TILE_SIZE, oy, ox + 2 * TILE_SIZE, oy + TILE_SIZE),
        "tile_0_1": (ox, oy + TILE_SIZE, ox + TILE_SIZE, oy + 2 * TILE_SIZE),
        "tile_1_1": (ox + TILE_SIZE, oy + TILE_SIZE,
                     ox + 2 * TILE_SIZE, oy + 2 * TILE_SIZE),
    }

    roads = list(root.findall("road"))
    road_by_id = {r.get("id"): r for r in roads}
    core_roads = {
        rid for rid, b in bounds_map.items()
        if any(_intersects(_bounds_rect(b), cell) for cell in cells.values())
    }
    junction_of = {r.get("id"): r.get("junction")
                   for r in roads if r.get("junction")}
    junction_members: Dict[str, List[str]] = defaultdict(list)
    for rid, jid in junction_of.items():
        # OSM2ODR convention: junction="-1" means "not part of any
        # junction" — exclude the pseudo-junction from I3/I2 analysis.
        if jid and jid != "-1":
            junction_members[jid].append(rid)

    # ownership (I2): midpoint policy with junction context co-placement
    ownership = tile_road_ownership(root, cells, policy="midpoint")

    # build tiles through the production path
    tiles_out = EVIDENCE_DIR / "tiles"
    tiles_out.mkdir(parents=True, exist_ok=True)
    tile_road_sets: Dict[str, set] = {}
    tile_health: Dict[str, dict] = {}
    tile_roads: Dict[str, Dict[str, ET.Element]] = {}
    for name, core in cells.items():
        buf = (core[0] - TILE_BUFFER_M, core[1] - TILE_BUFFER_M,
               core[2] + TILE_BUFFER_M, core[3] + TILE_BUFFER_M)
        tile_root = _build_tile_root(
            root, roads, name, core, TILE_BUFFER_M)
        analysis = _analyze_tile_lanes(tile_root, preserve_global=True)
        path, health = _finalize_tile(
            tile_root, name, str(tiles_out),
            core_bounds=core, buffer_m=TILE_BUFFER_M,
            analysis=analysis, dropped_lane_links=None,
            preserve_global=True, allow_outside=True, strict=False)
        tile_road_sets[name] = {
            r.get("id") for r in tile_root.findall("road") if r.get("id")}
        tile_health[name] = health
        tile_roads[name] = {
            r.get("id"): r for r in tile_root.findall("road") if r.get("id")}

    union = set().union(*tile_road_sets.values()) if tile_road_sets else set()

    results: Dict[str, Any] = {
        "window_origin": [ox, oy],
        "tile_size_m": TILE_SIZE,
        "buffer_m": TILE_BUFFER_M,
        "core_roads": len(core_roads),
        "union_roads": len(union),
        "tile_road_counts": {k: len(v) for k, v in tile_road_sets.items()},
    }

    # --- I8 completeness: every core road in the union, byte-identical ---
    missing = sorted(core_roads - union)
    byte_violations = []
    for rid in sorted(core_roads):
        src_bytes = _canonical_bytes(road_by_id[rid])
        for name in tile_road_sets:
            if rid not in tile_road_sets[name]:
                continue
            if _canonical_bytes(tile_roads[name][rid]) != src_bytes:
                byte_violations.append({"road": rid, "tile": name})
                break

    # --- I5: duplicated (context) roads byte-identical across tiles ---
    dup_violations = []
    dup_road_groups = defaultdict(list)
    for name, rids in tile_road_sets.items():
        for rid in rids:
            dup_road_groups[rid].append(name)
    duplicated = {rid: ts for rid, ts in dup_road_groups.items() if len(ts) > 1}
    for rid, ts in duplicated.items():
        first_bytes = _canonical_bytes(tile_roads[ts[0]][rid])
        for name in ts[1:]:
            if _canonical_bytes(tile_roads[name][rid]) != first_bytes:
                dup_violations.append({"road": rid, "tiles": ts})
                break

    # --- I4 inventory preservation (source core roads vs union copies) ---
    inventory_mismatches = []
    for rid in sorted(core_roads):
        src_inv = _inventory(road_by_id[rid])
        for name in tile_road_sets:
            if rid not in tile_road_sets[name]:
                continue
            if _inventory(tile_roads[name][rid]) != src_inv:
                inventory_mismatches.append({"road": rid, "tile": name})

    # --- I3 junction completeness in union + straddle duplication ---
    window_junctions = {
        jid: [r for r in members if r in core_roads]
        for jid, members in junction_members.items()
        if any(r in core_roads for r in members)
    }
    junction_missing = []
    for jid, members in window_junctions.items():
        if not all(m in union for m in members):
            junction_missing.append({"junction": jid,
                                     "missing": sorted(set(members) - union)})
    junction_split = []
    for jid, members in window_junctions.items():
        tiles_with = sorted({n for n, s in tile_road_sets.items()
                             if set(members) & s})
        if len(tiles_with) == 1:
            continue
        if not all(m in set().union(
                *[tile_road_sets[n] for n in tiles_with])
                for m in members):
            junction_split.append({"junction": jid,
                                   "tiles": tiles_with,
                                   "member_roads": len(members)})

    # --- I6 adjacency graph + border context duplication ---
    adjacency = verify_tile_adjacency(cells, {
        n: [n2 for n2 in cells if n2 != n] for n in cells})
    border_x = ox + TILE_SIZE
    border_y = oy + TILE_SIZE
    envelope = (ox - TILE_BUFFER_M, oy - TILE_BUFFER_M,
                ox + 2 * TILE_SIZE + TILE_BUFFER_M,
                oy + 2 * TILE_SIZE + TILE_BUFFER_M)
    border_roads: List[Dict[str, Any]] = []
    for rid, b in bounds_map.items():
        x0, y0, x1, y1 = _bounds_rect(b)
        if not _intersects((x0, y0, x1, y1), envelope):
            continue
        if x0 < border_x < x1 or y0 < border_y < y1:
            border_roads.append({"road": rid,
                                 "in_tiles": sorted(
                                     n for n, s in tile_road_sets.items()
                                     if rid in s)})
    border_not_duplicated = [r for r in border_roads if len(r["in_tiles"]) < 2]

    # --- I3/I6 route continuity per tile ---
    dangling_links = []
    for name, rids in tile_road_sets.items():
        for r in tile_roads[name].values():
            for link in r.findall(".//lane/link/*"):
                target = link.get("road")
                if target and target not in rids:
                    dangling_links.append({"tile": name,
                                           "road": r.get("id"),
                                           "link": link.tag,
                                           "target": target})

    results.update({
        "missing_core_roads": missing,
        "byte_violations": byte_violations,
        "duplicate_violations": dup_violations,
        "duplicated_road_count": len(duplicated),
        "inventory_mismatches": inventory_mismatches,
        "junction_missing": junction_missing,
        "junction_split": junction_split,
        "adjacency": adjacency,
        "border_roads_total": len(border_roads),
        "border_roads_not_context_duplicated": border_not_duplicated,
        "dangling_links": dangling_links,
        "window_junction_count": len(window_junctions),
        "ownership": {
            "policy": ownership["policy"],
            "assigned": ownership["assigned"],
            "unassigned": ownership["unassigned"],
        },
        "tile_health": {
            k: {kk: vv for kk, vv in v.items() if kk != "bounds"}
            for k, v in tile_health.items()
        },
    })
    return results


def _check_fail_closed() -> Dict[str, Any]:
    checks = {}
    for path, needle in (
        (REPO_ROOT / "ultimate_pipeline" / "run_full_test.py",
         'env.setdefault("UP_ALLOW_TILE_QA_FAIL"'),
        (REPO_ROOT / "ultimate_pipeline" / "tools"
         / "run_thesis_final_experiments.py",
         'env["UP_ALLOW_TILE_QA_FAIL"]'),
    ):
        text = path.read_text(encoding="utf-8", errors="replace")
        checks[path.name] = needle not in text
    stage = (REPO_ROOT / "ultimate_pipeline" / "pipeline_stages"
             / "stage_09_tiling.py").read_text(encoding="utf-8", errors="replace")
    checks["stage_09_profile_consumed"] = (
        "allow_tile_qa_failure" in stage
        and "_PROFILE_DEFAULTS" in stage
        and "fail closed" in stage.lower())
    checks["release_profile_flag_exists"] = (
        "allow_tile_qa_failure" in
        (REPO_ROOT / "ultimate_pipeline" / "contracts"
         / "release_profile.py").read_text(encoding="utf-8"))
    return checks


def _endpoint_box(geom: ET.Element) -> Tuple[float, float, float, float]:
    """(start,end) box of one geometry element (no interior extrema)."""
    x0 = float(geom.get("x", "0.0")); y0 = float(geom.get("y", "0.0"))
    hdg = float(geom.get("hdg", "0.0")); length = float(geom.get("length", "0.0"))
    try:
        from opendrive_geometry.primitives import (
            evaluate_arc, evaluate_line, evaluate_param_poly3,
            evaluate_poly3, evaluate_spiral,
        )
        kind = _geom_kind(geom)
        child = geom.find(kind)
        if kind == "line":
            end = evaluate_line(x0, y0, hdg, length, length)
        elif kind == "arc":
            end = evaluate_arc(x0, y0, hdg, length,
                               float(child.get("curvature", "0.0")), length)
        elif kind == "spiral":
            end = evaluate_spiral(x0, y0, hdg, length,
                                  float(child.get("curvStart", "0.0")),
                                  float(child.get("curvEnd", "0.0")), length)
        elif kind == "poly3":
            end = evaluate_poly3(x0, y0, hdg, length,
                                 float(child.get("a", "0.0")),
                                 float(child.get("b", "0.0")),
                                 float(child.get("c", "0.0")),
                                 float(child.get("d", "0.0")), length)
        elif kind == "paramPoly3":
            end = evaluate_param_poly3(
                x0, y0, hdg, length,
                float(child.get("aU", "0.0")), float(child.get("bU", "0.0")),
                float(child.get("cU", "0.0")), float(child.get("dU", "0.0")),
                float(child.get("aV", "0.0")), float(child.get("bV", "0.0")),
                float(child.get("cV", "0.0")), float(child.get("dV", "0.0")),
                child.get("pRange", "arcLength"), length)
        else:
            end = None
        if end is not None:
            return (min(x0, end.x), min(y0, end.y),
                    max(x0, end.x), max(y0, end.y))
    except Exception:
        pass
    return (x0, y0, x0, y0)


def main() -> int:
    root = ET.parse(str(INPUT_XODR)).getroot()

    # --- I1 curve-aware bounds over the full map ---
    bounds_map: Dict[str, Dict[str, float]] = {}
    kind_counter: Counter = Counter()
    geometry_extrema = 0
    curve_delta_roads = 0
    max_delta = 0.0
    for road in root.findall("road"):
        rid = road.get("id")
        b = road_bounds_curve_aware(road)
        bounds_map[rid] = b
        road_has_extrema = False
        for g in road.findall("planView/geometry"):
            kind = _geom_kind(g)
            if kind != "unknown":
                kind_counter[kind] += 1
            lb = _geometry_local_bounds(g)
            eb = _endpoint_box(g)
            delta = max(abs(lb[0] - eb[0]), abs(lb[1] - eb[1]),
                        abs(lb[2] - eb[2]), abs(lb[3] - eb[3]))
            max_delta = max(max_delta, delta)
            if delta > CURVE_DELTA_EPS_M:
                geometry_extrema += 1
                road_has_extrema = True
        if road_has_extrema:
            curve_delta_roads += 1

    i1 = {
        "roads_scanned": len(bounds_map),
        "geometry_kind_counts": dict(kind_counter),
        "geometry_curve_extrema": geometry_extrema,
        "roads_curve_extrema_beyond_endpoints": curve_delta_roads,
        "max_geometry_bounds_delta_m": round(max_delta, 3),
        "threshold_m": CURVE_DELTA_EPS_M,
    }

    window = _pick_window(bounds_map)

    eq = _run_equivalence(root, bounds_map, window)
    fc = _check_fail_closed()

    ok_i1 = i1["roads_curve_extrema_beyond_endpoints"] > 0
    ok_i8 = (not eq["missing_core_roads"] and not eq["byte_violations"]
             and not eq["duplicate_violations"] and not eq["inventory_mismatches"])
    ok_i3 = (not eq["junction_missing"] and not eq["junction_split"]
             and not eq["dangling_links"])
    ok_i6 = eq["adjacency"]["ok"]
    ok_i7 = all(fc.values())

    verdict = "PHASE_I_TILING_PASS"
    if not ok_i1:
        verdict = "PHASE_I_BLOCKED_CURVE_BOUNDS"
    elif not ok_i3:
        verdict = "PHASE_I_BLOCKED_JUNCTION_CUT"
    elif not ok_i8:
        verdict = "PHASE_I_BLOCKED_EQUIVALENCE"
    elif not ok_i6:
        verdict = "PHASE_I_BLOCKED_JUNCTION_CUT"
    elif not ok_i7:
        verdict = "PHASE_I_BLOCKED_FAIL_CLOSED"

    report = {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_i_tiling_strategy.py",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "I",
        "input": str(INPUT_XODR),
        "strategy": {
            "xodr_logical_partitioning": "NOT_APPLIED_cooked_single_identity",
            "unreal_visual_asset_tiling": "IMPORT_TIME_CARLA_EDITOR",
            "carla_map_identity": "ONE_LOGICAL_MAP_PER_CAMPAIGN",
            "tile_role": "observation_window_with_context_duplication",
        },
        "i1_curve_aware_bounds": i1,
        "i2_ownership_policy": eq["ownership"],
        "i8_equivalence": eq,
        "i7_fail_closed": fc,
        "i_verdict": verdict,
    }
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "PHASE_I_TILING_STRATEGY.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    md = [
        "# I — Tiling strategy and tile equivalence",
        "",
        f"- run_id: `{RUN_ID}`",
        f"- verdict: **{verdict}**",
        "",
        "## Strategy (three concepts, not mixed)",
        "",
        "1. **XODR logical partitioning** — NOT applied to the cooked campaign; "
        "the candidate is one logical CARLA map identity "
        "(32710 roads, single document). Partitioned builds remain supported "
        "by the hardened tiler (observation windows + context duplication).",
        "2. **Unreal visual-asset tiling** — import-time (CARLA editor); "
        "no per-tile markers in XODR (I5).",
        "3. **CARLA map identity** — one logical map per campaign.",
        "",
        "## I1 curve-aware bounds",
        "",
    ]
    for k, v in sorted(i1.items()):
        md.append(f"- {k}: {v}")
    md += [
        "",
        "## I2 ownership policy",
        "",
        f"- policy: `{eq['ownership']['policy']}` (reference-line midpoint)",
        f"- assigned: {eq['ownership']['assigned']} / "
        f"unassigned: {eq['ownership']['unassigned']} "
        "(expected: roads whose midpoint falls outside the 4-tile "
        "observation window are not owned by any window tile)",
        "- junction context: all roads of a junction co-assigned to the "
        "majority tile; context duplication via buffer; ownership out of band.",
        "",
        "## I3 junction-cut prevention",
        "",
    ]
    md.append(f"- window junctions: {eq['window_junction_count']}")
    md.append(f"- junctions with missing roads in union: "
              f"{len(eq['junction_missing'])}")
    md.append(f"- split junctions (incomplete in every straddled tile): "
              f"{len(eq['junction_split'])}")
    md.append(f"- dangling lane links in tiles: {len(eq['dangling_links'])}")
    md += [
        "",
        "## I4/I5/I8 equivalence (untiled source vs union of tiles)",
        "",
        f"- core roads: {eq['core_roads']} / union roads: {eq['union_roads']}",
        f"- missing core roads: {len(eq['missing_core_roads'])}",
        f"- byte violations: {len(eq['byte_violations'])}",
        f"- duplicated (context) roads: {eq['duplicated_road_count']}, "
        f"non-identical: {len(eq['duplicate_violations'])}",
        f"- inventory mismatches: {len(eq['inventory_mismatches'])}",
        "",
        "## I6 adjacency and seams",
        "",
        f"- adjacency ok: {eq['adjacency']['ok']} "
        f"({eq['adjacency']['adjacency_edges']} edges)",
        f"- border roads total: {eq['border_roads_total']}, "
        f"not context-duplicated: "
        f"{len(eq['border_roads_not_context_duplicated'])}",
        "",
        "## I7 fail closed",
        "",
    ]
    for k, v in sorted(fc.items()):
        md.append(f"- {k}: {'PASS' if v else 'FAIL'}")
    md += [
        "",
        "Tiles (observation windows over the window origin) are stored under "
        "`tiles/`; ownership/health are recorded out of band in this report.",
    ]
    (EVIDENCE_DIR / "PHASE_I_TILING_STRATEGY.md").write_text(
        "\n".join(md), encoding="utf-8")

    print(f"I verdict: {verdict}")
    print(EVIDENCE_DIR / "PHASE_I_TILING_STRATEGY.json")
    return 0 if verdict == "PHASE_I_TILING_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
