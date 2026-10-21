#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Unified Traffic Light Inference (CARLA 0.9.16 compatible)

This merges both:
    • TrafficLightInferer (direct XODR insertion)
    • TrafficLightInference (returns OSMObject list)

P0 signal authority hierarchy (signals/ENR mode contract):
    1. **OSM-first (grounded)**: `osm_traffic_signals:node/<id>` provenance,
       coordinates taken from real OSM traffic-signal/crossing-signal nodes
       (``highway=traffic_signals`` ``node`` elements, plus
       ``crossing=traffic_signals`` nodes) projected into the map's LOCAL
       frame via the same bare-tmerc transformer the building pipeline
       uses, minus the map's header <offset> rebase. ``confidence="grounded"``.
    2. **Heuristic fallback (inferred)**: legacy topology-only inference
       (>= 3 connections, non-roundabout). DISABLED by default; enable with
       UP_ENABLE_TL_HEURISTIC_FALLBACK=1 (or the allow_heuristic_fallback
       argument). Signals produced this way are ``confidence="inferred"``.

    With no OSM source and the fallback disabled, infer_and_insert() inserts
    ZERO signals rather than fabricating plausible-looking heuristic ones
    (2724/3561 heuristic junctions was the retired false-pass behavior).

Heuristics (fallback path only):
    - Junction has >= 3 connections
    - Junction NOT marked isRoundabout="true"
    - One TL per incoming road
    - TL placed ~5–7m before the junction center along road heading
"""

import math
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from ultimate_pipeline.core.xodr_sanitizer import _safe_float
from ultimate_pipeline.enrichment.object_injector import OSMObject
from ultimate_pipeline.signals.signal_enrichment import (
    SignalEnrichment,
    build_controller,
    enrich_signals_idempotent,
)

# OpenDRIVE 1.7 generic signal catalog: 1000001 = "Signal, traffic light"
# (the same code CARLA's OpenDRIVE importer keys off of to spawn a
# functional, controllable traffic light actor rather than a static prop).
TRAFFIC_LIGHT_SIGNAL_TYPE = "1000001"

# ---------------------------------------------------------------------
# P0 signal provenance authority vocabulary
# ---------------------------------------------------------------------

#: provenance prefix for source-grounded (OSM) signals
OSM_SIGNAL_PROVENANCE_PREFIX = "osm_traffic_signals:node/"
#: provenance prefix for the legacy topology-heuristic fallback
HEURISTIC_SIGNAL_PROVENANCE_PREFIX = "traffic_light_infer:"

#: max distance (m) from an OSM signal node to the matched junction
#: incoming-road endpoint. NOT a frozen contract value; documented here and
#: in the stage report. Chosen so a signal node placed at the junction
#: boundary (OSM renders them a few meters inside/outside the intersection
#: area) still matches, while mid-block signal nodes cannot silently leap to
#: a distant junction.
OSM_SIGNAL_MATCH_RADIUS_M = 25.0


def _read_map_rebase_offset(root: ET.Element) -> Tuple[float, float]:
    """Header <offset x y> of the TARGET map (local frame rebase).

    OSM-derived coordinates arrive in the global native tmerc frame
    (bare lat_0=0/lon_0=0); the map's plan view stores local coordinates
    = native - offset. Reading the offset from the target at insert time
    (not from constants) keeps this correct for any local-rebased map.
    """
    hdr = root.find("header")
    if hdr is None:
        return 0.0, 0.0
    off = hdr.find("offset")
    if off is None:
        return 0.0, 0.0
    return (
        _safe_float(off.get("x", "0.0"), 0.0),
        _safe_float(off.get("y", "0.0"), 0.0),
    )


def load_osm_signal_nodes(osm_path: str) -> List[Dict[str, Any]]:
    """Extract real signal nodes from an OSM PBF/XML document.

    Harvests nodes carrying ``highway=traffic_signals`` (the true traffic
    light tag) and ``crossing=traffic_signals`` (pedestrian crossings
    signalled as part of a signalised junction — Ingolstadt's extract has
    zero ``highway=traffic_signals`` nodes but 46 such crossings).

    Returns [{node_id, lat, lon, source_tag}].
    """
    from ultimate_pipeline.enrichment.osm_polygon_loader import TRANSFORMER

    nodes: List[Dict[str, Any]] = []
    for event, el in ET.iterparse(osm_path, events=("end",)):
        if event != "end":
            continue
        if el.tag == "node":
            tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
            source_tag = None
            if tags.get("highway") == "traffic_signals":
                source_tag = "highway=traffic_signals"
            elif tags.get("crossing") == "traffic_signals":
                source_tag = "crossing=traffic_signals"
            if source_tag is not None:
                lat = _safe_float(el.get("lat"), None)
                lon = _safe_float(el.get("lon"), None)
                if lat is not None and lon is not None:
                    nodes.append({
                        "node_id": el.get("id"),
                        "lat": lat,
                        "lon": lon,
                        "source_tag": source_tag,
                    })
        # keep memory bounded on large extracts
        if el.tag in ("node", "way", "relation"):
            el.clear()

    return nodes


def osm_signal_nodes_to_local(
    root: ET.Element, osm_path: str
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Project OSM signal nodes into the TARGET map's LOCAL frame.

    native = osm_polygon_loader.TRANSFORMER(lon, lat)   (global bare tmerc)
    local  = native - (header <offset>.x, .y)

    Returns (nodes, stats) where each node carries local ``x``/``y``.
    """
    raw = load_osm_signal_nodes(osm_path)
    if not raw:
        return [], {"requested": 0, "matched": 0, "unmatched": 0, "reason": "no_signal_nodes_in_source"}

    from ultimate_pipeline.enrichment.osm_polygon_loader import TRANSFORMER

    ox, oy = _read_map_rebase_offset(root)
    out: List[Dict[str, Any]] = []
    for node in raw:
        nx, ny = TRANSFORMER.transform(node["lon"], node["lat"])
        out.append({**node, "x": nx - ox, "y": ny - oy})
    return out, {"requested": len(raw), "matched": 0, "unmatched": 0}


