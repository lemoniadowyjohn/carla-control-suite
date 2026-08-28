#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
CARLA Safety Pruner (OpenDRIVE)
------------------------------

Goal:
  Make OpenDRIVE maps loadable in CARLA by enforcing a strict invariant:

    Every driving lane must have at least one resolvable predecessor
    or successor in the final lane graph.

Strategy:
  - Build a lane graph using ONLY:
      (A) lane continuity across laneSections in the same road (same lane_id)
      (B) junction connections via <junction><connection><laneLink from=".." to="..">
  - Iteratively prune "dangling" driving lanes (degree == 0)
  - Cascade prune:
      - laneSections with no driving lanes
      - roads with no driving lanes
      - junction laneLinks that reference deleted lanes
      - junction connections referencing missing roads

This module does NOT:
  - invent successors
  - "repair" junction topology
  - guess lane ID remappings

It produces:
  - pruned .xodr
  - report JSON (counts + details)

Usage:
  python -m ultimate_pipeline.quality.carla_pruner \
    --in  input.xodr \
    --out output_pruned.xodr \
    --report pruner_report.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple, Optional, Set

import xml.etree.ElementTree as ET

from ultimate_pipeline.artifacts.map_event_record import append_event, build_record


# -----------------------------
# Data structures
# -----------------------------

LaneKey = Tuple[str, int, int]  # (road_id, laneSection_index, lane_id)


@dataclass
class PruneReport:
    input_xodr: str
    output_xodr: str
    removed_lanes: int
    removed_lane_sections: int
    removed_roads: int
    removed_junction_lane_links: int
    removed_junction_connections: int
    iterations: int
    dangling_lane_keys_sample: List[str]


# -----------------------------
# Helpers
# -----------------------------

def _safe_float(x: Optional[str], default: float = 0.0) -> float:
    try:
        return float(x) if x is not None else default
    except Exception:
        return default


def _find_parent_map(root: ET.Element) -> Dict[int, ET.Element]:
    """
    ElementTree doesn't provide parent pointers.
    Build id(child)->parent lookup.
    """
    parent = {}
    for p in root.iter():
        for c in list(p):
            parent[id(c)] = p
    return parent


def _is_driving_lane(lane_elem: ET.Element) -> bool:
    return lane_elem.tag == "lane" and lane_elem.get("type") == "driving"


def _lane_length_estimate(road_elem: ET.Element) -> float:
    """
    Approx: use road length attribute if present.
    """
    return _safe_float(road_elem.get("length"), 0.0)


def _lane_id_int(lane_elem: ET.Element) -> Optional[int]:
    v = lane_elem.get("id")
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def _road_id(road_elem: ET.Element) -> Optional[str]:
    return road_elem.get("id")


def _lane_sections_sorted(road_elem: ET.Element) -> List[ET.Element]:
    lanes = road_elem.find("lanes")
    if lanes is None:
        return []
    lss = list(lanes.findall("laneSection"))
    lss.sort(key=lambda e: _safe_float(e.get("s"), 0.0))
    return lss


def _lane_section_bounds(road_elem: ET.Element) -> List[Tuple[float, float]]:
    lss = _lane_sections_sorted(road_elem)
    bounds: List[Tuple[float, float]] = []
    if not lss:
        return bounds
    s_vals = [_safe_float(ls.get("s"), 0.0) for ls in lss]
    road_len = _safe_float(road_elem.get("length"), 0.0)
    for idx, s0 in enumerate(s_vals):
        s1 = s_vals[idx + 1] if idx + 1 < len(s_vals) else road_len
        bounds.append((float(s0), float(s1)))
    return bounds


def _driving_lanes_in_lane_section(lane_section: ET.Element) -> List[ET.Element]:
    out = []
    for side_tag in ("left", "center", "right"):
        side = lane_section.find(side_tag)
        if side is None:
            continue
        for lane in side.findall("lane"):
            if _is_driving_lane(lane):
                out.append(lane)
    return out


def _has_any_driving_lane(lane_section: ET.Element) -> bool:
    return any(_is_driving_lane(l) for l in _driving_lanes_in_lane_section(lane_section))


def _road_has_any_driving_lane(road_elem: ET.Element) -> bool:
    for ls in _lane_sections_sorted(road_elem):
        if _has_any_driving_lane(ls):
            return True
    return False


