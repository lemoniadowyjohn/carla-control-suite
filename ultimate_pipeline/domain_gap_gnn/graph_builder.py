#!/usr/bin/env python3
# ultimate_pipeline/domain_gap_gnn/graph_builder.py

from __future__ import annotations

import xml.etree.ElementTree as ET
import math
from typing import Any, Optional, Dict, List, Tuple

import torch
from torch_geometric.data import Data

from ultimate_pipeline.config.settings import SETTINGS
from ultimate_pipeline.geometry.opendrive_geometry_kernel import sample as sample_geometry


LANE_TYPES = ["driving", "shoulder", "sidewalk", "biking", "parking", "none"]

# ---------------------------------------------------------------------------
# OC-51 (RQ4): schema / feature-algorithm identity.
# These constants feed the canonical graph-schema descriptor (see
# gnn_provenance.canonical_graph_schema). Any change here MUST change the
# schema hash — never paper over it with a descriptive label.
# ---------------------------------------------------------------------------
GRAPH_SCHEMA_VERSION = "rq4_gnn_graph_schema_v1"
WIDTH_ALGORITHM_LEGACY_A_ONLY = "width_a_only_v0"
WIDTH_ALGORITHM_POLYNOMIAL_V1 = "width_poly_v1"
CURVATURE_ALGORITHM = "canonical_kernel_v1"
GEOMETRY_KERNEL_ID = (
    "ultimate_pipeline.geometry.opendrive_geometry_kernel.pose_at_s"
)

NODE_FEATURE_NAMES = [
    "lane_driving",
    "lane_shoulder",
    "lane_sidewalk",
    "lane_biking",
    "lane_parking",
    "lane_none",
    "speed_norm",
    "width_mean_norm",
    "width_std_norm",
    "curv_mean_norm",
    "curv_std_norm",
    "junction_flag",
]

EDGE_SEMANTICS = [
    "lane_successor_intra_road_next_laneSection",
    "lane_predecessor_intra_road_prev_laneSection",
    "road_boundary_successor_via_road_link_contact_point",
    "road_boundary_predecessor_via_road_link_contact_point",
]

JUNCTION_EDGE_POLICY = (
    "no_edge_when_junction_mediated: tile-scoped XODR files carry no "
    "<junction> definitions, so junction-mediated lane links are skipped "
    "(no edge added) rather than guessed"
)

# Deterministic sampling used when a lane-width record has no bounded
# interval (last record of the last laneSection with unknown road length).
OPEN_ENDED_WIDTH_WINDOW_M = 5.0
WIDTH_POLY_SAMPLES_PER_INTERVAL = 8


def _one_hot_lane_type(t: str) -> List[float]:
    if t not in LANE_TYPES:
        t = "none"
    return [1.0 if t == lt else 0.0 for lt in LANE_TYPES]


def _safe_float(v, default: float = 0.0, *, strict: bool = False) -> float:
    """Parse a float with a documented fallback.

    Rule (OC-51 §12): absent values (None) keep the documented prior
    ``default`` in every mode. Present-but-unparseable or non-finite values
    keep ``default`` in LEGACY_TOLERANT mode but raise in RESEARCH_STRICT
    mode instead of silently becoming legitimate zero-valued ML features.
    """
    if v is None:
        return default
    try:
        out = float(v)
    except Exception:
        if strict:
            raise ValueError(f"non-numeric structural value: {v!r}")
        return default
    if not math.isfinite(out):
        if strict:
            raise ValueError(f"non-finite structural value: {v!r}")
        return default
    return out


def node_feature_dim() -> int:
    """Return the number of node features produced by build_from_xodr()."""
    # one-hot lane type + speed + width_mean + width_std + curvature_mean
    # + curvature_std + junction_flag
    dim = int(len(LANE_TYPES) + 6)
    assert dim == len(NODE_FEATURE_NAMES), (
        f"node_feature_dim={dim} disagrees with NODE_FEATURE_NAMES "
        f"({len(NODE_FEATURE_NAMES)}); schema hash would be wrong"
    )
    return dim


def _road_curvatures(road: ET.Element, *, strict: bool = False) -> List[float]:
    """Collect finite curvature samples for every supported primitive once."""
    curvatures: List[float] = []
    for geometry in road.findall("./planView/geometry"):
        try:
            length = _safe_float(geometry.get("length"), 0.0, strict=strict)
            spacing = max(length / 3.0, 0.25)
            curvatures.extend(
                float(pose.curvature)
                for pose in sample_geometry(geometry, spacing)
                if pose.curvature is not None and math.isfinite(float(pose.curvature))
            )
        except (TypeError, ValueError, ZeroDivisionError):
            if strict:
                raise
            # Preserve the old arc-only fallback for malformed/unknown input.
            arc = geometry.find("arc")
            if arc is not None:
                curvatures.append(_safe_float(arc.get("curvature"), 0.0))
    return curvatures or [0.0]


