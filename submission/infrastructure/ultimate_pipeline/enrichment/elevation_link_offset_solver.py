# ultimate_pipeline/enrichment/elevation_link_offset_solver.py
"""Post-pass to reduce elevation discontinuities at road links by solving per-road vertical offsets.

This adjusts only the elevation polynomial 'a' term per road (constant vertical shift).
It does NOT modify planView geometry, CRS, header offsets, or slopes (b/c/d).

Notes:
- We keep eps_z unchanged (fail-closed). We fix the artifact deterministically.
- Real OSM-derived graphs can contain inconsistent cycles and junction/link noise; a pure
  Jacobi mean update often leaves residual seams.

Algorithm (graph relaxation):
- For each road, compute z_start and z_end by evaluating its elevation profile at s=0 and s=length.
- For each road-road link, define constraint at the linked endpoints resolved via OpenDRIVE
  contactPoint semantics (same as quality.check_elevation_continuity):
    own side: successor -> end, predecessor -> start
    other side: contactPoint (start/end; defaults to start)
  Constraint: (z_own + d_own) ~= (z_other + d_other)
- Solve offsets with:
    (1) deterministic spanning-tree propagation init
    (2) robust edge relaxation (Gauss-Seidel) with a fixed anchor per component

Enabled only when UP_ELEVATION_CONTINUITY_OFFSETS=1 (default OFF).
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
import xml.etree.ElementTree as ET


def _safe_float(v: Optional[str], default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


@dataclass
class RoadElev:
    """Elevation profile summary used for link-offset solving."""

    elev_elems: List[ET.Element]
    length: float
    z_start: float
    z_end: float


def _get_road_length(road: ET.Element) -> float:
    return _safe_float(road.get("length"), 0.0)


def _eval_elevation_at(elevs: List[ET.Element], s: float) -> float:
    """Evaluate OpenDRIVE elevation profile at longitudinal position s."""
    if not elevs:
        return 0.0
    segs = sorted(elevs, key=lambda e: _safe_float(e.get("s"), 0.0))
    active = segs[0]
    for e in segs:
        if _safe_float(e.get("s"), 0.0) <= float(s):
            active = e
        else:
            break
    s0 = _safe_float(active.get("s"), 0.0)
    # Do not extrapolate backwards if the chosen segment starts after the queried s.
    # This matches the endpoint behavior used in quality.check_elevation_continuity.
    ds = max(0.0, float(s) - float(s0))
    a = _safe_float(active.get("a"), 0.0)
    b = _safe_float(active.get("b"), 0.0)
    c = _safe_float(active.get("c"), 0.0)
    d = _safe_float(active.get("d"), 0.0)
    return float(a + b * ds + c * ds * ds + d * ds * ds * ds)


def _read_profile(road: ET.Element) -> Optional[RoadElev]:
    prof = road.find("elevationProfile")
    if prof is None:
        return None
    elevs = prof.findall("elevation")
    if not elevs:
        return None
    length = _get_road_length(road)
    z0 = _eval_elevation_at(elevs, 0.0)
    zL = _eval_elevation_at(elevs, length if length > 0.0 else 0.0)
    return RoadElev(elev_elems=elevs, length=length, z_start=z0, z_end=zL)


def _normalize_contact_point(value: Optional[str]) -> str:
    cp = (value or "start").strip().lower()
    return cp if cp in ("start", "end") else "start"


def _resolve_link_sides(link_kind: str, other_contact_point: str) -> Tuple[str, str]:
    """Match quality.check_elevation_continuity semantics for endpoints."""
    own_side = "end" if link_kind == "successor" else "start"
    other_side = _normalize_contact_point(other_contact_point)
    return own_side, other_side


def _z_at(re: RoadElev, side: str) -> float:
    return float(re.z_end if side == "end" else re.z_start)


def _parse_links(road: ET.Element) -> List[Tuple[str, str, str]]:
    """Return (kind, elementId, contactPoint) tuples for road-to-road links."""
    out: List[Tuple[str, str, str]] = []
    link = road.find("link")
    if link is None:
        return out
    for tag in ("predecessor", "successor"):
        el = link.find(tag)
        if el is None:
            continue
        if el.get("elementType") != "road":
            continue
        rid = el.get("elementId")
        if rid is None:
            continue
        out.append((tag, str(rid), _normalize_contact_point(el.get("contactPoint"))))
    return out


def apply_link_offset_correction_root(root: ET.Element) -> Dict:
    """Apply per-road vertical offset correction in-memory on an OpenDRIVE XML root element."""
    roads = [r for r in root.findall("road") if r.get("id") is not None]
    by_id: Dict[str, ET.Element] = {str(r.get("id")): r for r in roads}

    profs: Dict[str, RoadElev] = {}
    missing: List[str] = []
    for rid, r in by_id.items():
        prof = _read_profile(r)
        if prof is None:
            missing.append(rid)
            continue
        profs[rid] = prof

    if not profs:
        return {"ok": False, "reason": "no_elevation_profiles"}

    # Build constraints in the same endpoint conventions as the continuity QA.
    # rhs = z_u - z_v; desired equation is offsets[u] - offsets[v] + rhs == 0
    neighbors: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    edges: List[Tuple[str, str, float]] = []  # (u, v, rhs=z_u-z_v)
    for rid, r in by_id.items():
        if rid not in profs:
            continue
        re = profs[rid]
        for link_kind, ref, other_cp in _parse_links(r):
            if ref not in profs:
                continue
            te = profs[ref]

            own_side, other_side = _resolve_link_sides(link_kind, other_cp)
            # Constraint: (z_own + d_own) ~= (z_other + d_other)
            # Rearranged for relaxation update: d_own = d_other - (z_own - z_other)
            rhs = float(_z_at(re, own_side) - _z_at(te, other_side))
            neighbors[rid].append((ref, rhs))
            neighbors[ref].append((rid, -rhs))
            edges.append((rid, ref, rhs))

    offsets: Dict[str, float] = {}
    visited = set()
    components = 0

    for start in list(neighbors.keys()):
        if start in visited:
            continue
        components += 1
        q = deque([start])
        visited.add(start)
        comp = [start]
        while q:
            u = q.popleft()
            for v, _rhs in neighbors.get(u, []):
                if v not in visited:
                    visited.add(v)
                    q.append(v)
                    comp.append(v)

        comp_set = set(comp)
        for n in comp:
            offsets[n] = 0.0

        # (1) Deterministic spanning-tree propagation initialization:
        # If neighbors[u] contains (v, rhs_uv=z_u-z_v), then d_v = d_u + rhs_uv.
        dq = deque([start])
        seen = {start}
        while dq:
            u = dq.popleft()
            du = offsets[u]
            for v, rhs_uv in neighbors.get(u, []):
                if v in seen:
                    continue
                offsets[v] = du + float(rhs_uv)
                seen.add(v)
                dq.append(v)

        # (2) Robust edge-based relaxation (Gauss-Seidel) with fixed anchor.
        # Distributes inconsistency in cyclic graphs.
        for _it in range(250):
            max_err = 0.0
            for u, v, rhs_uv in edges:
                if u not in comp_set or v not in comp_set:
                    continue
                err = offsets[u] - offsets[v] + float(rhs_uv)  # want 0
                if abs(err) < 1e-9:
                    continue
                max_err = max(max_err, abs(err))
                if u == start:
                    offsets[v] += err
                elif v == start:
                    offsets[u] -= err
                else:
                    offsets[u] -= 0.5 * err
                    offsets[v] += 0.5 * err
            offsets[start] = 0.0
            if max_err < 1e-4:
                break

    applied = 0
    max_abs_offset = 0.0
    for rid, prof in profs.items():
        d = float(offsets.get(rid, 0.0))
        max_abs_offset = max(max_abs_offset, abs(d))
        if abs(d) < 1e-9:
            continue
        for e in prof.elev_elems:
            a = _safe_float(e.get("a"), 0.0)
            e.set("a", f"{a + d:.6f}")
        applied += 1

    return {
        "ok": True,
        "roads_with_offsets": applied,
        "components": components,
        "max_abs_offset_m": float(max_abs_offset),
        "note_debug": "Edge-relaxation solver (Gauss-Seidel) with per-component anchor.",
        "missing_roads": missing[:200],
        "note": "Applied per-road vertical offsets to reduce dz seams at links; slopes unchanged.",
    }


def apply_link_offset_correction(xodr_path: Union[str, Path]) -> Dict:
    """File-based wrapper for apply_link_offset_correction_root."""
    xodr_path = Path(xodr_path)
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    rep = apply_link_offset_correction_root(root)
    tree.write(xodr_path, encoding="utf-8", xml_declaration=True)
    return rep