def _lane_key_str(k: LaneKey) -> str:
    return f"road={k[0]} ls_idx={k[1]} lane_id={k[2]}"


# -----------------------------
# Graph building
# -----------------------------

@dataclass
class LaneNode:
    key: LaneKey
    lane_elem: ET.Element


class CarlaSafetyPruner:
    def __init__(self, min_road_length_m: float = 0.5):
        self.min_road_length_m = min_road_length_m

    def prune(self, in_xodr: str, out_xodr: str, report_path: Optional[str] = None) -> PruneReport:
        tree = ET.parse(in_xodr)
        root = tree.getroot()

        roads_by_id = self._index_roads(root)
        road_bounds = {rid: _lane_section_bounds(road) for rid, road in roads_by_id.items()}
        parent_map = _find_parent_map(root)

        # Build lane nodes + graph edges
        nodes = self._index_lane_nodes(roads_by_id)
        out_edges, in_edges = self._build_edges(root, roads_by_id, nodes)

        # Iteratively prune dangling driving lanes
        removed_lane_keys: List[LaneKey] = []
        iters = 0
        while True:
            iters += 1
            dangling = self._find_dangling(nodes, out_edges, in_edges, roads_by_id)
            if not dangling:
                break

            for k in dangling:
                # Remove lane element from XML
                lane_elem = nodes[k].lane_elem
                parent = parent_map.get(id(lane_elem))
                if parent is not None:
                    parent.remove(lane_elem)
                removed_lane_keys.append(k)

                # Remove from graph
                self._remove_node_from_graph(k, nodes, out_edges, in_edges)

            # refresh parent map after structural changes
            parent_map = _find_parent_map(root)

            # safety stop (should never happen)
            if iters > 50:
                break

        # Cascade prune laneSections and roads
        removed_lane_sections = self._prune_empty_lane_sections(root, roads_by_id)
        roads_by_id = self._index_roads(root)  # refresh after section removal
        removed_roads = self._prune_empty_roads(root, roads_by_id)

        # Junction cleanup (remove laneLinks and connections pointing to deleted stuff)
        roads_by_id = self._index_roads(root)
        removed_j_ll, removed_j_conn = self._cleanup_junctions(root, roads_by_id)

        # Write
        os.makedirs(os.path.dirname(out_xodr) or ".", exist_ok=True)
        tree.write(out_xodr, encoding="utf-8", xml_declaration=True)

        out_dir = os.path.dirname(out_xodr)
        for rid, ls_idx, lane_id in removed_lane_keys:
            road = roads_by_id.get(rid)
            bounds = road_bounds.get(rid, [])
            s_from = s_to = None
            if 0 <= ls_idx < len(bounds):
                s_from, s_to = bounds[ls_idx]
            road_len = _safe_float(road.get("length"), 0.0) if road is not None else 0.0
            removed_len = None
            removed_pct = None
            if s_from is not None and s_to is not None:
                removed_len = float(max(0.0, s_to - s_from))
                if road_len > 0:
                    removed_pct = float(removed_len / road_len)

            record = build_record(
                out_dir=out_dir,
                final_xodr_path=out_xodr,
                stage_name="carla_pruner",
                gate_name="carla_pruner",
                event_type="remove",
                road_id=str(rid),
                lane_section_id=str(ls_idx),
                lane_id=str(lane_id),
                junction_id=None,
                s_from=s_from,
                s_to=s_to,
                removed_length_m=removed_len,
                removed_length_pct=removed_pct,
            )
            append_event(out_dir, record)

        rep = PruneReport(
            input_xodr=in_xodr,
            output_xodr=out_xodr,
            removed_lanes=len(removed_lane_keys),
            removed_lane_sections=removed_lane_sections,
            removed_roads=removed_roads,
            removed_junction_lane_links=removed_j_ll,
            removed_junction_connections=removed_j_conn,
            iterations=iters,
            dangling_lane_keys_sample=[_lane_key_str(k) for k in removed_lane_keys[:50]],
        )

        if report_path:
            os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(asdict(rep), f, indent=2)

        return rep

    # ---------- indexing ----------

    @staticmethod
    def _index_roads(root: ET.Element) -> Dict[str, ET.Element]:
        roads = {}
        for r in root.findall("road"):
            rid = _road_id(r)
            if rid is not None:
                roads[rid] = r
        return roads

    @staticmethod
    def _index_lane_nodes(roads_by_id: Dict[str, ET.Element]) -> Dict[LaneKey, LaneNode]:
        nodes: Dict[LaneKey, LaneNode] = {}
        for rid, road in roads_by_id.items():
            lss = _lane_sections_sorted(road)
            for i, ls in enumerate(lss):
                for lane in _driving_lanes_in_lane_section(ls):
                    lid = _lane_id_int(lane)
                    if lid is None:
                        continue
                    # CARLA hates driving lane id == 0; if it exists, it should already be removed earlier.
                    if lid == 0:
                        continue
                    nodes[(rid, i, lid)] = LaneNode((rid, i, lid), lane)
        return nodes

    # ---------- edge construction ----------

    def _build_edges(
        self,
        root: ET.Element,
        roads_by_id: Dict[str, ET.Element],
        nodes: Dict[LaneKey, LaneNode],
    ) -> Tuple[Dict[LaneKey, Set[LaneKey]], Dict[LaneKey, Set[LaneKey]]]:
        out_edges: Dict[LaneKey, Set[LaneKey]] = {k: set() for k in nodes.keys()}
        in_edges: Dict[LaneKey, Set[LaneKey]] = {k: set() for k in nodes.keys()}

        # A) Same-road continuity across laneSections (same lane_id)
        for rid, road in roads_by_id.items():
            lss = _lane_sections_sorted(road)
            for i in range(len(lss) - 1):
                # Map lane_id -> key in section i and i+1
                ids_i = {k[2]: k for k in nodes.keys() if k[0] == rid and k[1] == i}
                ids_j = {k[2]: k for k in nodes.keys() if k[0] == rid and k[1] == i + 1}
                for lane_id, k1 in ids_i.items():
                    k2 = ids_j.get(lane_id)
                    if k2 is not None:
                        out_edges[k1].add(k2)
                        in_edges[k2].add(k1)

        # B) Junction connections via laneLink from->to
        #    We approximate endpoints:
        #      - from is on incomingRoad at its LAST laneSection
        #      - to is on connectingRoad at its FIRST laneSection if contactPoint=start else LAST if end
        for j in root.findall("junction"):
            for conn in j.findall("connection"):
                incoming = conn.get("incomingRoad")
                connecting = conn.get("connectingRoad")
                cp = (conn.get("contactPoint") or "start").lower()

                if not incoming or not connecting:
                    continue
                if incoming not in roads_by_id or connecting not in roads_by_id:
                    continue

                incoming_ls_last = self._last_lane_section_index(roads_by_id[incoming])
                connecting_ls_idx = self._first_lane_section_index(roads_by_id[connecting]) if cp == "start" \
                    else self._last_lane_section_index(roads_by_id[connecting])

                if incoming_ls_last is None or connecting_ls_idx is None:
                    continue

                for ll in conn.findall("laneLink"):
                    frm = ll.get("from")
                    to = ll.get("to")
                    try:
                        frm_id = int(frm) if frm is not None else None
                        to_id = int(to) if to is not None else None
                    except Exception:
                        continue

                    if frm_id is None or to_id is None:
                        continue
                    if frm_id == 0 or to_id == 0:
                        continue

                    k_from = (incoming, incoming_ls_last, frm_id)
                    k_to = (connecting, connecting_ls_idx, to_id)

                    if k_from in nodes and k_to in nodes:
                        out_edges[k_from].add(k_to)
                        in_edges[k_to].add(k_from)

        return out_edges, in_edges

    @staticmethod
    def _first_lane_section_index(road: ET.Element) -> Optional[int]:
        lss = _lane_sections_sorted(road)
        return 0 if lss else None

    @staticmethod
    def _last_lane_section_index(road: ET.Element) -> Optional[int]:
        lss = _lane_sections_sorted(road)
        return (len(lss) - 1) if lss else None

    # ---------- dangling detection ----------

    def _find_dangling(
        self,
        nodes: Dict[LaneKey, LaneNode],
        out_edges: Dict[LaneKey, Set[LaneKey]],
        in_edges: Dict[LaneKey, Set[LaneKey]],
        roads_by_id: Dict[str, ET.Element],
    ) -> List[LaneKey]:
        dangling: List[LaneKey] = []
        for k in list(nodes.keys()):
            road_id = k[0]
            road = roads_by_id.get(road_id)
            if road is None:
                dangling.append(k)
                continue

            # Prune tiny roads that can't reasonably be driven (CARLA often hates these)
            _road_len_est = _lane_length_estimate(road)
            if not math.isfinite(_road_len_est) or _road_len_est < self.min_road_length_m:
                dangling.append(k)
                continue

            deg = len(out_edges.get(k, set())) + len(in_edges.get(k, set()))
            if deg == 0:
                dangling.append(k)
        return dangling

    @staticmethod
    def _remove_node_from_graph(
            k: LaneKey,
        nodes: Dict[LaneKey, LaneNode],
        out_edges: Dict[LaneKey, Set[LaneKey]],
        in_edges: Dict[LaneKey, Set[LaneKey]],
    ) -> None:
        # remove incident edges
        for t in out_edges.get(k, set()):
            in_edges.get(t, set()).discard(k)
        for s in in_edges.get(k, set()):
            out_edges.get(s, set()).discard(k)

        out_edges.pop(k, None)
        in_edges.pop(k, None)
        nodes.pop(k, None)

    # ---------- cascade pruning ----------

    @staticmethod
    def _prune_empty_lane_sections(root: ET.Element, roads_by_id: Dict[str, ET.Element]) -> int:
        removed = 0
        parent_map = _find_parent_map(root)
        for rid, road in list(roads_by_id.items()):
            lanes = road.find("lanes")
            if lanes is None:
                continue
            for ls in list(lanes.findall("laneSection")):
                if not _has_any_driving_lane(ls):
                    lanes.remove(ls)
                    removed += 1
        return removed

    @staticmethod
    def _prune_empty_roads(root: ET.Element, roads_by_id: Dict[str, ET.Element]) -> int:
        removed = 0
        for rid, road in list(roads_by_id.items()):
            if not _road_has_any_driving_lane(road):
                root.remove(road)
                removed += 1
        return removed

    @staticmethod
    def _cleanup_junctions(root: ET.Element, roads_by_id: Dict[str, ET.Element]) -> Tuple[int, int]:
        """
        Remove junction laneLinks referencing missing roads.
        Also remove connections referencing missing roads.
        """
        removed_lane_links = 0
        removed_connections = 0

        for j in root.findall("junction"):
            for conn in list(j.findall("connection")):
                incoming = conn.get("incomingRoad")
                connecting = conn.get("connectingRoad")
                if not incoming or not connecting or incoming not in roads_by_id or connecting not in roads_by_id:
                    j.remove(conn)
                    removed_connections += 1
                    continue

                # If a connection has no laneLinks after pruning, remove it
                for ll in list(conn.findall("laneLink")):
                    frm = ll.get("from")
                    to = ll.get("to")
                    # If malformed, delete
                    try:
                        int(frm) if frm is not None else None
                        int(to) if to is not None else None
                    except Exception:
                        conn.remove(ll)
                        removed_lane_links += 1

                if len(conn.findall("laneLink")) == 0:
                    j.remove(conn)
                    removed_connections += 1

        return removed_lane_links, removed_connections


# -----------------------------
# CLI entry
# -----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="Input .xodr")
    ap.add_argument("--out", dest="out", required=True, help="Output pruned .xodr")
    ap.add_argument("--report", dest="report", default=None, help="Optional report.json")
    ap.add_argument("--min-road-len", dest="min_road_len", type=float, default=0.5)
    args = ap.parse_args()

    pruner = CarlaSafetyPruner(min_road_length_m=args.min_road_len)
    rep = pruner.prune(args.inp, args.out, report_path=args.report)

    print("✅ CARLA Safety Prune complete")
    print(f"   input : {rep.input_xodr}")
    print(f"   output: {rep.output_xodr}")
    print(f"   removed lanes        : {rep.removed_lanes}")
    print(f"   removed laneSections : {rep.removed_lane_sections}")
    print(f"   removed roads        : {rep.removed_roads}")
    print(f"   iterations           : {rep.iterations}")
    if args.report:
        print(f"   report               : {args.report}")


if __name__ == "__main__":
    main()