def _parse_width_coeffs(
    width_el: ET.Element, *, strict: bool
) -> Tuple[float, float, float, float, float]:
    """Return (s_offset, a, b, c, d) for one <width> record.

    Missing attributes keep the documented prior (0.0); present-but-invalid
    values raise in strict mode (§12).
    """
    s_offset = _safe_float(width_el.get("sOffset", 0.0), 0.0, strict=strict)
    a = _safe_float(width_el.get("a", 0.0), 0.0, strict=strict)
    b = _safe_float(width_el.get("b", 0.0), 0.0, strict=strict)
    c = _safe_float(width_el.get("c", 0.0), 0.0, strict=strict)
    d = _safe_float(width_el.get("d", 0.0), 0.0, strict=strict)
    return s_offset, a, b, c, d


def _eval_width_poly(a: float, b: float, c: float, d: float, ds: float) -> float:
    """Evaluate the OpenDRIVE lane-width function a + b·ds + c·ds² + d·ds³."""
    return a + b * ds + c * ds * ds + d * ds * ds * ds


def _lane_width_stats(
    lane: ET.Element,
    *,
    strict: bool,
    width_mode: str,
    section_end_abs: Optional[float],
    section_s: float,
) -> Tuple[float, float]:
    """Mean/std of lane width over the lane's domain.

    - ``legacy`` (``width_a_only_v0``): historical behaviour — statistics
      over the bare ``a`` coefficients only. Reproduces PRE_FIX embeddings.
    - ``polynomial`` (``width_poly_v1``): each ``<width>`` record's
      polynomial is evaluated over its applicable interval
      (``[sOffset_i, sOffset_{i+1})``, or up to the laneSection end / road
      end / fallback window for the last record) with deterministic uniform
      sampling; statistics are pooled over all samples.
    """
    records = [
        _parse_width_coeffs(w, strict=strict) for w in lane.findall("width")
    ]
    if not records:
        # Documented prior for lanes without width records (e.g. center
        # lanes): 3.5 m in every mode.
        return 3.5, 0.0
    if width_mode == "legacy":
        widths = [a for _, a, _, _, _ in records]
        w_mean = sum(widths) / len(widths)
        w_std = (
            sum((w - w_mean) ** 2 for w in widths) / len(widths)
        ) ** 0.5
        return w_mean, w_std
    if width_mode != "polynomial":
        raise ValueError(f"unknown width_mode: {width_mode!r}")

    records.sort(key=lambda r: r[0])
    if section_end_abs is not None and math.isfinite(section_end_abs):
        section_remainder = max(float(section_end_abs) - float(section_s), 0.0)
    else:
        section_remainder = None
    samples: List[float] = []
    for i, (s_offset, a, b, c, d) in enumerate(records):
        if i + 1 < len(records):
            interval_len = max(records[i + 1][0] - s_offset, 0.0)
        elif section_remainder is not None:
            interval_len = max(section_remainder - s_offset, 0.0)
        else:
            interval_len = OPEN_ENDED_WIDTH_WINDOW_M
        if interval_len <= 0.0:
            points = [0.0]
        else:
            n = WIDTH_POLY_SAMPLES_PER_INTERVAL
            points = [interval_len * j / (n - 1) for j in range(n)]
        for ds in points:
            val = _eval_width_poly(a, b, c, d, ds)
            if not math.isfinite(val):
                if strict:
                    raise ValueError(
                        f"non-finite lane-width polynomial value at ds={ds}"
                    )
                continue
            samples.append(val)
    if not samples:
        if strict:
            raise ValueError("no finite lane-width samples")
        widths = [a for _, a, _, _, _ in records]
        w_mean = sum(widths) / len(widths)
        w_std = (
            sum((w - w_mean) ** 2 for w in widths) / len(widths)
        ) ** 0.5
        return w_mean, w_std
    w_mean = sum(samples) / len(samples)
    w_std = (sum((w - w_mean) ** 2 for w in samples) / len(samples)) ** 0.5
    return w_mean, w_std


def describe_graph_schema(*, width_mode: str = "legacy") -> Dict[str, Any]:
    """Canonical schema descriptor built from actual graph semantics (§8).

    ``width_mode`` selects the width feature algorithm recorded in the
    descriptor, so legacy and polynomial feature definitions hash
    differently by construction.
    """
    from .gnn_provenance import canonical_graph_schema

    if width_mode == "legacy":
        width_algo: str = WIDTH_ALGORITHM_LEGACY_A_ONLY
    elif width_mode == "polynomial":
        width_algo = WIDTH_ALGORITHM_POLYNOMIAL_V1
    else:
        raise ValueError(f"unknown width_mode: {width_mode!r}")
    max_speed = float(getattr(SETTINGS, "GNN_MAX_SPEED_KMH", 130.0))
    max_width = float(getattr(SETTINGS, "GNN_MAX_LANE_WIDTH_M", 5.0))
    max_curv = float(getattr(SETTINGS, "GNN_MAX_CURVATURE", 0.2))
    return canonical_graph_schema(
        node_feature_names=NODE_FEATURE_NAMES,
        normalization_constants={
            "GNN_MAX_SPEED_KMH": max_speed,
            "GNN_MAX_LANE_WIDTH_M": max_width,
            "GNN_MAX_CURVATURE": max_curv,
        },
        lane_type_vocabulary=LANE_TYPES,
        edge_semantics=EDGE_SEMANTICS,
        junction_edge_policy=JUNCTION_EDGE_POLICY,
        geometry_kernel={
            "module": "ultimate_pipeline.geometry.opendrive_geometry_kernel",
            "entrypoint": GEOMETRY_KERNEL_ID,
            "primitives": ["line", "arc", "spiral", "poly3", "paramPoly3"],
        },
        curvature_policy={
            "algorithm": CURVATURE_ALGORITHM,
            "spacing_rule": "max(length/3.0, 0.25)",
            "scope": "per_road_samples_shared_across_all_lane_nodes_of_road",
            "nonfinite": "rejected_before_pooling",
            "fallback_empty": "single_zero_sample",
        },
        width_feature_algorithm=width_algo,
        schema_version=GRAPH_SCHEMA_VERSION,
    )


