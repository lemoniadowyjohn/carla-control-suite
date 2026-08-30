from __future__ import annotations

import hashlib
import json
import math
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

Point = Tuple[float, float]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _geom_end(geom: ET.Element) -> Tuple[float, float, float]:
    x = float(geom.attrib["x"])
    y = float(geom.attrib["y"])
    hdg = float(geom.attrib["hdg"])
    length = float(geom.attrib["length"])

    if geom.find("line") is not None:
        return x + length * math.cos(hdg), y + length * math.sin(hdg), hdg

    pp = geom.find("paramPoly3")
    if pp is None:
        return x, y, hdg

    a_u = float(pp.attrib.get("aU", "0"))
    b_u = float(pp.attrib.get("bU", "0"))
    c_u = float(pp.attrib.get("cU", "0"))
    d_u = float(pp.attrib.get("dU", "0"))
    a_v = float(pp.attrib.get("aV", "0"))
    b_v = float(pp.attrib.get("bV", "0"))
    c_v = float(pp.attrib.get("cV", "0"))
    d_v = float(pp.attrib.get("dV", "0"))
    p_range = pp.attrib.get("pRange", "normalized")

    p = 1.0 if p_range == "normalized" else length
    u = a_u + b_u * p + c_u * p * p + d_u * p * p * p
    v = a_v + b_v * p + c_v * p * p + d_v * p * p * p

    x_end = x + u * math.cos(hdg) - v * math.sin(hdg)
    y_end = y + u * math.sin(hdg) + v * math.cos(hdg)
    return x_end, y_end, hdg


def _road_endpoints(road: ET.Element) -> Tuple[Point, Point]:
    pv = road.find("planView")
    if pv is None:
        raise ValueError(f"road id={road.attrib.get('id')} has no planView")
    geoms = pv.findall("geometry")
    if not geoms:
        raise ValueError(f"road id={road.attrib.get('id')} has empty planView")
    g0 = geoms[0]
    start = (float(g0.attrib["x"]), float(g0.attrib["y"]))
    x_end, y_end, _ = _geom_end(geoms[-1])
    return start, (x_end, y_end)


def _is_unlinked_non_junction_road(road: ET.Element) -> bool:
    if road.attrib.get("junction", "-1") != "-1":
        return False
    link = road.find("link")
    if link is None:
        return True
    return not link.findall("predecessor") and not link.findall("successor")


def _has_junction_link(road: ET.Element, junction_id: str) -> bool:
    link = road.find("link")
    if link is None:
        return False
    for tag in ("predecessor", "successor"):
        for el in link.findall(tag):
            if el.attrib.get("elementType") == "junction" and el.attrib.get(
                "elementId"
            ) == str(junction_id):
                return True
    return False


