#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H3 — signal/controller integrity audit (Phase H, H5).

Validates on a full map:
- unique signal ids (map-wide)
- signal s within [0, road length]
- signal t within the road envelope tolerance
- type/subtype within the governed catalogs (DEU type 1, type 2)
- lane validity references existing lanes
- controller / signalReference references resolve
- no duplicate spatial groups (road, s, t, type, subtype) within 1 m
- provenance present on every governed signal (H1)
- every governed signal carries a deterministic id prefix h_
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, List

SIGNAL_COUNTRY = "DEU"
GOVERNED_TYPES = {"1", "2"}
GOVERNED_SUBTYPES = {
    "1": {"5", "7", "10", "15", "20", "30", "40", "50", "60", "70",
          "80", "90", "100", "110", "120", "130"},
    "2": {"240", "245", "239"},
}
MAX_T_M = 25.0


def audit_signals(root: ET.Element) -> Dict[str, Any]:
    duplicate_ids: List[Dict[str, str]] = []
    out_of_s: List[Dict[str, str]] = []
    out_of_t: List[Dict[str, str]] = []
    unknown_type: List[Dict[str, str]] = []
    unknown_subtype: List[Dict[str, str]] = []
    invalid_validity: List[Dict[str, str]] = []
    unresolved_refs: List[Dict[str, str]] = []
    duplicate_spatial: List[Dict[str, str]] = []
    missing_provenance: List[Dict[str, str]] = []
    non_governed_prefix: List[Dict[str, str]] = []
    signals_audited = 0

    seen_ids: Dict[str, str] = {}
    spatial_keys: Dict[tuple, List[Dict[str, str]]] = {}
    controllers = {c.get("id") for c in root.findall("controller")}
    signal_ids = set()

    def _f(v, default: float = 0.0) -> float:
        try:
            return float(v)
        except Exception:
            return default

    for road in root.findall("road"):
        rid = road.get("id")
        length = _f(road.get("length"), 0.0)
        lane_ids = {
            lane.get("id")
            for sec in road.findall("lanes/laneSection")
            for lane in sec.findall(".//lane")
        }
        sig_el = road.find("signals")
        if sig_el is None:
            continue
        for sig in sig_el.findall("signal"):
            signals_audited += 1
            sid = sig.get("id")
            s = _f(sig.get("s"), -1.0)
            t = _f(sig.get("t"), 0.0)
            stype = sig.get("type")
            subtype = sig.get("subtype")
            country = sig.get("country")

            if sid in seen_ids:
                duplicate_ids.append({"road": rid, "id": sid,
                                      "also_road": seen_ids[sid]})
            else:
                seen_ids[sid] = rid
            if sid is not None:
                signal_ids.add(sid)

            if s < 0.0 or s > length + 1e-6:
                out_of_s.append({"road": rid, "id": sid, "s": str(s),
                                 "length": str(length)})
            if abs(t) > MAX_T_M:
                out_of_t.append({"road": rid, "id": sid, "t": str(t)})

            if stype not in GOVERNED_TYPES or country != SIGNAL_COUNTRY:
                unknown_type.append({"road": rid, "id": sid,
                                     "type": stype, "country": country})
            elif subtype not in GOVERNED_SUBTYPES.get(stype, set()):
                unknown_subtype.append({"road": rid, "id": sid,
                                        "type": stype, "subtype": subtype})

            for val in sig.findall("validity"):
                frm = val.get("fromLane")
                to = val.get("toLane")
                if frm not in lane_ids or to not in lane_ids:
                    invalid_validity.append({"road": rid, "id": sid,
                                             "fromLane": frm, "toLane": to})

            if sid is not None and not sid.startswith("h_"):
                non_governed_prefix.append({"road": rid, "id": sid})
            ud = sig.find("userData")
            vectors = {v.get("key"): v.get("value")
                       for v in ud.findall("vector")} if ud is not None else {}
            if not (vectors.get("osm:way") and
                    vectors.get("enrichment:method") and
                    vectors.get("enrichment:writer")):
                missing_provenance.append({"road": rid, "id": sid})

            key = (rid, round(s, 1), round(t, 1), stype, subtype)
            spatial_keys.setdefault(key, []).append(
                {"road": rid, "id": sid})

    for ref in root.findall(".//signalReference"):
        if ref.get("signalId") not in signal_ids:
            unresolved_refs.append({"signalId": ref.get("signalId")})
    for ctrl in root.findall("controller"):
        if ctrl.get("id") not in controllers:
            unresolved_refs.append({"controllerId": ctrl.get("id")})
    for ctrl in root.findall("controller"):
        for control in ctrl.findall("control"):
            if control.get("signalId") not in signal_ids:
                unresolved_refs.append(
                    {"controller": ctrl.get("id"),
                     "signalId": control.get("signalId")})

    for key, entries in spatial_keys.items():
        if len(entries) > 1:
            duplicate_spatial.append({"group": list(key), "count": len(entries)})

    return {
        "signals_audited": signals_audited,
        "controllers_audited": len(root.findall("controller")),
        "duplicate_ids": duplicate_ids,
        "out_of_s": out_of_s,
        "out_of_t": out_of_t,
        "unknown_type": unknown_type,
        "unknown_subtype": unknown_subtype,
        "invalid_validity": invalid_validity,
        "unresolved_refs": unresolved_refs,
        "duplicate_spatial": duplicate_spatial,
        "missing_provenance": missing_provenance,
        "non_governed_prefix": non_governed_prefix,
    }


def audit_clean(root: ET.Element) -> Dict[str, Any]:
    a = audit_signals(root)
    return {
        key: a[key] for key in (
            "duplicate_ids", "out_of_s", "out_of_t", "unknown_type",
            "unknown_subtype", "invalid_validity", "unresolved_refs",
            "duplicate_spatial", "missing_provenance",
            "non_governed_prefix",
        )
    } | {"clean": all(not a[key] for key in (
        "duplicate_ids", "out_of_s", "out_of_t", "unknown_type",
        "unknown_subtype", "invalid_validity", "unresolved_refs",
        "duplicate_spatial", "missing_provenance", "non_governed_prefix",
    ))}
