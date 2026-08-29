#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SIG-ENR-001 — provenance-backed, idempotent signal/controller enrichment.

Implements the enrichment contract:

- ENR-001: every enrichment carries its OSM/source entity, mapping confidence
  and the affected XODR element (road id, s, t) as inline provenance.
- ENR-002: ambiguous/unmapped source data is REJECTED, never guessed.
- ENR-003: enrichment is idempotent and duplicate-safe (re-running yields
  matched counts, not new signals).
- ENR-004: modes ``grounded`` / ``inferred`` / ``synthetic_debug`` are kept in
  separate result buckets; synthetic-debug records require explicit opt-in.
- ENR-005: every call reports requested, matched, inserted, updated,
  rejected, ambiguous counts per feature.
- SIG-001: signals use native OpenDRIVE ``<signal>``; controllers use native
  ``<controller>`` with ``<control>`` links; references use ``<signalReference>``.
- SIG-003: placement (s, t, zOffset, hOffset) is validated against the road
  before insertion; invalid placement is rejected, never clamped silently.
- SIG-005: duplicates are detected by source id and spatial grouping.
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

PROVENANCE_TAG = "provenance"
CONFIDENCES = ("grounded", "inferred", "synthetic_debug")
DEFAULT_MAX_T_M = 100.0


@dataclass
class SignalEnrichment:
    """One requested signal enrichment (ENR-001 payload)."""
    source_entity: str                      # OSM / authoritative source id
    confidence: str                         # grounded | inferred | synthetic_debug
    road_id: str
    s: float
    t: float
    signal_type: str = "1000001"            # OpenDRIVE default signal type
    subtype: str = "-1"
    dynamic: str = "no"
    z_offset: float = 5.0
    h_offset: float = 0.0
    controller_id: Optional[str] = None
    country: Optional[str] = None
    name: Optional[str] = None

    def __post_init__(self) -> None:
        if self.confidence not in CONFIDENCES:
            raise ValueError(f"confidence must be one of {CONFIDENCES}")

    def placement_key(self) -> Tuple[str, float, float]:
        """Spatial grouping key for SIG-005 duplicate detection."""
        return (self.road_id, round(self.s, 2), round(self.t, 2))


