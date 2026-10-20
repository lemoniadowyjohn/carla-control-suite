# -*- coding: utf-8 -*-
"""RQ1 structural signature — versioned identity of the network STRUCTURE.

Version: ``rq1-structural-signature/v1``

Clear, non-aliased construction (never a generic report hash): a canonical
JSON payload is built solely from frozen structural / topological fields of
the OpenDRIVE document and hashed with SHA256:

  * road identities and count (id, junction attribute);
  * junction identities and count (id, per-junction connections:
    incoming road, connecting road, contact point, lane links);
  * lane topology / connectivity: explicit predecessor/successor road
    links, per-lane-section left/right lane id sets and lane types;
  * lane-section structure: per-road lane-section records (s position,
    lane id sets) and per-lane width-record digests (lane widths are part
    of the frozen lane-section structure; recorded as a sub-digest so the
    payload stays compact but any width/offset change is detected);
  * relevant feature counts: signal and object counts per road.

Deterministic: parsed (never byte-compared), traversal is document order
with stable canonical key ordering at payload level.

Scientifically documented exclusions (with justification):
  * planView/elevationProfile geometry numerics — geometry is the
    normalization/geometry domain (covered by the RQ1 normalized XODR
    identity and RQ2 curvature metrics), not network structure;
  * road ``name`` attributes — textual labeling metadata, not structure
    (a name-only change is captured by the normalized identity);
  * administrative attributes unrelated to the road network (e.g.
    ``geometryFreezeHash``) — provenance bookkeeping, not structure.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

import xml.etree.ElementTree as ET

STRUCTURAL_SIGNATURE_VERSION = "rq1-structural-signature/v1"


def _sha256_list(records: List[Any]) -> str:
    """Digest of a canonical list of value tuples (strings kept verbatim)."""
    payload = "\x1f".join(
        "\x1e".join(str(v) for v in record) for record in records
    ).encode("utf-8", "replace")
    return hashlib.sha256(payload).hexdigest()


def _link_record(link_elem: Optional[ET.Element]) -> List[Any]:
    if link_elem is None:
        return []
    recs: List[Any] = []
    for tag in ("predecessor", "successor"):
        sub = link_elem.find(tag)
        if sub is None:
            continue
        recs.append(
            [
                tag,
                sub.attrib.get("elementType", ""),
                sub.attrib.get("elementId", ""),
                sub.attrib.get("contactPoint", ""),
            ]
        )
    return recs


def _lane_section_record(section: ET.Element) -> Dict[str, Any]:
    def lane_side(side_tag: str) -> Dict[str, Any]:
        side = section.find(side_tag)
        if side is None:
            return {"count": 0, "lane_ids": [], "lane_types": [], "width_digest": None}
        lanes = side.findall("lane")
        width_records: List[List[Any]] = []
        lane_types: List[str] = []
        for lane in lanes:
            lane_types.append(lane.attrib.get("type", ""))
            for w in lane.findall("width"):
                width_records.append(
                    [
                        w.attrib.get("sOffset", ""),
                        w.attrib.get("a", ""),
                        w.attrib.get("b", ""),
                        w.attrib.get("c", ""),
                        w.attrib.get("d", ""),
                    ]
                )
            for w in lane.findall("laneWidth"):
                width_records.append(
                    [
                        "laneWidth",
                        w.attrib.get("sOffset", ""),
                        w.attrib.get("a", ""),
                        w.attrib.get("b", ""),
                        w.attrib.get("c", ""),
                        w.attrib.get("d", ""),
                    ]
                )
        return {
            "count": len(lanes),
            "lane_ids": [lane.attrib.get("id", "") for lane in lanes],
            "lane_types": lane_types,
            "width_digest": _sha256_list(width_records) if width_records else None,
        }

    return {
        "s": section.attrib.get("s", ""),
        "left": lane_side("left"),
        "center": lane_side("center"),
        "right": lane_side("right"),
    }


def _road_record(road: ET.Element) -> Dict[str, Any]:
    lanes = road.find("lanes")
    sections: List[Dict[str, Any]] = []
    if lanes is not None:
        sections = [_lane_section_record(s) for s in lanes.findall("laneSection")]
    signals = road.find("signals")
    objects = road.find("objects")
    return {
        "id": road.attrib.get("id", ""),
        "junction": road.attrib.get("junction", ""),
        "links": _link_record(road.find("link")),
        "lane_sections": sections,
        "feature_counts": {
            "signals": len(signals.findall("signal")) if signals is not None else 0,
            "objects": len(objects.findall("object")) if objects is not None else 0,
        },
    }


def _junction_record(junction: ET.Element) -> Dict[str, Any]:
    connections: List[Dict[str, Any]] = []
    for conn in junction.findall("connection"):
        ll: Dict[str, List[Any]] = {}
        for attr_tag in ("laneLink",):
            for contact in conn.findall(attr_tag):
                for side in ("from", "to"):
                    links = contact.findall(side)
                    ll.setdefault(side, []).extend(
                        [
                            [link.attrib.get("from", ""), link.attrib.get("to", "")]
                            for link in links
                        ]
                    )
        connections.append(
            {
                "id": conn.attrib.get("id", ""),
                "incomingRoad": conn.attrib.get("incomingRoad", ""),
                "connectingRoad": conn.attrib.get("connectingRoad", ""),
                "contactPoint": conn.attrib.get("contactPoint", ""),
                "laneLinks": ll,
            }
        )
    connections.sort(
        key=lambda c: (
            c["incomingRoad"],
            c["connectingRoad"],
            c["contactPoint"],
            c["id"],
        )
    )
    return {
        "id": junction.attrib.get("id", ""),
        "type": junction.attrib.get("type", ""),
        "connections": connections,
    }


def build_structural_payload(path: str | Path) -> Dict[str, Any]:
    """Build the structural payload (canonical dict) from an XODR file."""
    path = Path(path)
    root = ET.fromstring(path.read_bytes())

    roads = sorted(
        [_road_record(r) for r in root.findall("road")], key=lambda r: _id_key(r["id"])
    )
    junctions = sorted(
        [_junction_record(j) for j in root.findall("junction")], key=lambda j: _id_key(j["id"])
    )
    return {
        "signature_version": STRUCTURAL_SIGNATURE_VERSION,
        "road_count": len(roads),
        "roads": roads,
        "junction_count": len(junctions),
        "junctions": junctions,
    }


def _id_key(raw: str) -> Tuple[int, Any]:
    try:
        return (0, int(raw))
    except ValueError:
        return (1, str(raw))


def _canon(obj: Any) -> bytes:
    import json

    return json.dumps(obj, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode(
        "utf-8"
    )


def compute_structural_signature(path: str | Path, store_payload: Optional[str | Path] = None) -> Dict[str, Any]:
    """Compute the versioned structural signature of an XODR file.

    Returns ``{version, sha256, road_count, junction_count}`` plus, when
    ``store_payload`` is given, ``payload_path``/``payload_sha256`` for
    divergence forensics.
    """
    payload = build_structural_payload(path)
    canonical = _canon(payload)
    sha = hashlib.sha256(canonical).hexdigest()
    out = {
        "version": STRUCTURAL_SIGNATURE_VERSION,
        "sha256": sha,
        "road_count": payload["road_count"],
        "junction_count": payload["junction_count"],
    }
    if store_payload is not None:
        p = Path(store_payload)
        p.write_text(
            _canon(payload).decode("utf-8") + "\n", encoding="utf-8"
        )
        out["payload_path"] = str(p)
        out["payload_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def structural_rules() -> Dict[str, Any]:
    """Machine-readable field description embedded in receipts."""
    return {
        "version": STRUCTURAL_SIGNATURE_VERSION,
        "included": [
            "road ids + count",
            "road junction attribute",
            "road predecessor/successor links",
            "lane sections (s, left/center/right lane id sets + types)",
            "per-lane width/laneWidth record digests (exact value strings)",
            "junction ids + count",
            "junction connections (incoming/connecting road, contact point,"
            " lane link from/to)",
            "signal/object counts per road",
        ],
        "excluded_documented": [
            "planView/elevationProfile geometry numerics (geometry domain;"
            " covered by normalized XODR identity + RQ2 curvature metrics)",
            "road name attributes (textual labeling, not structure)",
            "provenance bookkeeping attributes (e.g. geometryFreezeHash)",
        ],
    }
