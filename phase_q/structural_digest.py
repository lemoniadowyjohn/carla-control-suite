"""Q-structural protected digests (read-only analysis).

Canonical digests over the structural skeleton of an OpenDRIVE map, used to
freeze the semantic parent and to prove post-mutation structural invariance.

Protected digests (Stage 1 freeze + Stage 5 post-mutation integrity):

PLANVIEW_DIGEST
    Per road, every <geometry> child in order:
        (s, x, y, hdg, length, type, geometry-specific params)
    Geometry params are type-specific (line has none; arc -> curvatureStart/
    curvatureEnd; spiral -> curveStartFactor; poly3 -> a/b/c/d; paramPoly3 ->
    aU/bU/cU/dU/aV/bV/cV/dV/ pRange p1 p2).

ROAD_LINK_DIGEST
    Per road: (id, predecessor, successor, neighbor ids/types/sides) in order.

JUNCTION_DIGEST
    All <junction> in order: id, type, group, and each <connection>
    (in, out, type, maneuver) and its <laneLink> (from, to).

LANELINK_DIGEST
    All <laneLink> (from, to) across all connections, deterministic order.

LANESECTION_DIGEST
    Per road: laneSection count and, per section, start + each lane
    (id, type, level, direction) + lane's <type>/'<roadMark>' summaries.

ELEVATION_DIGEST
    Per road: every <elevation> (s, a, b, c, d) in order, plus superelevation
    profiles.
"""
from __future__ import annotations

import hashlib
from typing import Any, List, Tuple

from phase_q.common import XodrTree, norm_id

SEP = "\x1f"


def _n(v: Any) -> str:
    if v is None:
        return ""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return norm_id(v)
    if f == 0.0:
        f = 0.0
    return repr(f)


def _geom_params(geom) -> Tuple[str, ...]:
    t = norm_id(geom.get("type"))
    if t == "line":
        return ()
    if t == "arc":
        return (_n(geom.get("curvatureStart")), _n(geom.get("curvatureEnd")))
    if t == "spiral":
        return (_n(geom.get("curveStartFactor")),)
    if t == "poly3":
        return (_n(geom.get("a")), _n(geom.get("b")), _n(geom.get("c")), _n(geom.get("d")))
    if t == "paramPoly3":
        return tuple(_n(geom.get(k)) for k in (
            "aU", "bU", "cU", "dU", "aV", "bV", "cV", "dV", "pRange", "p1", "p2"))
    # fallback: all attributes
    return tuple(f"{norm_id(k)}={norm_id(v)}" for k, v in sorted(geom.items()))


def planview_digests(parsed: XodrTree) -> List[str]:
    root = parsed.root
    out = []
    for road in root.findall("road"):
        rid = norm_id(road.get("id"))
        geoms = []
        pv = road.find("planView")
        if pv is not None:
            for g in pv.findall("geometry"):
                geoms.append(SEP.join([
                    _n(g.get("s")), _n(g.get("x")), _n(g.get("y")),
                    _n(g.get("hdg")), _n(g.get("length")),
                    norm_id(g.get("type")), *_geom_params(g)
                ]))
        out.append(f"road:{rid}:geom_count={len(geoms)}")
        for g in geoms:
            out.append(g)
    return out


def road_link_digests(parsed: XodrTree) -> List[str]:
    root = parsed.root
    out = []
    for road in root.findall("road"):
        rid = norm_id(road.get("id"))
        links = ["road:{}".format(rid)]
        rl = road.find("link")
        for tag in ("predecessor", "successor", "neighbor"):
            for e in rl.findall(tag) if rl is not None else []:
                links.append(f"{tag}:{norm_id(e.get('elementType'))}:{norm_id(e.get('elementId'))}:{norm_id(e.get('side'))}")
        out.append(SEP.join(links))
    return out


