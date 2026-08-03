#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H2 — governed signal/controller enrichment writers (Phase H).

Replaces the legacy heuristic <speed> layer (unprovenanced, m/s noise) with
governed writers per H1-H4:

- H1 provenance: every emitted element carries userData vectors with the
  source OSM way id, governing tag, method (GROUNDED/INFERRED), confidence
  and writer version.
- H2 modes: GROUNDED (explicit maxspeed / traffic_sign tags) versus
  INFERRED (maxspeed:type zone default) are separated in provenance.
- H3 idempotency: deterministic element ids derived from the OSM way id and
  existence checks; running the writers twice on the same file is a no-op.
- H4 native signal layer: <signal> elements with the OpenDRIVE Germany
  country catalog (type 1 = speed limit, type 2 = speed-limit zone),
  plus per-lane <speed> records (OpenDRIVE default unit m/s, matching the
  CARLA importer expectation), plus turn:lanes userData.

Controllers: no OSM node in the source carries traffic_signals/stop/give_way
tags, so the <controller>/<control> layer is requested=0 and reported N/A.

Conflict policy: when two OSM ways with different speeds map to the same
road, the way with the most matched nodes wins; the loser is recorded as a
rejected conflict.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

WRITER_VERSION = "phase_h2_signal_writer.py/1"
SIGNAL_COUNTRY = "DEU"
SPEED_LIMIT_TYPE = "1"
ZONE_SIGN_TYPE = "2"
ZONE_SIGN_SPEED = {"240": 30, "245": 50, "239": None}


# ---------------------------------------------------------------------------
# element placement helpers
# ---------------------------------------------------------------------------

def _road_length(road: ET.Element) -> float:
    try:
        return float(road.get("length", "0"))
    except Exception:
        return 0.0


def _ensure_signals(road: ET.Element) -> ET.Element:
    sig = road.find("signals")
    if sig is not None:
        return sig
    sig = ET.SubElement(road, "signals")
    for anchor in ("objects", "lanes"):
        a = road.find(anchor)
        if a is not None:
            road.remove(sig)
            idx = list(road).index(a) + 1
            road.insert(idx, sig)
            break
    return sig


def _ensure_userdata(road: ET.Element) -> ET.Element:
    ud = road.find("userData")
    if ud is None:
        ud = ET.SubElement(road, "userData")
    return ud


def _has_vector(ud: ET.Element, key: str, value: Optional[str] = None) -> bool:
    for v in ud.findall("vector"):
        if v.get("key") != key:
            continue
        if value is None or v.get("value") == value:
            return True
    return False


def _provenance_vectors(
    way_id: str, tags: Dict[str, str], method: str, confidence: float,
    reason: str,
) -> List[Tuple[str, str]]:
    vec = [
        ("osm:way", way_id),
        ("osm:source_tag", reason),
        ("enrichment:method", method),
        ("enrichment:confidence", f"{confidence:.2f}"),
        ("enrichment:writer", WRITER_VERSION),
    ]
    for k, v in sorted(tags.items()):
        if v is not None:
            vec.append((f"osm:tag:{k}", str(v)))
    return vec


def _add_provenance(parent: ET.Element, vectors: List[Tuple[str, str]]) -> None:
    ud = ET.SubElement(parent, "userData")
    for key, value in vectors:
        ET.SubElement(ud, "vector", key=key, value=value)


def _signal_id(kind: str, way_id: str, road_id: str) -> str:
    return f"h_{kind}_{way_id}_{road_id}"


# ---------------------------------------------------------------------------
# legacy layer replacement
# ---------------------------------------------------------------------------

def remove_legacy_speeds(root: ET.Element) -> int:
    """Remove the legacy heuristic <speed> records (no provenance)."""
    removed = 0
    for lane in root.findall(".//lane"):
        for speed in list(lane.findall("speed")):
            lane.remove(speed)
            removed += 1
    return removed


# ---------------------------------------------------------------------------
# speed limits
# ---------------------------------------------------------------------------

def _kmh_to_ms(kmh: int) -> str:
    return f"{kmh / 3.6:.3f}"