def graph_schema_hash(*, width_mode: str = "legacy") -> str:
    """Content-derived schema hash (canonical JSON over §8 semantics)."""
    from .gnn_provenance import graph_schema_hash as _hash

    return _hash(describe_graph_schema(width_mode=width_mode))


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
    def build_from_xodr(
        xodr_path: str,
        *,
        strict: bool = False,
        width_mode: str = "legacy",
    ) -> Optional[Data]:
        """Build a lane-level graph from one OpenDRIVE tile.

        Args:
            strict: RESEARCH_STRICT mode — present-but-invalid structural
                values raise (the tile is then classified INVALID by the
                dataset loader) instead of silently becoming zero-valued
                features. Strict mode requires ``width_mode="polynomial"``
                so the authoritative feature definition is unambiguous.
            width_mode: ``"legacy"`` reproduces historical PRE_FIX features
                (width stats over bare ``a`` coefficients);
                ``"polynomial"`` evaluates the full ``a + b·ds + c·ds² +
                d·ds³`` width function over its domain (POST_FIX).
        """
        if strict and width_mode == "legacy":
            raise ValueError(
                "RESEARCH_STRICT mode requires width_mode='polynomial': "
                "refusing to certify legacy a-only width features as strict"
            )
        try:
            root = ET.parse(xodr_path).getroot()
        except Exception:
            if strict:
                raise ValueError(f"unparseable XODR: {xodr_path}")
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

        # Section layout per road (for polynomial width intervals).
        lane_sections_by_road_pre: Dict[str, List[float]] = {}
        road_length_by_road: Dict[str, Optional[float]] = {}
        for road in root.findall("road"):
            rid = road.get("id", "")
            try:
                road_length_by_road[rid] = _safe_float(
                    road.get("length"), float("nan"), strict=False
                )
                if not math.isfinite(float(road_length_by_road[rid] or float("nan"))):
                    road_length_by_road[rid] = None
            except Exception:
                road_length_by_road[rid] = None
            lanes_el = road.find("lanes")
            if lanes_el is not None:
                try:
                    lane_sections_by_road_pre[rid] = sorted(
                        _safe_float(ls.get("s", "0.0"), strict=strict)
                        for ls in lanes_el.findall("laneSection")
                    )
                except ValueError:
                    if strict:
                        raise
                    lane_sections_by_road_pre[rid] = sorted(
                        _safe_float(ls.get("s", "0.0"))
                        for ls in lanes_el.findall("laneSection")
                    )

        for road in root.findall("road"):
            road_id = road.get("id", "")
            is_junction = 1.0 if road.get("junction") not in (None, "-1") else 0.0

            # speed limit
            speed_elems = road.findall("./type/speed")
            speed = (
                _safe_float(speed_elems[0].get("max"), max_speed, strict=strict)
                if speed_elems else max_speed
            )

            lanes = road.find("lanes")
            if lanes is None:
                continue

            curvs = _road_curvatures(road, strict=strict)
            c_mean = sum(curvs) / len(curvs)
            c_std = (
                sum((c - c_mean) ** 2 for c in curvs) / len(curvs)
            ) ** 0.5

            for lsec in lanes.findall("laneSection"):
                sec_s = _safe_float(lsec.get("s", "0.0"), strict=strict)
                # Absolute end of this laneSection: next section s, else road
                # length, else None (fallback window inside _lane_width_stats).
                secs_pre = lane_sections_by_road_pre.get(road_id, [])
                section_end_abs: Optional[float] = None
                try:
                    pos = secs_pre.index(sec_s)
                    if pos + 1 < len(secs_pre):
                        section_end_abs = secs_pre[pos + 1]
                except ValueError:
                    pos = None
                if section_end_abs is None:
                    section_end_abs = road_length_by_road.get(road_id)

                for side_tag in ("left", "center", "right"):
                    side = lsec.find(side_tag)
                    if side is None:
                        continue

                    for lane in side.findall("lane"):
                        lane_id = lane.get("id", "0")
                        lane_type = lane.get("type", "none")

                        # lane widths (mode-selected feature definition)
                        w_mean, w_std = _lane_width_stats(
                            lane,
                            strict=strict,
                            width_mode=width_mode,
                            section_end_abs=section_end_abs,
                            section_s=sec_s,
                        )

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
