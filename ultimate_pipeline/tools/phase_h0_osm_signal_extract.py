#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H0 — OSM signal candidate extraction (Phase H semantic enrichment).

Extracts grounded signal candidates from the authoritative OSM source and
projects them into the verified Osm2Odr native frame (F1 CRS contract).

Candidate kinds (H2 separation):
- GROUNDED  : explicit OSM tags (maxspeed, traffic_sign=DE:2xx, turn:lanes)
- INFERRED  : maxspeed absent but maxspeed:type zone default applies
- SYNTHETIC_DEBUG : never produced from this source

Every candidate carries full provenance (H1): source way id, source tags,
mapping method, confidence, grounded/inferred classification.

Fail-closed: raises if the F1 CRS contract is not verified or the OSM
source cannot be parsed.
"""
from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

from ultimate_pipeline.enrichment.speed_limit_writer import parse_maxspeed
from ultimate_pipeline.enrichment.structure_classifier import _wgs84_to_native_transformer
from ultimate_pipeline.enrichment.structure_classifier import _point_polyline_dist

WRITER_VERSION = "phase_h0_osm_signal_extract.py/1"

# OSM traffic_sign values that map to a governed OpenDRIVE signal type.
ZONE_SIGN_TABLE: Dict[str, Tuple[str, str]] = {
    "DE:240": ("2", "240"),   # zone 30 (StVO 274.1 start zone)
    "DE:245": ("2", "245"),   # zone 50 (StVO 274.2)
    "DE:239": ("2", "239"),   # pedestrian zone
    "DE:274.1": ("2", "240"),
    "DE:274.2": ("2", "245"),
}

# maxspeed:type zone defaults -> km/h (RASt 06 / StVO).
ZONE_TABLE_KMH: Dict[str, int] = {
    "de:urban": 50,
    "de:rural": 100,
    "de:motorway": 130,
    "de:living_street": 7,
    "de:pedestrian": 10,
    "de:zone10": 10,
    "de:zone20": 20,
    "de:zone30": 30,
    "de:zone40": 40,
    "de:zone50": 50,
}

MATCH_DEFAULTS = {"threshold_m": 15.0, "ambiguous_gap_m": 1.5}


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class OSMSignalExtractor:
    """Parse the authoritative OSM and emit provenance-bearing candidates."""

    def __init__(self, osm_path: str, xodr_path: str):
        if not os.path.exists(osm_path):
            raise FileNotFoundError(f"[H0] OSM source missing: {osm_path}")
        if not os.path.exists(xodr_path):
            raise FileNotFoundError(f"[H0] XODR missing: {xodr_path}")
        self.osm_path = osm_path
        self.xodr_path = xodr_path
        self.transformer, self.crs_record = _wgs84_to_native_transformer(
            xodr_path, osm_path
        )
        self.nodes: Dict[str, Tuple[float, float]] = {}
        self.ways: Dict[str, Dict[str, Any]] = {}
        self.counters: Dict[str, int] = {}

    # ------------------------------------------------------------------
    def _load_nodes(self) -> None:
        try:
            for _ev, el in ET.iterparse(self.osm_path, events=("end",)):
                if _localname(el.tag) == "node":
                    try:
                        lat = float(el.get("lat"))
                        lon = float(el.get("lon"))
                        x, y = self.transformer.transform(float(lon), float(lat))
                        self.nodes[el.get("id")] = (float(x), float(y))
                    except Exception:
                        pass
                    el.clear()
        except ET.ParseError as exc:
            raise RuntimeError(f"[H0] OSM parse failed: {exc}") from exc
        if not self.nodes:
            raise RuntimeError("[H0] OSM contains no node coordinates")

    def _load_ways(self) -> None:
        try:
            for _ev, el in ET.iterparse(self.osm_path, events=("end",)):
                if _localname(el.tag) != "way":
                    continue
                tags: Dict[str, str] = {}
                for tag in el.findall("tag"):
                    tags.setdefault(tag.get("k"), tag.get("v"))
                refs = [n.get("ref") for n in el.findall("nd")]
                pts: List[Tuple[float, float]] = []
                for ref in refs:
                    if ref in self.nodes:
                        pts.append(self.nodes[ref])
                self.ways[el.get("id")] = {"tags": tags, "polyline_m": pts}
                el.clear()
        except ET.ParseError as exc:
            raise RuntimeError(f"[H0] OSM parse failed: {exc}") from exc

    # ------------------------------------------------------------------
    @staticmethod
    def _candidate(
        kind: str, way_id: str, tags: Dict[str, str], method: str,
        confidence: float, reason: str, points: List[Tuple[float, float]],
    ) -> Dict[str, Any]:
        return {
            "kind": kind,
            "osm_way_id": way_id,
            "tags": {k: tags.get(k) for k in ("maxspeed", "maxspeed:type",
                                              "traffic_sign", "turn:lanes",
                                              "highway", "junction", "oneway",
                                              "name", "source:maxspeed")
                     if tags.get(k) is not None},
            "method": method,
            "confidence": confidence,
            "reason": reason,
            "start_m": (points[0] if points else None),
            "end_m": (points[-1] if points else None),
            "polyline_m": points,
            "speed_kmh": tags.get("maxspeed") and parse_maxspeed(tags.get("maxspeed")),
            "sign_code": (
                (ZONE_SIGN_TABLE.get(str(tags.get("traffic_sign", "")).strip().upper()) or (None, None))[1]
                if tags.get("traffic_sign") else None
            ),
            "polyline_len_m": sum(
                math.hypot(b[0] - a[0], b[1] - a[1])
                for a, b in zip(points, points[1:])
            ),
        }

    def extract(self) -> Dict[str, Any]:
        self._load_nodes()
        self._load_ways()
        candidates: List[Dict[str, Any]] = []
        grouped: Dict[str, int] = {}
        rejected: List[Dict[str, Any]] = []

        for way_id, w in self.ways.items():
            tags = w["tags"]
            pts = w["polyline_m"]
            if len(pts) < 2:
                continue
            highway = tags.get("highway")

            # --- speed limit (GROUNDED numeric or maxspeed:type zone) ---
            raw_maxspeed = tags.get("maxspeed")
            speed = parse_maxspeed(raw_maxspeed) if raw_maxspeed else None
            if speed is not None and speed > 0:
                candidates.append(self._candidate(
                    "speed_limit", way_id, tags, "GROUNDED", 0.95,
                    f"maxspeed={raw_maxspeed!r}", pts))
                grouped["speed_limit"] = grouped.get("speed_limit", 0) + 1
            elif raw_maxspeed == "none":
                rejected.append(self._candidate(
                    "speed_limit", way_id, tags, "GROUNDED", 0.9,
                    "maxspeed=none (no limit element emitted)", pts))
                grouped["speed_limit_rejected"] = (
                    grouped.get("speed_limit_rejected", 0) + 1)
            else:
                mst = tags.get("maxspeed:type")
                if mst:
                    zone = ZONE_TABLE_KMH.get(str(mst).lower())
                    if zone is not None:
                        candidates.append(self._candidate(
                            "speed_limit", way_id, tags, "INFERRED", 0.7,
                            f"maxspeed:type={mst} -> {zone} km/h", pts))
                        grouped["speed_limit"] = grouped.get("speed_limit", 0) + 1
                    else:
                        rejected.append(self._candidate(
                            "speed_limit", way_id, tags, "INFERRED", 0.5,
                            f"maxspeed:type={mst} not in governed zone table",
                            pts))
                        grouped["speed_limit_rejected"] = (
                            grouped.get("speed_limit_rejected", 0) + 1)
                else:
                    rejected.append(self._candidate(
                        "speed_limit", way_id, tags, "UNMAPPED", 0.0,
                        "no maxspeed / maxspeed:type tag (grounded data absent)", pts))
                    grouped["speed_limit_unmapped"] = (
                        grouped.get("speed_limit_unmapped", 0) + 1)

            # --- zone signs (GROUNDED traffic_sign=DE:2xx) ---
            sign = str(tags.get("traffic_sign", "")).strip().upper()
            if sign:
                entry = ZONE_SIGN_TABLE.get(sign)
                if entry is not None:
                    candidates.append(self._candidate(
                        "zone_sign", way_id, tags, "GROUNDED", 0.9,
                        f"traffic_sign={tags.get('traffic_sign')}", pts))
                    grouped["zone_sign"] = grouped.get("zone_sign", 0) + 1
                elif sign.startswith("DE:"):
                    rejected.append(self._candidate(
                        "zone_sign", way_id, tags, "GROUNDED", 0.6,
                        f"traffic_sign={tags.get('traffic_sign')} not in governed catalog",
                        pts))
                    grouped["zone_sign_rejected"] = (
                        grouped.get("zone_sign_rejected", 0) + 1)
                else:
                    rejected.append(self._candidate(
                        "zone_sign", way_id, tags, "UNMAPPED", 0.0,
                        f"unknown traffic_sign={tags.get('traffic_sign')}", pts))
                    grouped["zone_sign_unmapped"] = (
                        grouped.get("zone_sign_unmapped", 0) + 1)

            # --- turn lane metadata (GROUNDED turn:lanes) ---
            turn = tags.get("turn:lanes")
            if turn and highway:
                candidates.append(self._candidate(
                    "turn_lanes", way_id, tags, "GROUNDED", 0.85,
                    f"turn:lanes={turn}", pts))
                grouped["turn_lanes"] = grouped.get("turn_lanes", 0) + 1

            # --- roundabout cross-check (report only) ---
            if tags.get("junction") == "roundabout":
                grouped["roundabout_way"] = grouped.get("roundabout_way", 0) + 1

            # --- pedestrian crossing (no native element; rejected) ---
            if tags.get("crossing") is not None:
                rejected.append(self._candidate(
                    "crossing", way_id, tags, "GROUNDED", 0.5,
                    "crossing has no governed native <signal> element; report-only",
                    pts))
                grouped["crossing_rejected"] = grouped.get("crossing_rejected", 0) + 1

        self.counters = {
            "ways_total": len(self.ways),
            "nodes_total": len(self.nodes),
            **grouped,
            "candidates_total": len(candidates),
            "rejected_total": len(rejected),
        }
        return {
            "producer": WRITER_VERSION,
            "osm_path": self.osm_path,
            "xodr_path": self.xodr_path,
            "crs_verdict": self.crs_record.get("verdict"),
            "counters": self.counters,
            "candidates": candidates,
            "rejected": rejected,
        }


def main() -> int:
    import json
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo))
    osm = repo / "campaigns" / "ingolstadt_cooked_perception_v1" / "source" / "ingolstadt_authoritative.osm"
    xodr = repo / "reports" / "post_audit_hardening" / "20260804T030000Z" / "candidate_g7_roadmarks.xodr"
    rec = OSMSignalExtractor(str(osm), str(xodr)).extract()
    print(json.dumps(rec["counters"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
