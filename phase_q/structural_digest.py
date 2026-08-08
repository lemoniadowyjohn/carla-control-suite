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
    """v1 aggregate (6 categories) — kept for the pre-existing frozen authority."""
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


# ---------------------------------------------------------------------------
# v2 structural digests (R13). Keeps the v1 six categories byte-identical and
# adds the remaining R13-protected categories so the semantic-parent freeze
# covers all 13 protected digests:
#   PLANVIEW, ROAD_LINK, JUNCTION_CONNECTION, LANELINK, LANESECTION,
#   ELEVATION, SUPERELEVATION_CROSSFALL, ROADMARK, CONNECTOR_REPAIR
# plus (from signal_digest v2) SIGNAL_ELEMENT, SIGNAL_REFERENCE, CONTROLLER,
# COMBINED_TRAFFIC_CONTROL.
# ---------------------------------------------------------------------------
SUPERELEVATION_CROSSFALL_EMPTY = "EMPTY_COLLECTION"
SUPERELEVATION_CROSSFALL_MISSING = "MISSING_COLLECTION"
ROADMARK_EMPTY = "EMPTY_COLLECTION"
ROADMARK_MISSING = "MISSING_COLLECTION"
CONNECTOR_REPAIR_EMPTY = "EMPTY_COLLECTION"
CONNECTOR_REPAIR_MISSING = "MISSING_COLLECTION"


def superelevation_crossfall_digests(parsed: XodrTree) -> Tuple[List[str], str]:
    """SUPERELEVATION_CROSSFALL - per road <superelevation> and <crosssect>
    elems (s,a,b,c,d); PRESENT if any model, EMPTY if containers exist with
    zero records, MISSING otherwise. One digest covers both layers so the
    category is unambiguous for roundabout/banking maps."""
    root = parsed.root
    out: List[str] = []
    containers = 0
    elems = 0
    for road in root.findall("road"):
        rid = norm_id(road.get("id"))
        for e in road.findall("superelevation/elevation"):
            out.append(SEP.join([f"road:{rid}:superelev", *[_n(e.get(k)) for k in ("s", "a", "b", "c", "d")]]))
            containers += 1
            elems += 1
        for e in road.findall("crosssect/elevation"):
            out.append(SEP.join([f"road:{rid}:crossfall", *[_n(e.get(k)) for k in ("s", "a", "b", "c", "d")]]))
            containers += 1
            elems += 1
        if road.find("superelevation") is not None or road.find("crosssect") is not None:
            containers += 1
    state = SUPERELEVATION_CROSSFALL_PRESENT if elems else (
        SUPERELEVATION_CROSSFALL_EMPTY if containers else SUPERELEVATION_CROSSFALL_MISSING)
    return out, state


def roadmark_digests(parsed: XodrTree) -> Tuple[List[str], str]:
    """ROADMARK - per lane per-brand roadMark (sOffset,type,weight,color,
    lane,width,height). Missing lane sets -> MISSING_COLLECTION."""
    root = parsed.root
    out: List[str] = []
    containers = False
    elems = 0
    for road in root.findall("road"):
        rid = norm_id(road.get("id"))
        lanes = road.find("lanes")
        if lanes is None:
            continue
        for ls in lanes.findall("laneSection"):
            for side_tag in ("left", "right", "center"):
                side = ls.find(side_tag)
                if side is None:
                    continue
                for ln in side.findall("lane"):
                    marks = ln.findall("roadMark")
                    containers += 1
                    if not marks:
                        continue
                    elems += len(marks)
                    for rm in marks:
                        out.append(SEP.join([
                            f"road:{rid}", f"lane:{norm_id(ln.get('id'))}",
                            _n(rm.get("sOffset")), norm_id(rm.get("type")),
                            norm_id(rm.get("weight")), norm_id(rm.get("color")),
                            norm_id(rm.get("lane")), _n(rm.get("width"))]))
    state = ((ROADMARK_MISSING if not containers else ROADMARK_EMPTY)
             if not elems else _ROADMARK_PRESENT)
    return out, state


