#!/usr/bin/env python3
# ultimate_pipeline/domain_gap_gnn/graph_builder.py

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional, Dict, List, Tuple

import torch
from torch_geometric.data import Data

from ultimate_pipeline.config.settings import SETTINGS


LANE_TYPES = ["driving", "shoulder", "sidewalk", "biking", "parking", "none"]


def _one_hot_lane_type(t: str) -> List[float]:
    if t not in LANE_TYPES:
        t = "none"
    return [1.0 if t == lt else 0.0 for lt in LANE_TYPES]


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def node_feature_dim() -> int:
    """Return the number of node features produced by build_from_xodr()."""
    # one-hot lane type + speed + width_mean + width_std + curvature_mean
    # + curvature_std + junction_flag
    return int(len(LANE_TYPES) + 6)


class MapGraphBuilder:
    """
    Converts an OpenDRIVE tile into a lane-level graph.

    Node:
        (road_id, laneSection_s, lane_id)

    Edge:
        laneLink successor / predecessor, resolved to the target
        laneSection (next/previous laneSection within the same road, or
        the linked road's boundary laneSection via contactPoint). Links
        that resolve through a junction are skipped: tile-scoped XODR
        files carry no <junction> definitions to resolve them against, so
        no edge is added rather than guessing.

    Features:
        - lane type (one-hot)
        - speed limit (normalized)
        - lane width mean / std (normalized)
        - curvature mean / std (arc-based)
        - junction flag
        - Total node features: N = len(LANE_TYPES) + scalar features
          (auto-detected at runtime from graph payload)
    """

    @staticmethod
    def build_from_xodr(xodr_path: str) -> Optional[Data]:
        try:
            root = ET.parse(xodr_path).getroot()
        except Exception:
            return None

        # -----------------------------
        # SETTINGS (explicit contract)
        # -----------------------------
        max_speed = getattr(SETTINGS, "GNN_MAX_SPEED_KMH", 130.0)
        max_width = getattr(SETTINGS, "GNN_MAX_LANE_WIDTH_M", 5.0)
        max_curv = getattr(SETTINGS, "GNN_MAX_CURVATURE", 0.2)

        # -----------------------------
        # Collect nodes (deterministic)
        # -----------------------------
        nodes: Dict[Tuple[str, float, str], List[float]] = {}

        for road in root.findall("road"):
            road_id = road.get("id", "")
            is_junction = 1.0 if road.get("junction") not in (None, "-1") else 0.0

            # speed limit
            speed_elems = road.findall("./type/speed")
            speed = (
                _safe_float(speed_elems[0].get("max"), max_speed)
                if speed_elems else max_speed
            )

            lanes = road.find("lanes")
            if lanes is None:
                continue

            for lsec in lanes.findall("laneSection"):
                sec_s = _safe_float(lsec.get("s", "0.0"))

                for side_tag in ("left", "center", "right"):
                    side = lsec.find(side_tag)
                    if side is None:
                        continue

                    for lane in side.findall("lane"):
                        lane_id = lane.get("id", "0")
                        lane_type = lane.get("type", "none")

                        # lane widths
                        widths = [
                            _safe_float(w.get("a", 0.0))
                            for w in lane.findall("width")
                        ] or [3.5]

                        w_mean = sum(widths) / len(widths)
                        w_std = (
                            sum((w - w_mean) ** 2 for w in widths) / len(widths)
                        ) ** 0.5

                        # curvature from arc geometries
                        curvs = []
                        for g in road.findall("./planView/geometry"):
                            arc = g.find("arc")
                            if arc is not None:
                                curvs.append(_safe_float(arc.get("curvature"), 0.0))
                        if not curvs:
                            curvs = [0.0]

                        c_mean = sum(curvs) / len(curvs)
                        c_std = (
                            sum((c - c_mean) ** 2 for c in curvs) / len(curvs)
                        ) ** 0.5

                        features: List[float] = []
                        features += _one_hot_lane_type(lane_type)
                        features += [speed / max_speed]
                        features += [w_mean / max_width, w_std / max_width]
                        features += [c_mean / max_curv, c_std / max_curv]
                        features += [is_junction]

                        key = (road_id, sec_s, lane_id)
                        nodes[key] = features

        if not nodes:
            return None

        # deterministic ordering
        keys = sorted(nodes.keys())
        idx = {k: i for i, k in enumerate(keys)}
        x = torch.tensor([nodes[k] for k in keys], dtype=torch.float32)

        # -----------------------------
        # Build edges (laneLink)
        # -----------------------------
        # A lane's <link><successor id="X"/> (or predecessor) refers to a lane
        # in a DIFFERENT laneSection: either the next/previous laneSection of
        # the SAME road, or (at a road boundary) a laneSection of a DIFFERENT
        # road reached via that road's own <link> element. Resolve that
        # target (road_id, laneSection_s) explicitly instead of assuming it's
        # the source lane's own laneSection -- otherwise every edge collapses
        # into a self-loop.
        road_link: Dict[str, ET.Element] = {}
        lane_sections_by_road: Dict[str, List[float]] = {}
        for road in root.findall("road"):
            rid = road.get("id", "")
            link_el = road.find("link")
            if link_el is not None:
                road_link[rid] = link_el
            lanes_el = road.find("lanes")
            if lanes_el is not None:
                lane_sections_by_road[rid] = sorted(
                    _safe_float(ls.get("s", "0.0"))
                    for ls in lanes_el.findall("laneSection")
                )

        def _resolve_target_section(
            road_id: str, sec_s: float, direction: str
        ) -> Optional[Tuple[str, float]]:
            """Resolve the (road_id, laneSection_s) reached by following
            `direction` ("successor" or "predecessor") from the laneSection
            at `sec_s` in `road_id`. Returns None when unresolvable from
            tile-local data alone (e.g. the connection is junction-mediated,
            and tile-scoped XODR files carry no <junction> definitions to
            resolve which lane that maps to)."""
            secs = lane_sections_by_road.get(road_id, [])
            try:
                pos = secs.index(sec_s)
            except ValueError:
                pos = None
            if pos is not None:
                if direction == "successor" and pos + 1 < len(secs):
                    return road_id, secs[pos + 1]
                if direction == "predecessor" and pos > 0:
                    return road_id, secs[pos - 1]

            # At a road boundary: follow the road-level link, if it points to
            # another road (not a junction, which we can't resolve here).
            link_el = road_link.get(road_id)
            if link_el is None:
                return None
            boundary_el = link_el.find(direction)
            if boundary_el is None or boundary_el.get("elementType") != "road":
                return None
            target_road = boundary_el.get("elementId", "")
            target_secs = lane_sections_by_road.get(target_road)
            if not target_secs:
                return None
            contact = boundary_el.get("contactPoint", "start" if direction == "successor" else "end")
            return target_road, (target_secs[0] if contact == "start" else target_secs[-1])

        edges: List[Tuple[int, int]] = []

        for road in root.findall("road"):
            road_id = road.get("id", "")
            for lsec in road.findall("./lanes/laneSection"):
                sec_s = _safe_float(lsec.get("s", "0.0"))

                for side_tag in ("left", "center", "right"):
                    side = lsec.find(side_tag)
                    if side is None:
                        continue

                    for lane in side.findall("lane"):
                        lane_id = lane.get("id", "0")
                        src = (road_id, sec_s, lane_id)
                        if src not in idx:
                            continue

                        link = lane.find("link")
                        if link is None:
                            continue

                        for direction in ("successor", "predecessor"):
                            link_target = link.find(direction)
                            if link_target is None:
                                continue
                            to_lane = link_target.get("id")
                            resolved = _resolve_target_section(road_id, sec_s, direction)
                            if resolved is None:
                                continue
                            t_road, t_sec_s = resolved
                            dst = (t_road, t_sec_s, to_lane)
                            if dst in idx:
                                edges.append((idx[src], idx[dst]))

        edge_index = (
            torch.tensor(edges, dtype=torch.long).t().contiguous()
            if edges else torch.empty((2, 0), dtype=torch.long)
        )

        return Data(x=x, edge_index=edge_index)