# =====================================================================
# Helper utilities
# =====================================================================

def _ensure_objects_parent(root: ET.Element) -> ET.Element:
    objs = root.find("objects")
    if objs is None:
        objs = ET.SubElement(root, "objects")
    return objs


def _road_endpoint(road: ET.Element, at_start: bool) -> Tuple[float, float, float]:
    """
    Extract (x, y, hdg) from first or last geometry element of road.
    """
    geoms = road.findall("./planView/geometry")
    if not geoms:
        return 0.0, 0.0, 0.0

    geoms.sort(key=lambda g: _safe_float(g.get("s", "0.0"), 0.0))

    g = geoms[0] if at_start else geoms[-1]
    x = _safe_float(g.get("x", "0.0"), 0.0)
    y = _safe_float(g.get("y", "0.0"), 0.0)
    hdg = _safe_float(g.get("hdg", "0.0"), 0.0)

    return x, y, hdg


# =====================================================================
# Unified Traffic Light Inference
# =====================================================================

class TrafficLightInferer:
    """
    Main class that infers traffic lights from junction topology.

    API:
        - infer_as_objects(root)  → list[OSMObject]
        - infer_and_insert(root) → int (count inserted)
    """

    BACK_OFFSET = 6.0     # TL position behind the endpoint
    HEIGHT = 5.0          # meters
    SIZE = 0.4            # TL width/length

    # -----------------------------------------------------------------

    @staticmethod
    def _estimate_junction_center(junc: ET.Element, roads: Dict[str, ET.Element]) -> Tuple[float, float]:
        xs, ys = [], []

        for c in junc.findall("connection"):
            incoming = c.get("incomingRoad")
            if incoming not in roads:
                continue
            x, y, _ = _road_endpoint(roads[incoming], at_start=False)
            xs.append(x)
            ys.append(y)

        if not xs:
            return 0.0, 0.0

        return sum(xs)/len(xs), sum(ys)/len(ys)

    # -----------------------------------------------------------------

    @staticmethod
    def infer_as_objects(root: ET.Element) -> List[OSMObject]:
        """
        Returns inferred TLs as OSMObject (for ObjectInjector).
        """
        roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}

        out: List[OSMObject] = []

        for junc in root.findall("junction"):
            if junc.get("isRoundabout", "false") == "true":
                continue

            conns = junc.findall("connection")
            if len(conns) < 3:
                continue

            cx, cy = TrafficLightInferer._estimate_junction_center(junc, roads)

            idx = 0
            for c in conns:
                rid = c.get("incomingRoad")
                if rid not in roads:
                    continue

                rx, ry, hdg = _road_endpoint(roads[rid], at_start=False)

                # place light back from endpoint along heading
                lx = rx - TrafficLightInferer.BACK_OFFSET * math.cos(hdg)
                ly = ry - TrafficLightInferer.BACK_OFFSET * math.sin(hdg)

                out.append(OSMObject(
                    x=lx, y=ly, z=0.0,
                    obj_type="traffic_light",
                    subtype="auto_inferred"
                ))

                idx += 1

        return out

    # -----------------------------------------------------------------

    @staticmethod
    def infer_and_insert(root: ET.Element,
                         osm_source_path: Optional[str] = None,
                         allow_heuristic_fallback: Optional[bool] = None) -> int:
        """Governed entry point: insert traffic lights from source evidence.

        Priority:
          1. OSM-first (grounded, ``confidence="grounded"``): real OSM
             traffic-signal nodes projected into this map's local frame and
             bound to the nearest junction incoming road within
             ``OSM_SIGNAL_MATCH_RADIUS_M``. Provenance
             ``osm_traffic_signals:node/<id>`` is embedded (ENR-001), per
             junction, a controller groups the signals.
          2. Heuristic fallback (``confidence="inferred"``): legacy topology
             inference ONLY when allowed (``allow_heuristic_fallback=True``
             or env ``UP_ENABLE_TL_HEURISTIC_FALLBACK=1``).
          3. Otherwise inserts NOTHING (0) — never fabricates plausible
             heuristic signals.

        Returns the number of traffic-light signal records inserted.
        Full run statistics are available via TrafficLightInferer.last_run_stats.
        """
        if allow_heuristic_fallback is None:
            allow_heuristic_fallback = os.getenv(
                "UP_ENABLE_TL_HEURISTIC_FALLBACK", ""
            ).strip().lower() in ("1", "true", "yes", "on")

        stats: Dict[str, Any] = {
            "osm_source": None,
            "osm_requested": 0,
            "osm_mapped": 0,
            "osm_unmatched": 0,
            "osm_inserted": 0,
            "heuristic_inserted": 0,
            "heuristic_fallback_enabled": bool(allow_heuristic_fallback),
        }

        resolved_path = osm_source_path or os.getenv("UP_OSM_SIGNALS_SOURCE", "")
        if not resolved_path:
            try:
                from ultimate_pipeline.config.settings import SETTINGS

                resolved_path = getattr(SETTINGS, "OSM_FILE", "") or ""
            except Exception:
                resolved_path = ""
        resolved_path = (resolved_path or "").strip()

        inserted = 0
        if resolved_path and os.path.isfile(resolved_path):
            stats["osm_source"] = resolved_path
            local_nodes, node_stats = osm_signal_nodes_to_local(
                root, resolved_path
            )
            stats["osm_requested"] = node_stats["requested"]
            inserted, stats = TrafficLightInferer._insert_osm_signals(
                root, local_nodes, stats
            )

        fallback = bool(allow_heuristic_fallback)
        if not inserted and not fallback:
            stats["reason"] = (
                "no OSM traffic-signal source mapped and heuristic fallback "
                "disabled: zero signals inserted (no fabrication)"
            )
            TrafficLightInferer.last_run_stats = stats
            return 0

        if fallback:
            heur_count = TrafficLightInferer.infer_and_insert_heuristic(
                root, skip_junction_ids=stats.get("osm_mapped_junction_ids")
            )
            stats["heuristic_inserted"] = heur_count
            inserted += heur_count

        TrafficLightInferer.last_run_stats = stats
        return inserted

    # -----------------------------------------------------------------

    last_run_stats: Dict[str, Any] = {}

    # -----------------------------------------------------------------

    @staticmethod
    def _insert_osm_signals(
        root: ET.Element,
        local_nodes: List[Dict[str, Any]],
        stats: Dict[str, Any],
    ) -> Tuple[int, Dict[str, Any]]:
        """Insert OSM-sourced signals bound to junction incoming roads.

        Matching rule (die-cast, bounded): a signal node matches the NEAREST
        eligible-junction incoming-road endpoint within
        ``OSM_SIGNAL_MATCH_RADIUS_M`` of the road end; placement ``s`` is the
        along-track distance of the node behind the road end (clamped into
        the road), ``t`` the lateral offset in OpenDRIVE's left-positive
        convention. Unmatched nodes are counted, never silently dropped,
        and never force-matched to a further road.
        """
        roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}

        # eligible incoming-road endpoint index (same eligibility rule as the
        # heuristic path: signalised junctions = non-roundabout, >= 3 conns)
        endpoints: List[Tuple[str, str, float, float, float, float]] = []
        eligible_junction_ids = set()
        for junc in root.findall("junction"):
            if junc.get("isRoundabout", "false") == "true":
                continue
            conns = junc.findall("connection")
            if len(conns) < 3:
                continue
            junction_id = junc.get("id", "J")
            eligible_junction_ids.add(junction_id)
            for c in conns:
                incoming = c.get("incomingRoad")
                if incoming not in roads:
                    continue
                road = roads[incoming]
                length = _safe_float(road.get("length", "0.0"), 0.0)
                ex, ey, hdg = _road_endpoint(road, at_start=False)
                endpoints.append((junction_id, incoming, ex, ey, hdg, length))

        if not endpoints:
            stats["osm_unmatched"] = stats["osm_requested"]
            stats["reason"] = "no signalised junction endpoints in map"
            return 0, stats

        per_junction: Dict[str, List[SignalEnrichment]] = {}
        per_junction_object_ids: Dict[str, List[str]] = {}
        matched = 0
        unmatched = 0
        radius_sq = OSM_SIGNAL_MATCH_RADIUS_M * OSM_SIGNAL_MATCH_RADIUS_M

        for node in local_nodes:
            best = None  # (dist_sq, junction_id, incoming, ex, ey, hdg, length)
            for ep in endpoints:
                jid, rid, ex, ey, hdg, length = ep
                dx = node["x"] - ex
                dy = node["y"] - ey
                d2 = dx * dx + dy * dy
                if d2 <= radius_sq and (best is None or d2 < best[0]):
                    best = (d2, jid, rid, ex, ey, hdg, length)
            if best is None:
                unmatched += 1
                continue
            matched += 1
            _, junction_id, road_id, ex, ey, hdg, length = best

            dx = node["x"] - ex
            dy = node["y"] - ey
            cos_h, sin_h = math.cos(hdg), math.sin(hdg)
            # then d_back < 0: node lies beyond the end (node clamps out but match stands)
            d_back = dx * (-cos_h) + dy * (-sin_h)
            t = dx * (-sin_h) + dy * cos_h
            s_pos = min(max(length - d_back, 0.0), max(length, 0.0))

            tl_id = f"tl_osm_{node['node_id']}"
            road = roads[road_id]
            road_objs = road.find("objects")
            if road_objs is None:
                road_objs = ET.SubElement(road, "objects")
            existing_obj_ids = {o.get("id") for o in road_objs.findall("object")}
            if tl_id not in existing_obj_ids:
                ET.SubElement(road_objs, "object", {
                    "id": tl_id,
                    "name": tl_id,
                    "type": "traffic_light",
                    "s": f"{s_pos:.3f}",
                    "t": f"{t:.3f}",
                    "zOffset": "0.0",
                    "hdg": f"{hdg:.6f}",
                    "pitch": "0.0",
                    "roll": "0.0",
                    "orientation": "none",
                    "dynamic": "no",
                    "height": f"{TrafficLightInferer.HEIGHT:.3f}",
                    "length": f"{TrafficLightInferer.SIZE:.3f}",
                    "width": f"{TrafficLightInferer.SIZE:.3f}",
                })

            per_junction.setdefault(junction_id, []).append(SignalEnrichment(
                source_entity=f"{OSM_SIGNAL_PROVENANCE_PREFIX}{node['node_id']}",
                confidence="grounded",
                road_id=road_id,
                s=s_pos,
                t=t,
                signal_type=TRAFFIC_LIGHT_SIGNAL_TYPE,
                subtype="osm_mapped",
                dynamic="yes",
                z_offset=TrafficLightInferer.HEIGHT,
                h_offset=0.0,
                country="OpenDRIVE",
                name=tl_id,
                controller_id=f"ctrl_tl_osm_{junction_id}",
            ))
            per_junction_object_ids.setdefault(junction_id, []).append(tl_id)

        stats["osm_mapped"] = matched
        stats["osm_unmatched"] = unmatched
        stats["osm_mapped_junction_ids"] = sorted(per_junction.keys())

        inserted_count = 0
        for junction_id, records in per_junction.items():
            result = enrich_signals_idempotent(root, records)
            inserted_ids = list(result.get("inserted_signal_ids") or [])
            if not inserted_ids:
                inserted_ids = TrafficLightInferer._signal_ids_for_junction(
                    root, junction_id
                )
            if inserted_ids:
                build_controller(
                    root,
                    controller_id=f"ctrl_tl_osm_{junction_id}",
                    name=f"OSM traffic lights @ junction {junction_id}",
                    signals=inserted_ids,
                )
            inserted_count += len(records)

        stats["osm_inserted"] = inserted_count
        return inserted_count, stats

    # -----------------------------------------------------------------

    @staticmethod
    def infer_and_insert_heuristic(
        root: ET.Element, skip_junction_ids: Optional[set] = None
    ) -> int:
        """
        Inserts traffic lights as standard OpenDRIVE <object> elements under the
        corresponding incoming <road>/<objects> element (road-relative placement),
        AND as paired, functional <signal> elements (CODEX C7 / W2) so that CARLA's
        OpenDRIVE importer creates real traffic-light actors rather than treating
        the traffic light as a static mesh prop. Signals for the same junction are
        grouped under one <controller> so CARLA can cycle them coherently.

        This avoids non-standard <positionWorld> extensions and is generally safer
        for CARLA/OpenDRIVE parsers.

        Returns number of inserted TLs (== number of <object> == number of <signal>).
        """
        roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}

        count = 0

        for junc in root.findall("junction"):
            if junc.get("isRoundabout", "false") == "true":
                continue

            conns = junc.findall("connection")
            if len(conns) < 3:
                continue

            junction_id = junc.get("id", "J")
            if skip_junction_ids and junction_id in skip_junction_ids:
                # already carries source-grounded OSM signals; never overwrite
                # grounded authority with heuristic duplicates
                continue

            signal_records: List[SignalEnrichment] = []
            idx = 0
            for c in conns:
                incoming = c.get("incomingRoad")
                if incoming not in roads:
                    continue

                road = roads[incoming]
                length = _safe_float(road.get("length", "0.0"), 0.0)

                # road end pose
                _, _, hdg = _road_endpoint(road, at_start=False)

                # place ~BACK_OFFSET meters before road end (clamped)
                s_pos = max(0.0, length - TrafficLightInferer.BACK_OFFSET)

                tl_id = f"tl_{junction_id}_{idx}"

                # ensure <objects> under road
                road_objs = road.find("objects")
                if road_objs is None:
                    road_objs = ET.SubElement(road, "objects")

                existing_obj_ids = {o.get("id") for o in road_objs.findall("object")}
                if tl_id not in existing_obj_ids:
                    ET.SubElement(road_objs, "object", {
                        "id": tl_id,
                        "name": tl_id,
                        "type": "traffic_light",
                        "s": f"{s_pos:.3f}",
                        "t": "0.0",
                        "zOffset": "0.0",
                        "hdg": f"{hdg:.6f}",
                        "pitch": "0.0",
                        "roll": "0.0",
                        "orientation": "none",
                        "dynamic": "no",
                        "height": f"{TrafficLightInferer.HEIGHT:.3f}",
                        "length": f"{TrafficLightInferer.SIZE:.3f}",
                        "width": f"{TrafficLightInferer.SIZE:.3f}",
                    })
                    count += 1

                signal_records.append(SignalEnrichment(
                    source_entity=f"traffic_light_infer:{tl_id}",
                    confidence="inferred",
                    road_id=incoming,
                    s=s_pos,
                    t=0.0,
                    signal_type=TRAFFIC_LIGHT_SIGNAL_TYPE,
                    subtype="-1",
                    dynamic="yes",
                    z_offset=TrafficLightInferer.HEIGHT,
                    h_offset=0.0,
                    country="OpenDRIVE",
                    name=tl_id,
                ))

                idx += 1

            if signal_records:
                result = enrich_signals_idempotent(root, signal_records)
                inserted_ids = list(result.get("inserted_signal_ids") or [])
                if not inserted_ids:
                    # Idempotent re-run: signals already present from a
                    # prior call -- find them via provenance for the
                    # controller instead of skipping controller creation.
                    inserted_ids = TrafficLightInferer._signal_ids_for_junction(
                        root, junction_id
                    )
                if inserted_ids:
                    build_controller(
                        root,
                        controller_id=f"ctrl_tl_{junction_id}",
                        name=f"Traffic lights @ junction {junction_id}",
                        signals=inserted_ids,
                    )

        return count

    # -----------------------------------------------------------------

    @staticmethod
    def _signal_ids_for_junction(root: ET.Element, junction_id: str) -> List[str]:
        """Find previously-inserted signal ids for a junction via provenance."""
        prefix = f"traffic_light_infer:tl_{junction_id}_"
        ids: List[str] = []
        for signal in root.findall(".//signal"):
            prov = signal.find("./userData/provenance")
            if prov is None:
                continue
            src = prov.get("source_entity") or ""
            if src.startswith(prefix):
                ids.append(signal.get("id"))
        return ids

    # -----------------------------------------------------------------
    # Perception-readiness transparency: how much of the junction
    # population received a heuristically-inferred signal.
    # -----------------------------------------------------------------
    @staticmethod
    def junction_coverage_stats(root: ET.Element) -> Dict[str, object]:
        """Report what fraction of the map's junctions carry an inferred
        traffic light, and make explicit that every one of them is a
        topology-only heuristic (connection count >= 3, non-roundabout)
        with no OSM or other real-world signal-location source (see
        CODEX_TRAFFIC_LIGHT_GROUND_TRUTH_AUDIT.md).

        The raw insertion count alone (already recorded elsewhere) reads
        as an unremarkable-looking number; on the pinned map-of-record it
        actually corresponds to 2724/3561 (76.5%) of ALL junctions being
        tagged as signal-controlled, which is implausible for a real city
        and matters directly for anyone training/evaluating a perception
        model against this map's traffic-light ground truth -- they need
        this fraction, not just the total, to judge how much to trust it.
        """
        junctions = root.findall("junction")
        total_junctions = len(junctions)
        roundabout_junctions = sum(
            1 for j in junctions if j.get("isRoundabout", "false") == "true"
        )
        eligible = [
            j for j in junctions
            if j.get("isRoundabout", "false") != "true"
            and len(j.findall("connection")) >= 3
        ]

        # One pass over signals building junction_id -> {authority: count}
        # (single linear scan, not one scan per junction).
        osm_prefix = OSM_SIGNAL_PROVENANCE_PREFIX
        heur_prefix = "traffic_light_infer:tl_"  # heuristic id: tl_{junction}_{idx}

        # road -> linked junction (incoming roads carry it in their <link>;
        # needed because OSM provenance encodes the OSM node id, not the
        # OpenDRIVE junction id).
        junction_of_road: Dict[str, str] = {}
        for road in root.findall("road"):
            rid = road.get("id")
            if not rid:
                continue
            for end in ("successor", "predecessor"):
                link = road.find(f"link/{end}")
                if link is not None and link.get("elementType") == "junction":
                    junction_of_road[rid] = link.get("elementId")
                    break

        per_junction: Dict[str, Dict[str, int]] = {}
        total_signals = 0
        for road in root.findall("road"):
            rid = road.get("id")
            for signal in road.findall("signals/signal"):
                prov = signal.find("./userData/provenance")
                if prov is None:
                    continue
                src = prov.get("source_entity") or ""
                if src.startswith(osm_prefix):
                    authority = "osm_mapped"
                    junction_id = junction_of_road.get(rid)
                elif src.startswith(heur_prefix):
                    authority = "heuristic"
                    junction_id, _, _idx = src[len(heur_prefix):].rpartition("_")
                else:
                    continue
                if not junction_id:
                    continue
                total_signals += 1
                entry = per_junction.setdefault(junction_id, {"osm_mapped": 0, "heuristic": 0})
                entry[authority] = entry.get(authority, 0) + 1

        covered = 0
        covered_osm = 0
        covered_heuristic = 0
        junction_signal_counts: Dict[str, int] = {}
        for j in eligible:
            entry = per_junction.get(j.get("id", "J"))
            if entry:
                junction_signal_counts[j.get("id", "J")] = (
                    entry.get("osm_mapped", 0) + entry.get("heuristic", 0)
                )
                covered += 1
                if entry.get("osm_mapped"):
                    covered_osm += 1
                if entry.get("heuristic"):
                    covered_heuristic += 1

        parts = []
        if covered_osm:
            parts.append(
                f"{covered_osm}/{len(eligible)} junctions carry OSM-sourced, "
                "grounded signals (provenance osm_traffic_signals:node/<id>)"
            )
        if covered_heuristic:
            parts.append(
                f"{covered_heuristic}/{len(eligible)} junctions carry "
                "topology-HEURISTIC signals (confidence 'inferred'; "
                "connection count >= 3, non-roundabout); their presence/"
                "absence is unverified, not real-world-accurate"
            )
        if not parts:
            parts.append(
                "no traffic-light signal source mapped: zero inserted "
                "(neither OSM evidence nor heuristic fallback)"
            )

        return {
            "total_junctions": total_junctions,
            "roundabout_junctions": roundabout_junctions,
            "eligible_junctions": len(eligible),
            "eligible_junctions_with_signal": covered,
            "eligible_junction_coverage_fraction": (
                covered / len(eligible) if eligible else 0.0
            ),
            "eligible_junctions_with_osm_signal": covered_osm,
            "eligible_junctions_with_heuristic_signal": covered_heuristic,
            "total_signals": total_signals,
            "signal_authority_counts": per_junction,
            "provenance": "; ".join(parts),
        }

    # -----------------------------------------------------------------
    # Post-inference validation of signal → lane references
    # -----------------------------------------------------------------
    @staticmethod
    def validate_signal_references(root: ET.Element):
        """
        Validate that every <signalReference laneId="X"> refers to a lane on
        its owning road's active lane section at the reference's ``s`` value.

        A map-wide lane-ID inventory is not sufficient: lane IDs repeat on
        every road and can change at a lane-section boundary.  The validator
        therefore rejects an otherwise globally-present ID when it is absent
        from the referenced road at the referenced position.

        Returns list[str] with human-readable errors.
        """
        bad_refs = []
        scoped_references = set()

        for road in root.findall("road"):
            lane_sections = sorted(
                road.findall("./lanes/laneSection"),
                key=lambda section: float(section.get("s", "0")),
            )
            for sig_ref in road.findall(".//signalReference"):
                scoped_references.add(sig_ref)
                sig_id = sig_ref.get("id", "UNKNOWN")
                lane_id = sig_ref.get("laneId")
                if lane_id is None:
                    bad_refs.append(
                        f"signalReference id={sig_id}: missing laneId attribute."
                    )
                    continue

                try:
                    reference_s = float(sig_ref.get("s", "0"))
                except (TypeError, ValueError):
                    bad_refs.append(
                        f"signalReference id={sig_id}: invalid s={sig_ref.get('s')!r}."
                    )
                    continue

                active_section = max(
                    (
                        section
                        for section in lane_sections
                        if float(section.get("s", "0")) <= reference_s
                    ),
                    key=lambda section: float(section.get("s", "0")),
                    default=None,
                )
                lane_ids = (
                    {
                        lane.get("id")
                        for lane in (
                            active_section.findall("./left/lane")
                            + active_section.findall("./right/lane")
                        )
                        if lane.get("id") is not None
                    }
                    if active_section is not None
                    else set()
                )
                if lane_id not in lane_ids:
                    bad_refs.append(
                        "signalReference "
                        f"id={sig_id}: laneId={lane_id} does not exist on road "
                        f"{road.get('id')} at s={reference_s}."
                    )

        for sig_ref in root.findall(".//signalReference"):
            if sig_ref not in scoped_references:
                bad_refs.append(
                    "signalReference "
                    f"id={sig_ref.get('id', 'UNKNOWN')}: reference is not scoped to a road."
                )

        return bad_refs