_ROADMARK_PRESENT = "PRESENT"
SUPERELEVATION_CROSSFALL_PRESENT = "PRESENT"


def connector_repair_digests(parsed: XodrTree, repaired_connector_road_ids) -> Tuple[List[str], str, list]:
    """CONNECTOR_REPAIR - deterministic digest over the connector roads that
    were zero-length-repaired (Category C, phase-E junction hardening). Frozen
    list of road ids; each repaired road's plan <geometry> rows (s,x,y,hdg,
    length,type) in road-id order. A mutation that undoes a repair (or any
    geometry row on these roads) changes the digest.

    Some inherited callers still pass this list under the name
    `repaired_junction_ids`; the elements ARE road ids (the 12 connector
    roads), which is the frozen semantic of the R04 authority record.
    """
    ids = [norm_id(x) for x in (repaired_connector_road_ids or ())]
    roads = {norm_id(r.get("id")): r for r in parsed.findall("road")}
    out: List[str] = []
    present_ids: List[str] = []
    for rid in ids:
        r = roads.get(rid)
        if r is None:
            continue
        present_ids.append(rid)
        pv = r.find("planView")
        geoms = pv.findall("geometry") if pv is not None else []
        out.append(f"road:{rid}:length={_n(r.get('length'))}:geom_count={len(geoms)}")
        for g in geoms:
            out.append(SEP.join([
                f"road:{rid}:geometry",
                _n(g.get("s")), _n(g.get("x")), _n(g.get("y")),
                _n(g.get("hdg")), _n(g.get("length")),
                norm_id(g.get("type")), *_geom_params(g),
            ]))
    state = "PRESENT" if ids and len(present_ids) == len(ids) else CONNECTOR_REPAIR_MISSING
    return out, state, [i for i in ids if i in roads]


def structural_digests_v2(xodr_text: str, repaired_junction_ids=None,
                          parsed: "XodrTree" = None) -> dict:
    """R13 13-category protected structural (9 structural categories here;
    the 4 traffic-control categories come from signal_digest v2). The six
    v1 categories remain byte-identical to frozen v1 digests.

    `repaired_junction_ids` carries the frozen connector-repair list: the 12
    repaired connector ROAD ids from the R04 authority record (legacy name)."""
    if parsed is None:
        parsed = XodrTree(xodr_text)
    pv = planview_digests(parsed)
    rl = road_link_digests(parsed)
    jc, ll = junction_digests(parsed)
    ls = lanesection_digests(parsed)
    el = elevation_digests(parsed)
    sec, sc_state = superelevation_crossfall_digests(parsed)
    rm, rm_state = roadmark_digests(parsed)
    cr, cr_state, cr_present = connector_repair_digests(parsed, repaired_junction_ids)
    h = hashlib.sha256()
    for name, lst in (("planview", pv), ("road_link", rl), ("junction", jc),
                      ("lanelink", ll), ("lanesection", ls), ("elevation", el),
                      ("superelevation_crossfall", sec), ("roadmark", rm),
                      ("connector_repair", cr)):
        h.update(name.encode("utf-8"))
        h.update(SEP.encode("utf-8"))
        h.update(_list_digest(lst).encode("utf-8"))
    combined = h.hexdigest()
    return {
        "schema": "phase_q/structural_digest/v13",
        "planview_digest": _list_digest(pv),
        "road_link_digest": _list_digest(rl),
        "junction_connection_digest": _list_digest(jc),
        "lanelink_digest": _list_digest(ll),
        "lanesection_digest": _list_digest(ls),
        "elevation_digest": _list_digest(el),
        "superelevation_crossfall_digest": _list_digest(sec),
        "superelevation_crossfall_state": sc_state,
        "roadmark_digest": _list_digest(rm),
        "roadmark_state": rm_state,
        "connector_repair_digest": _list_digest(cr),
        "connector_repair_state": cr_state,
        "connector_repair_present_ids": cr_present,
        "roads": len(parsed.findall("road")),
        "junctions": len(parsed.findall("junction")),
        "combined_structural_digest": combined,
    }