def _safe_float(value: Optional[str], default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except Exception:
        return default


def _road_length(road: ET.Element) -> float:
    return _safe_float(road.get("length"), 0.0)


def _ensure_signals_parent(road: ET.Element) -> ET.Element:
    signals = road.find("signals")
    if signals is None:
        signals = ET.SubElement(road, "signals")
    return signals


def _existing_signal_ids(road: ET.Element) -> Dict[str, ET.Element]:
    out: Dict[str, ET.Element] = {}
    signals = road.find("signals")
    if signals is None:
        return out
    for sig in signals.findall("signal"):
        if sig.get("id"):
            out[sig.get("id")] = sig
    return out


def _provenance_source(sig: ET.Element) -> Optional[str]:
    prov = sig.find(f"./userData/{PROVENANCE_TAG}")
    if prov is None:
        return None
    return prov.get("source_entity")


def _existing_provenance(road: ET.Element) -> Dict[str, ET.Element]:
    """Signals keyed by provenance source_entity (ENR-003 duplicate gate)."""
    out: Dict[str, ET.Element] = {}
    signals = road.find("signals")
    if signals is None:
        return out
    for sig in signals.findall("signal"):
        src = _provenance_source(sig)
        if src:
            out[src] = sig
    return out


def validate_placement(root: ET.Element, rec: SignalEnrichment, *, max_t_m: float = DEFAULT_MAX_T_M) -> Optional[str]:
    """SIG-003: reject placement outside the road; never clamp."""
    road = next((r for r in root.findall("road") if (r.get("id") or "") == rec.road_id), None)
    if road is None:
        return f"road_id {rec.road_id!r} not found"
    length = _road_length(road)
    if not (0.0 <= rec.s <= length + 1e-6):
        return f"s={rec.s:.3f} outside [0, {length:.3f}]"
    if abs(rec.t) > max_t_m:
        return f"|t|={abs(rec.t):.3f} exceeds max {max_t_m}"
    if not all(math.isfinite(v) for v in (rec.s, rec.t, rec.z_offset, rec.h_offset)):
        return "non-finite placement attributes"
    return None


def detect_duplicate_signals(root: ET.Element, *, spatial_radius_m: float = 3.0) -> Dict[str, Any]:
    """SIG-005: duplicates by source id (provenance) and spatial grouping."""
    duplicates: List[Dict[str, Any]] = []
    seen: Dict[str, List[ET.Element]] = {}
    for road in root.findall("road"):
        signals = road.find("signals")
        if signals is None:
            continue
        for sig in signals.findall("signal"):
            src = _provenance_source(sig)
            if src:
                seen.setdefault(src, []).append(sig)
    for src, sigs in seen.items():
        if len(sigs) > 1:
            duplicates.append({
                "source_entity": src,
                "count": len(sigs),
                "signal_ids": [s.get("id") for s in sigs],
                "kind": "source_id",
            })
    # spatial grouping: same road, s within radius
    for road in root.findall("road"):
        signals = road.find("signals")
        if signals is None:
            continue
        items = [(sig, _safe_float(sig.get("s"))) for sig in signals.findall("signal")]
        for i, (a, sa) in enumerate(items):
            for b, sb in items[i + 1:]:
                delta = abs(sa - sb)
                # NaN/Inf from a corrupted `s` attribute makes `delta` non-finite;
                # `nan <= spatial_radius_m` is always False in IEEE-754, so a
                # signal with a corrupted position would silently escape SIG-005
                # spatial-duplicate detection. Flag it for review instead.
                if not math.isfinite(delta) or delta <= spatial_radius_m:
                    duplicates.append({
                        "source_entity": "spatial",
                        "road_id": road.get("id"),
                        "a": a.get("id"), "b": b.get("id"),
                        "sa": sa, "sb": sb,
                        "kind": "spatial_grouping",
                    })
    return {"duplicate_groups": duplicates, "duplicate_count": len(duplicates)}


def _attach_provenance(signal: ET.Element, rec: SignalEnrichment) -> None:
    user_data = ET.SubElement(signal, "userData")
    ET.SubElement(user_data, PROVENANCE_TAG, {
        "source_entity": rec.source_entity,
        "confidence": rec.confidence,
        "road_id": rec.road_id,
        "s": f"{rec.s:.3f}",
        "t": f"{rec.t:.3f}",
    })


def _next_signal_id(road: ET.Element, existing: Dict[str, ET.Element]) -> str:
    taken = set(existing)
    idx = 1
    while f"{road.get('id')}_{idx}" in taken:
        idx += 1
    return f"{road.get('id')}_{idx}"


def _build_signal(road: ET.Element, rec: SignalEnrichment, signal_id: str) -> ET.Element:
    attrs = {
        "id": signal_id,
        "name": rec.name or f"src:{rec.source_entity}",
        "s": f"{rec.s:.3f}",
        "t": f"{rec.t:.3f}",
        "zOffset": f"{rec.z_offset:.2f}",
        "hOffset": f"{rec.h_offset:.3f}",
        "dynamic": rec.dynamic,
        "type": rec.signal_type,
        "subtype": rec.subtype,
    }
    if rec.country:
        attrs["country"] = rec.country
    signal = ET.SubElement(_ensure_signals_parent(road), "signal", attrs)
    if rec.controller_id:
        ET.SubElement(signal, "signalReference", {"id": rec.controller_id})
    _attach_provenance(signal, rec)
    return signal


def enrich_signals_idempotent(
    root: ET.Element,
    records: List[SignalEnrichment],
    *,
    allow_synthetic_debug: bool = False,
    max_t_m: float = DEFAULT_MAX_T_M,
) -> Dict[str, Any]:
    """ENR-003/004/005: idempotent, mode-separated, counting signal enrichment."""
    counts = {mode: {k: 0 for k in
                     ("requested", "matched", "inserted", "updated", "rejected", "ambiguous")}
              for mode in CONFIDENCES}
    for mode in ("grounded", "inferred"):
        counts[mode]["rejected"] = 0
    inserted_ids: List[str] = []
    rejected: List[Dict[str, Any]] = []

    for rec in records:
        mode = rec.confidence
        counts[mode]["requested"] += 1
        if mode == "synthetic_debug" and not allow_synthetic_debug:
            counts[mode]["rejected"] += 1
            rejected.append({"source_entity": rec.source_entity, "reason": "synthetic_debug_opt_in_required"})
            continue
        if rec.source_entity.startswith("?") or "unknown" in rec.source_entity.lower():
            counts[mode]["ambiguous"] += 1
            rejected.append({"source_entity": rec.source_entity, "reason": "ambiguous_source_entity"})
            continue
        problem = validate_placement(root, rec, max_t_m=max_t_m)
        if problem is not None:
            counts[mode]["rejected"] += 1
            rejected.append({"source_entity": rec.source_entity, "reason": f"invalid_placement: {problem}"})
            continue
        road = next(r for r in root.findall("road") if (r.get("id") or "") == rec.road_id)
        existing = _existing_provenance(road)
        if rec.source_entity in existing:
            counts[mode]["matched"] += 1
            continue
        signal = _build_signal(road, rec, _next_signal_id(road, _existing_signal_ids(road)))
        inserted_ids.append(signal.get("id"))
        counts[mode]["inserted"] += 1

    return {
        "rule": "ENR-001..005/SIG-001/SIG-003",
        "counts": counts,
        "inserted_signal_ids": inserted_ids,
        "rejected": rejected,
        "total_inserted": sum(counts[m]["inserted"] for m in CONFIDENCES),
        "total_rejected": sum(counts[m]["rejected"] for m in CONFIDENCES),
        "total_ambiguous": sum(counts[m]["ambiguous"] for m in CONFIDENCES),
        "total_matched": sum(counts[m]["matched"] for m in CONFIDENCES),
    }


# ------------------------------------------------------------- controllers
def build_controller(
    root: ET.Element,
    *,
    controller_id: str,
    name: str,
    signals: List[str],
    mode: str = "autonomous",
    cycle_time_s: float = 60.0,
) -> Dict[str, Any]:
    """SIG-001: native <controller> with <control> references to signal ids."""
    controllers = root.find("controller")
    if controllers is None:
        controllers = ET.SubElement(root, "controller")
    existing = {c.get("id") for c in controllers.findall("controller")}
    if controller_id in existing:
        return {"ok": True, "inserted": False, "reason": "already_present"}
    controller = ET.SubElement(controllers, "controller", {
        "id": controller_id,
        "name": name,
        "mode": mode,
        "cycleTime": f"{cycle_time_s:.1f}",
    })
    for sig_id in signals:
        ET.SubElement(controller, "control", {"signalId": sig_id, "type": "trafficLight"})
    return {"ok": True, "inserted": True, "controller_id": controller_id,
            "control_count": len(signals)}