def patch_junction_links(
    in_xodr: Path,
    out_xodr: Path,
    report_json: Path,
    tolerance_m: float = 5.0,
) -> dict:
    in_xodr = Path(in_xodr).expanduser().resolve()
    out_xodr = Path(out_xodr).expanduser().resolve()
    report_json = Path(report_json).expanduser().resolve()

    tree = ET.parse(in_xodr)
    root = tree.getroot()

    roads: Dict[str, ET.Element] = {}
    for road in root.findall("road"):
        road_id = road.attrib.get("id")
        if road_id is not None:
            roads[road_id] = road
    junctions = root.findall("junction")

    missing_link_roads_non_junction_before = sum(
        1 for r in roads.values() if _is_unlinked_non_junction_road(r)
    )

    endpoints: Dict[str, Dict[str, Point]] = {}
    for rid, road in roads.items():
        start, end = _road_endpoints(road)
        endpoints[rid] = {"start": start, "end": end}

    def _connect_point(connecting_road_id: str, contact_point: str) -> Optional[Point]:
        ep = endpoints.get(connecting_road_id)
        if ep is None:
            return None
        if contact_point == "end":
            return ep["end"]
        return ep["start"]

    incoming_to_junctions: Dict[str, set[str]] = {}
    incoming_referenced: set[str] = set()
    connection_records: List[dict] = []
    for junction in junctions:
        junction_id = str(junction.attrib.get("id", "")).strip()
        if not junction_id:
            continue
        for conn in junction.findall("connection"):
            incoming = conn.attrib.get("incomingRoad")
            connecting = conn.attrib.get("connectingRoad")
            contact_point = conn.attrib.get("contactPoint", "start")
            if not incoming or not connecting:
                continue
            incoming = str(incoming)
            incoming_referenced.add(incoming)
            incoming_to_junctions.setdefault(incoming, set()).add(junction_id)
            connection_records.append(
                {
                    "junction_id": junction_id,
                    "incoming_road": incoming,
                    "connecting_road": str(connecting),
                    "contactPoint": str(contact_point),
                }
            )

    missing_before_ids: List[str] = []
    for incoming_id in sorted(incoming_referenced):
        road = roads.get(incoming_id)
        if road is None:
            continue
        needed = incoming_to_junctions.get(incoming_id, set())
        if any(not _has_junction_link(road, jid) for jid in needed):
            missing_before_ids.append(incoming_id)

    changes: List[dict] = []
    suspicious: List[dict] = []
    conflicts: List[dict] = []
    for rec in connection_records:
        junction_id = rec["junction_id"]
        incoming = rec["incoming_road"]
        connecting = rec["connecting_road"]
        contact_point = rec["contactPoint"]

        pt = _connect_point(connecting, contact_point)
        if pt is None:
            continue

        road = roads.get(incoming)
        if road is None:
            continue

        link = road.find("link")
        if link is None:
            link = ET.SubElement(road, "link")

        if _has_junction_link(road, junction_id):
            continue

        ep = endpoints[incoming]
        d_start = _dist(ep["start"], pt)
        d_end = _dist(ep["end"], pt)

        if min(d_start, d_end) > float(tolerance_m):
            suspicious.append(
                {
                    "junction_id": junction_id,
                    "incoming_road": incoming,
                    "connecting_road": connecting,
                    "contactPoint": contact_point,
                    "d_start": d_start,
                    "d_end": d_end,
                    "tolerance_m": float(tolerance_m),
                }
            )

        if d_end <= d_start:
            slot, tag = "successor", "successor"
        else:
            slot, tag = "predecessor", "predecessor"

        # A road may have at most one predecessor and one successor in valid
        # OpenDRIVE. If the target slot is already occupied (e.g. by a link
        # to a plain road, or to a different junction), blindly appending a
        # second <predecessor>/<successor> element would produce an invalid,
        # ambiguous document instead of a fix. Record the conflict and leave
        # the existing link untouched rather than silently corrupting it.
        existing = link.find(tag)
        if existing is not None:
            conflicts.append(
                {
                    "road_id": incoming,
                    "junction_id": junction_id,
                    "slot": slot,
                    "existing_element_type": existing.attrib.get("elementType"),
                    "existing_element_id": existing.attrib.get("elementId"),
                }
            )
            continue

        new_el = ET.SubElement(link, tag)
        new_el.attrib = {
            "elementType": "junction",
            "elementId": junction_id,
            "contactPoint": "start" if tag == "successor" else "end",
        }
        changes.append({"road_id": incoming, "junction_id": junction_id, "added": tag})

    missing_after_ids: List[str] = []
    for incoming_id in sorted(incoming_referenced):
        road = roads.get(incoming_id)
        if road is None:
            continue
        needed = incoming_to_junctions.get(incoming_id, set())
        if any(not _has_junction_link(road, jid) for jid in needed):
            missing_after_ids.append(incoming_id)

    remaining_unlinked_nonjunction_ids = sorted(
        rid for rid, road in roads.items() if _is_unlinked_non_junction_road(road)
    )

    out_xodr.parent.mkdir(parents=True, exist_ok=True)
    input_sha = _sha256_file(in_xodr)

    added_junction_links = len(changes)
    if added_junction_links > 0:
        tree.write(out_xodr, encoding="UTF-8", xml_declaration=True)
    else:
        shutil.copy2(in_xodr, out_xodr)

    output_sha = _sha256_file(out_xodr)
    report_json.parent.mkdir(parents=True, exist_ok=True)

    output_rel = str(Path(out_xodr).resolve())
    try:
        output_rel = str(
            Path(out_xodr).resolve().relative_to(report_json.parent.resolve())
        )
    except Exception:
        output_rel = str(out_xodr)

    notes: List[str] = []
    if added_junction_links > 0:
        notes.append(f"Added {added_junction_links} missing road-to-junction link(s).")
    else:
        notes.append("No missing road-to-junction links were added.")
    if missing_after_ids:
        notes.append(
            f"{len(missing_after_ids)} road(s) still missing required junction links after patch."
        )
    if conflicts:
        notes.append(
            f"{len(conflicts)} road(s) had a junction link that could not be added because "
            "the predecessor/successor slot was already occupied by a different link."
        )

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "roads_total": int(len(roads)),
        "junctions_total": int(len(junctions)),
        "added_junction_links": int(added_junction_links),
        "missing_road_to_junction_links_before": int(len(missing_before_ids)),
        "missing_road_to_junction_links_after": int(len(missing_after_ids)),
        "remaining_unlinked_nonjunction_roads": int(
            len(remaining_unlinked_nonjunction_ids)
        ),
        "suspicious_matches": suspicious,
        "link_slot_conflicts": conflicts,
        "notes": notes,
        # Legacy keys kept for backward compatibility.
        "missing_link_roads_non_junction_before": int(
            missing_link_roads_non_junction_before
        ),
        "junction_link_additions": int(added_junction_links),
        "remaining_unlinked_incoming_roads": int(len(missing_after_ids)),
        "remaining_unlinked_roads_non_junction": int(
            len(remaining_unlinked_nonjunction_ids)
        ),
        "remaining_unlinked_incoming_road_ids": missing_after_ids,
        "remaining_unlinked_road_ids_non_junction": remaining_unlinked_nonjunction_ids,
        "output_xodr_path": output_rel,
        "input_xodr_sha256": input_sha,
        "output_xodr_sha256": output_sha,
        "modified": bool(added_junction_links > 0),
        "source_xodr_path": str(in_xodr),
    }

    report_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def patch_xodr_junction_links(
    in_xodr: Path,
    out_xodr: Path,
    report_json: Path,
    tolerance_m: float = 5.0,
) -> dict:
    """Compatibility alias for older callers."""
    return patch_junction_links(
        in_xodr=in_xodr,
        out_xodr=out_xodr,
        report_json=report_json,
        tolerance_m=tolerance_m,
    )


__all__ = ["patch_junction_links", "patch_xodr_junction_links"]