def junction_digests(parsed: XodrTree) -> List[str]:
    root = parsed.root
    out = []
    lane_links = []
    for j in root.findall("junction"):
        jid = norm_id(j.get("id"))
        out.append(f"junction:{jid}:type={norm_id(j.get('type'))}:group={norm_id(j.get('group'))}")
        for c in j.findall("connection"):
            out.append(f"  connection:{norm_id(c.get('id'))}:{norm_id(c.get('in'))}->{norm_id(c.get('out'))}:type={norm_id(c.get('type'))}:maneuver={norm_id(c.get('maneuver'))}")
            for ll in c.findall("laneLink"):
                rec = f"    laneLink:from={norm_id(ll.get('from'))}:to={norm_id(ll.get('to'))}"
                out.append(rec)
                lane_links.append(f"{jid}:{norm_id(c.get('in'))}:{norm_id(c.get('out'))}:from={norm_id(ll.get('from'))}:to={norm_id(ll.get('to'))}")
    return out, lane_links


def lanesection_digests(parsed: XodrTree) -> List[str]:
    root = parsed.root
    out = []
    for road in root.findall("road"):
        rid = norm_id(road.get("id"))
        lanes = road.find("lanes")
        if lanes is None:
            continue
        secs = lanes.findall("laneSection")
        out.append(f"road:{rid}:laneSections={len(secs)}")
        for ls in secs:
            s = _n(ls.get("s"))
            out.append(f"  s={s}")
            for side_tag in ("left", "right", "center"):
                side = ls.find(side_tag)
                if side is None:
                    continue
                for ln in side.findall("lane"):
                    marks = [(norm_id(rm.get("type")), norm_id(rm.get("weight")))
                             for rm in ln.findall("roadMark")]
                    out.append(f"    {side_tag}/lane:id={norm_id(ln.get('id'))}:type={norm_id(ln.get('type'))}:level={norm_id(ln.get('level'))}:dir={norm_id(ln.get('direction'))}:marks={len(marks)}")
    return out


def elevation_digests(parsed: XodrTree) -> List[str]:
    root = parsed.root
    out = []
    for road in root.findall("road"):
        rid = norm_id(road.get("id"))
        prof = road.find("elevationProfile")
        sup = road.find("superelevation")
        if prof is not None:
            pts = [(norm_id(e.get("s")), _n(e.get("a")), _n(e.get("b")), _n(e.get("c")), _n(e.get("d")))
                   for e in prof.findall("elevation")]
            out.append(f"road:{rid}:elev_count={len(pts)}")
            for p in pts:
                out.append(SEP.join(p))
        if sup is not None:
            for e in sup.findall("elevation"):
                out.append(f"road:{rid}:superelev:s={_n(e.get('s'))}:a={_n(e.get('a'))}:b={_n(e.get('b'))}:c={_n(e.get('c'))}:d={_n(e.get('d'))}")
    return out


def _list_digest(items: List[str]) -> str:
    h = hashlib.sha256()
    h.update(str(len(items)).encode("utf-8"))
    for it in items:
        h.update(SEP.encode("utf-8"))
        h.update(it.encode("utf-8"))
    return h.hexdigest()


def all_structural_digests(xodr_text: str) -> dict:
    parsed = XodrTree(xodr_text)
    pv = planview_digests(parsed)
    rl = road_link_digests(parsed)
    jc, ll = junction_digests(parsed)
    ls = lanesection_digests(parsed)
    el = elevation_digests(parsed)
    h = hashlib.sha256()
    for name, lst in (("planview", pv), ("road_link", rl), ("junction", jc),
                      ("lanelink", ll), ("lanesection", ls), ("elevation", el)):
        h.update(name.encode("utf-8"))
        h.update(SEP.encode("utf-8"))
        h.update(_list_digest(lst).encode("utf-8"))
    combined = h.hexdigest()
    return {
        "schema": "phase_q/structural_digest/v1",
        "planview_digest": _list_digest(pv),
        "road_link_digest": _list_digest(rl),
        "junction_digest": _list_digest(jc),
        "lanelink_digest": _list_digest(ll),
        "lanesection_digest": _list_digest(ls),
        "elevation_digest": _list_digest(el),
        "roads": len(parsed.findall("road")),
        "junctions": len(parsed.findall("junction")),
        "combined_structural_digest": combined,
    }
