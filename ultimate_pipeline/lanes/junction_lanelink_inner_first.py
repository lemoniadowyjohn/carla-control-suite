"""GAP-026 generator-stage repair: junction laneLink inner-first remapping.

Earliest proven bad stage: the junction ``<laneLink>`` sets arrive from the
SUMO netconvert import and are never regenerated.  Stage 8 is VALIDATION_ONLY
for lane topology (GAP-048 closure), and no ``LaneLinkBuilder.regenerate``
call runs anywhere in the pipeline, so SUMO's outer->inner mispairs survive to
the final map.  On a lane-count-reduction connection (e.g. incoming 3 driving
lanes -> connecting 2) SUMO pairs the *outer* incoming lane to the *inner*
connecting lane, producing a lateral endpoint error of several metres while the
reference-line endpoints themselves coincide (``ref_gap == 0.0``).  Width is not
the cause: the paired lanes already share an identical ``<width @a>``.

DETERMINISTIC INNER-FIRST MAPPING RULE
=====================================
For each junction connection ``C = (junction, conn id, incomingRoad I,
connectingRoad K, contactPoint P)``:

1. Interface lane sets (production checker's authority):
   - ``INC`` = driving lane ids at the END section of ``I``
     (incoming always uses ``end``; OpenDRIVE junction semantics).
   - ``CON`` = driving lane ids at the section of ``K`` selected by ``P``
     (``start`` if ``contactPoint=start``, else ``end``).

2. Deterministic sort contract (the only ordering used; no XML element order):
   - Partition by sign into ``INC+``, ``INC-``, ``CON+``, ``CON-``.
   - Within each partition sort by ``|id|`` ascending
     (inner-first: ``|1| < |2| < ...``; lane ids are unique within a
     section-side, so this is a strict total order).

3. Canonical inner-first candidate ``B``:
   ``B = zip(INC+, CON+) ++ zip(INC-, CON-)``.
   ``zip`` truncates to the shorter list, so inner lanes pair first and any
   surplus *outer* incoming lane is left unlinked (it has no legal target;
   the road narrows through the junction).

4. Per-remap topological legality (proved structurally, per pair ``(f, t)``):
   - ``f ∈ INC``: exists as a driving lane on the incoming end section.
   - ``t ∈ CON``: exists as a driving lane on the connecting interface section.
   - ``sign(f) == sign(t)``: right-to-right or left-to-left, never crossing.
   - Injective: lane ids are unique per section-side and ``zip`` is monotone in
     rank, so no two pairs share a ``from`` or a ``to``.
   - No invalid targets are constructible: every ``to`` is drawn from ``CON``.

5. Selection between candidate ``A`` (original links) and ``B`` (inner-first):
   ``score(X)`` = number of links in ``X`` that fail the production checker's
   endpoint-continuity test (``dist > 0.25 m`` OR ``heading > 12 deg``) -- the
   *existing* tolerances, unchanged.  Apply ``B`` (positive construction:
   replace ``A`` with the full ``B`` set) iff ``score(B) < score(A)``; ties keep
   ``A``; an empty ``B`` never replaces a non-empty ``A`` (no zero-laneLink
   regression).  Regression-freedom is structural: the chosen set never has
   more failing links than the original for that connection.

6. Determinism: junctions and connections are iterated in a numeric-aware
   sorted order; emitted laneLinks are sorted by ``(sign, |id|)``.  The output
   is a pure function of the input bytes.

This is POSITIVE construction (it writes the complete inner-first link set),
never destructive pruning.  It never removes a link without writing the
canonical replacement that the mispair was displacing, so it cannot leave a
connection with fewer links than the inner-first pairing requires.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

# Production checker tolerances (stage_08_integrity.sanitize_junction_lane_links
# defaults).  Reused verbatim for candidate scoring; NOT modified here.
POSITION_TOLERANCE_M = 0.25
HEADING_TOLERANCE_RAD = math.radians(12.0)

DRIVING_TYPES = {"driving"}


def _safe_float(raw: Any, default: float = 0.0) -> float:
    try:
        return float(str(raw).strip())
    except Exception:
        return default


def _sort_key_id_str(raw: Any) -> Tuple[int, str]:
    """Numeric-aware sort key for junction/connection ids."""
    s = str(raw)
    try:
        return (0, f"{int(s):012d}")
    except Exception:
        return (1, s)


def _edge_section(road: ET.Element, at_start: bool) -> Optional[ET.Element]:
    sections = sorted(
        road.findall("./lanes/laneSection"),
        key=lambda s: _safe_float(s.get("s"), 0.0),
    )
    if not sections:
        return None
    return sections[0] if at_start else sections[-1]


def _driving_ids(section: ET.Element, side: str) -> List[int]:
    side_elem = section.find(side)
    if side_elem is None:
        return []
    out: List[int] = []
    for lane in side_elem.findall("lane"):
        try:
            lid = int(str(lane.get("id")))
        except (TypeError, ValueError):
            continue
        if str(lane.get("type", "driving")).lower() not in DRIVING_TYPES:
            continue
        out.append(lid)
    return out


def _edge_pose(road: ET.Element, at_start: bool) -> Optional[Tuple[float, float, float]]:
    from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint, pose_at_s

    geoms = sorted(
        road.findall("./planView/geometry"),
        key=lambda g: _safe_float(g.get("s"), 0.0),
    )
    if not geoms:
        return None
    p = pose_at_s(geoms[0], 0.0) if at_start else endpoint(geoms[-1])
    return float(p.x), float(p.y), float(p.heading)


def _lane_center(
    road: ET.Element, lane_id: int, at_start: bool
) -> Optional[Tuple[float, float, float]]:
    """Lane-center world pose at the interface edge (checker's authority)."""
    base = _edge_pose(road, at_start)
    if base is None:
        return None
    section = _edge_section(road, at_start)
    if section is None:
        return None
    side = section.find("left" if lane_id > 0 else "right")
    if side is None:
        return None
    lanes = sorted(
        (l for l in side.findall("lane") if str(l.get("type", "driving")).lower() in DRIVING_TYPES),
        key=lambda l: abs(int(str(l.get("id", 0)))),
    )
    sel = next((l for l in lanes if int(str(l.get("id", 0))) == lane_id), None)
    if sel is None:
        return None
    width = sel.find("./width")
    if width is None:
        return None
    try:
        lane_width = float(width.get("a"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lane_width) or lane_width <= 0:
        return None
    preceding = 0.0
    for l in lanes:
        if abs(int(str(l.get("id", 0)))) >= abs(lane_id):
            continue
        pw = l.find("./width")
        if pw is not None:
            try:
                preceding += float(pw.get("a", "0"))
            except (TypeError, ValueError):
                pass
    lateral = (preceding + lane_width / 2.0) * (1 if lane_id > 0 else -1)
    x, y, heading = base
    return x - math.sin(heading) * lateral, y + math.cos(heading) * lateral, heading


def _link_fails(
    inc: ET.Element,
    con: ET.Element,
    from_id: int,
    to_id: int,
    at_start: bool,
    pos_tol: float = POSITION_TOLERANCE_M,
    head_tol: float = HEADING_TOLERANCE_RAD,
) -> bool:
    """Endpoint-continuity test, identical to the production checker."""
    src = _lane_center(inc, from_id, False)
    tgt = _lane_center(con, to_id, at_start)
    if src is None or tgt is None:
        return True
    heading_target = tgt[2] + (0 if at_start else math.pi)
    dist = math.hypot(src[0] - tgt[0], src[1] - tgt[1])
    ang = abs((src[2] - heading_target + math.pi) % (2 * math.pi) - math.pi)
    return not (dist <= pos_tol and ang <= head_tol)


def _inner_first_pairs(inc_ids: List[int], con_ids: List[int]) -> List[Tuple[int, int]]:
    """Deterministic inner-first pairing per the sort contract (rule step 2-3)."""
    inc_pos = sorted([i for i in inc_ids if i > 0], key=abs)
    con_pos = sorted([c for c in con_ids if c > 0], key=abs)
    inc_neg = sorted([i for i in inc_ids if i < 0], key=abs)
    con_neg = sorted([c for c in con_ids if c < 0], key=abs)
    return list(zip(inc_pos, con_pos)) + list(zip(inc_neg, con_neg))


def _sort_pairs(pairs: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Emit order: positive side then negative side, each by |id| ascending."""
    pos = sorted([p for p in pairs if p[0] > 0], key=lambda p: abs(p[0]))
    neg = sorted([p for p in pairs if p[0] < 0], key=lambda p: abs(p[0]))
    return pos + neg


def repair_outer_to_inner_mispaired_lane_links(
    root: ET.Element, verbose: bool = False
) -> Dict[str, Any]:
    """Apply the deterministic inner-first laneLink rule at the source stage.

    Positive construction only: a connection is rewritten iff the inner-first
    set strictly reduces failing links under the production checker's own
    tolerances, and an empty inner-first set never replaces a non-empty
    original.  Returns a report dict.
    """
    roads = {str(r.get("id")): r for r in root.findall("road") if r.get("id")}

    remapped = 0
    kept = 0
    evaluated = 0
    links_before = 0
    links_after = 0
    remap_log: List[Dict[str, Any]] = []

    junctions = sorted(root.findall("junction"), key=lambda j: _sort_key_id_str(j.get("id")))
    for junc in junctions:
        conns = sorted(junc.findall("connection"), key=lambda c: _sort_key_id_str(c.get("id")))
        for conn in conns:
            inc = roads.get(str(conn.get("incomingRoad")))
            con = roads.get(str(conn.get("connectingRoad")))
            if inc is None or con is None:
                continue
            at_start = conn.get("contactPoint", "start") != "end"
            inc_sec = _edge_section(inc, False)
            con_sec = _edge_section(con, at_start)
            if inc_sec is None or con_sec is None:
                continue

            inc_ids = _driving_ids(inc_sec, "left") + _driving_ids(inc_sec, "right")
            con_ids = _driving_ids(con_sec, "left") + _driving_ids(con_sec, "right")
            if not inc_ids or not con_ids:
                continue

            original: List[Tuple[int, int]] = []
            for ll in conn.findall("laneLink"):
                try:
                    original.append((int(str(ll.get("from"))), int(str(ll.get("to")))))
                except (TypeError, ValueError):
                    continue
            if not original:
                continue

            con_abs = set(abs(c) for c in con_ids)
            has_oi = any(
                abs(f) not in con_abs
                and (
                    (f < 0 and t < 0 and abs(f) > abs(t))
                    or (f > 0 and t > 0 and abs(f) > abs(t))
                )
                for f, t in original
            )
            if not has_oi:
                continue

            evaluated += 1
            links_before += len(original)

            candidate = _inner_first_pairs(inc_ids, con_ids)
            if not candidate:
                # Rule step 5: empty inner-first never replaces a non-empty original
                # (no zero-laneLink regression).
                kept += 1
                links_before += 0
                continue

            orig_fails = sum(1 for f, t in original if _link_fails(inc, con, f, t, at_start))
            cand_fails = sum(1 for f, t in candidate if _link_fails(inc, con, f, t, at_start))

            if cand_fails < orig_fails:
                new_pairs = _sort_pairs(candidate)
                for ll in list(conn.findall("laneLink")):
                    conn.remove(ll)
                for f, t in new_pairs:
                    ET.SubElement(conn, "laneLink", {"from": str(f), "to": str(t)})
                remapped += 1
                links_after += len(new_pairs)
                remap_log.append(
                    {
                        "junction": junc.get("id"),
                        "connection": conn.get("id"),
                        "incomingRoad": conn.get("incomingRoad"),
                        "connectingRoad": conn.get("connectingRoad"),
                        "contactPoint": "start" if at_start else "end",
                        "inc_ids": sorted(inc_ids),
                        "con_ids": sorted(con_ids),
                        "orig_fails": orig_fails,
                        "cand_fails": cand_fails,
                        "orig_pairs": sorted(original),
                        "new_pairs": new_pairs,
                    }
                )
            else:
                kept += 1
                links_after += len(original)

    report = {
        "remapped_connections": remapped,
        "kept_connections": kept,
        "evaluated_connections": evaluated,
        "links_before": links_before,
        "links_after": links_after,
        "tolerances": {
            "position_tolerance_m": POSITION_TOLERANCE_M,
            "heading_tolerance_rad": HEADING_TOLERANCE_RAD,
        },
        "remap_log": remap_log,
    }
    if verbose:
        print(
            f"[inner-first laneLink] evaluated={evaluated} "
            f"remapped={remapped} kept={kept} "
            f"links {links_before}->{links_after}"
        )
    return report