def _clamp_s(s: float, road: ET.Element) -> float:
    """Clamp into [0, length] with rounding-down so s never exceeds length."""
    length = _road_length(road)
    s = max(0.0, min(s, length))
    return math.floor(s * 1000.0) / 1000.0


def write_speed_limits(
    root: ET.Element,
    candidates: List[Dict[str, Any]],
    matches: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Write grounded speed limits per driving/restricted lane + <signal>."""
    counters = {
        "roads_updated": 0, "signals_inserted": 0, "speeds_inserted": 0,
        "conflicts_rejected": 0, "skipped_existing": 0,
    }
    road_by_id = {r.get("id"): r for r in root.findall("road")}

    # per-road aggregation with conflict resolution
    per_road: Dict[str, List[Dict[str, Any]]] = {}
    for m in matches:
        cand = candidates[m["candidate_idx"]]
        if cand["kind"] != "speed_limit":
            continue
        kmh = cand.get("speed_kmh")
        if not kmh:
            continue
        for rid in m["road_ids"]:
            per_road.setdefault(rid, []).append({
                "candidate": cand,
                "kmh": kmh,
                "s": m["s"],
                "t": m["t_center"],
                "votes": sum(m["node_votes"].values()),
                "way_id": cand["osm_way_id"],
            })

    for rid, entries in sorted(per_road.items()):
        road = road_by_id.get(rid)
        if road is None:
            continue
        entries.sort(key=lambda e: (-e["votes"], e["way_id"]))
        chosen = entries[0]
        for other in entries[1:]:
            if other["kmh"] != chosen["kmh"]:
                counters["conflicts_rejected"] += 1
        cand = chosen["candidate"]
        kmh = chosen["kmh"]
        s = _clamp_s(chosen["s"], road)
        t = chosen["t"]
        method = cand["method"]
        conf = cand["confidence"]
        reason = cand["reason"]
        sig_id = _signal_id("spd", chosen["way_id"], rid)
        sig = _ensure_signals(road)
        if any(s.get("id") == sig_id for s in sig.findall("signal")):
            counters["skipped_existing"] += 1
            continue
        ET.SubElement(sig, "signal", {
            "id": sig_id, "s": f"{s:.3f}", "t": f"{t:.3f}",
            "zOffset": "0.000", "hOffset": "0.000", "orientation": "+",
            "dynamic": "no", "type": SPEED_LIMIT_TYPE, "subtype": str(kmh),
            "country": SIGNAL_COUNTRY, "name": f"maxspeed {kmh}",
        })
        signal_el = sig.findall("signal")[-1]
        _add_provenance(signal_el, _provenance_vectors(
            chosen["way_id"], cand["tags"], method, conf, reason))
        counters["signals_inserted"] += 1

        for sec in road.findall("lanes/laneSection"):
            for lane in sec.findall(".//lane"):
                if lane.get("type") not in ("driving", "restricted"):
                    continue
                if lane.find("speed") is not None:
                    continue
                ET.SubElement(lane, "speed", max=_kmh_to_ms(kmh))
                counters["speeds_inserted"] += 1
        counters["roads_updated"] += 1
    return counters


# ---------------------------------------------------------------------------
# zone signs (DE:240 / DE:245 / DE:239) -> zone signal + zone speed
# ---------------------------------------------------------------------------

def write_zone_signs(
    root: ET.Element,
    candidates: List[Dict[str, Any]],
    matches: List[Dict[str, Any]],
) -> Dict[str, int]:
    counters = {
        "roads_updated": 0, "signals_inserted": 0, "speeds_inserted": 0,
        "skipped_existing": 0, "skipped_unprovenanced": 0,
        "skipped_duplicate": 0,
    }
    road_by_id = {r.get("id"): r for r in root.findall("road")}
    seen: Dict[tuple, int] = {}
    for m in matches:
        cand = candidates[m["candidate_idx"]]
        if cand["kind"] != "zone_sign":
            continue
        sign_code = cand["sign_code"]
        if not sign_code:
            counters["skipped_unprovenanced"] += 1
            continue
        zone_speed = ZONE_SIGN_SPEED.get(sign_code)
        for rid in m["road_ids"]:
            road = road_by_id.get(rid)
            if road is None:
                continue
            s = _clamp_s(m["s"], road)
            t = m["t_center"]
            dup_key = (rid, round(s, 1), round(t, 1), sign_code)
            if dup_key in seen:
                counters["skipped_duplicate"] += 1
                continue
            seen[dup_key] = 1
            sig_id = _signal_id("zone", cand["osm_way_id"], rid)
            sig = _ensure_signals(road)
            if any(s_el.get("id") == sig_id for s_el in sig.findall("signal")):
                counters["skipped_existing"] += 1
                continue
            ET.SubElement(sig, "signal", {
                "id": sig_id, "s": f"{s:.3f}", "t": f"{t:.3f}",
                "zOffset": "0.000", "hOffset": "0.000", "orientation": "+",
                "dynamic": "no", "type": ZONE_SIGN_TYPE, "subtype": sign_code,
                "country": SIGNAL_COUNTRY,
                "name": f"zone {sign_code}",
            })
            signal_el = sig.findall("signal")[-1]
            _add_provenance(signal_el, _provenance_vectors(
                cand["osm_way_id"], cand["tags"], cand["method"],
                cand["confidence"], cand["reason"]))
            counters["signals_inserted"] += 1
            if zone_speed is not None:
                for sec in road.findall("lanes/laneSection"):
                    for lane in sec.findall(".//lane"):
                        if lane.get("type") not in ("driving", "restricted"):
                            continue
                        if lane.find("speed") is not None:
                            continue
                        ET.SubElement(lane, "speed", max=_kmh_to_ms(zone_speed))
                        counters["speeds_inserted"] += 1
            counters["roads_updated"] += 1
    return counters


# ---------------------------------------------------------------------------
# turn lane metadata (userData; CARLA consumes no turn metadata today)
# ---------------------------------------------------------------------------

def write_turn_lanes(
    root: ET.Element,
    candidates: List[Dict[str, Any]],
    matches: List[Dict[str, Any]],
) -> Dict[str, int]:
    counters = {"roads_updated": 0, "rejected_lane_mismatch": 0,
                "skipped_existing": 0}
    road_by_id = {r.get("id"): r for r in root.findall("road")}
    for m in matches:
        cand = candidates[m["candidate_idx"]]
        if cand["kind"] != "turn_lanes":
            continue
        raw = cand["tags"].get("turn:lanes", "")
        if not raw:
            continue
        for rid in m["road_ids"]:
            road = road_by_id.get(rid)
            if road is None:
                continue
            ud = _ensure_userdata(road)
            key = f"turnLanes"
            if _has_vector(ud, key, raw):
                counters["skipped_existing"] += 1
                continue
            driving_ids = [
                lane.get("id")
                for sec in road.findall("lanes/laneSection")
                for lane in sec.findall(".//lane")
                if lane.get("type") in ("driving", "restricted")
            ]
            # right-side lanes: -1 (leftmost) .. -n (rightmost), left-to-right
            driving_ids = sorted(
                driving_ids, key=lambda i: int(i) if i is not None else 0)
            lanes_l2r = sorted(driving_ids, key=lambda i: int(i))
            turn_vals = [v.strip() for v in raw.split(";") if v.strip()]
            mapping = {}
            mismatch = False
            for i, val in enumerate(turn_vals):
                if i < len(lanes_l2r):
                    mapping[str(lanes_l2r[i])] = val
                else:
                    mismatch = True
            if mismatch:
                counters["rejected_lane_mismatch"] += 1
                continue
            if not _has_vector(ud, "turnLanes", raw):
                ET.SubElement(ud, "vector", key="turnLanes", value=raw)
            for lane in sorted(mapping, key=int):
                key = f"turnLane:{lane}"
                if not _has_vector(ud, key, mapping[lane]):
                    ET.SubElement(ud, "vector", key=key, value=mapping[lane])
            for key, value in _provenance_vectors(
                cand["osm_way_id"], cand["tags"], cand["method"],
                cand["confidence"], cand["reason"]):
                if not _has_vector(ud, key, value):
                    ET.SubElement(ud, "vector", key=key, value=value)
            counters["roads_updated"] += 1
    return counters
