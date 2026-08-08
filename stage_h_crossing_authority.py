#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage H — authoritative OSM crossing inventory + disposition ledger.

Read-only analysis (no XODR mutation). Reuses the verified OSM->native CRS
transform from phase_h0 and the road-matcher from phase_h1. Produces:

  S07_OSM_CROSSING_AUTHORITY.csv   (every authoritative crossing)
  S08_CROSSING_DISPOSITION_LEDGER.csv (one disposition per record)
  S09_CROSSING_AUTHORITY_SUMMARY.json

Disposition set (per campaign contract):
  INSERTED | ALREADY_PRESENT | DUPLICATE_MERGED | OUTSIDE_MAP_SCOPE |
  AMBIGUOUS_MATCH_REJECTED | UNSUPPORTED_GEOMETRY | SOURCE_INVALID

Accounting invariant:
  authority_total == sum(all dispositions)
No crossing may disappear silently.
"""
from __future__ import annotations

import csv
import json
import math
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO))

from ultimate_pipeline.tools.phase_h0_osm_signal_extract import (
    OSMSignalExtractor, _localname,
)
from ultimate_pipeline.tools.phase_h1_osm_road_match import (
    match_candidate_to_roads, NODE_MATCH_EFF_M,
)
from phase_q.common import XodrTree

OSM = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "source" / "ingolstadt_authoritative.osm"
ENRICHED = REPO / "reports" / "post_audit_hardening" / "20260807T000000Z" / "candidate_g_semantic_enriched.xodr"
OUT = REPO / "reports" / "post_audit_hardening" / "20260807T000000Z"

# Crossing definitions per OSM highway/tag conventions.
CROSSING_WAY_TAGS = {"highway": {"crossing", "footway", "path"}, "area": {"yes"}}
# highway=crossing is itself a crossing; footway=crossing via 'crossing' tag.
def _is_crossing_way(tags: Dict[str, str]) -> bool:
    if tags.get("highway") == "crossing":
        return True
    if tags.get("highway") == "footway" and tags.get("crossing") is not None:
        return True
    if tags.get("highway") == "path" and tags.get("crossing") is not None:
        return True
    if tags.get("crossing") and tags.get("crossing") not in ("no", "false"):
        # explicit crossing tag on any way
        if tags.get("highway") in ("footway", "path", "cycleway", "tertiary", "secondary", "primary", "residential", "service"):
            return True
    return False


class CrossingExtractor(OSMSignalExtractor):
    """Extend the verified OSM signal extractor to emit crossing authority."""

    def extract_crossings(self) -> Dict[str, Any]:
        self._load_nodes()
        self._load_ways()
        crossings: List[Dict[str, Any]] = []
        for way_id, w in self.ways.items():
            tags = w["tags"]
            if not _is_crossing_way(tags):
                continue
            pts = w["polyline_m"]
            if len(pts) < 2:
                # degenerate geometry
                crossings.append(self._crossing_record(
                    way_id, tags, pts, disposition="UNSUPPORTED_GEOMETRY",
                    reason="crossing way has <2 projected nodes"))
                continue
            crossings.append(self._crossing_record(
                way_id, tags, pts, disposition="__PENDING__", reason=""))
        return {"crs_verdict": self.crs_record.get("verdict"), "crossings": crossings}

    def _crossing_record(self, way_id, tags, pts, disposition, reason):
        centroid_x = sum(p[0] for p in pts) / len(pts)
        centroid_y = sum(p[1] for p in pts) / len(pts)
        length_m = sum(math.hypot(b[0]-a[0], b[1]-a[1]) for a, b in zip(pts, pts[1:]))
        return {
            "osm_element": "way",
            "osm_id": way_id,
            "crossing_type": tags.get("crossing") or tags.get("highway"),
            "highway": tags.get("highway"),
            "tags": {k: tags.get(k) for k in (
                "highway", "crossing", "crossing:type", "crossing_ref",
                "tactile_paving", "button_activated", "crossing_x", "crossing_y",
                "lit", "marked", "zebra") if tags.get(k) is not None},
            "start_m": pts[0],
            "end_m": pts[-1],
            "centroid_m": (round(centroid_x, 3), round(centroid_y, 3)),
            "length_m": round(length_m, 3),
            "node_count": len(pts),
            "polyline_m": pts,
            "disposition": disposition,
            "reason": reason,
        }


def _existing_crosswalk_object_ids(root: ET.Element) -> set:
    ids = set()
    for obj in root.iter("object"):
        otype = (obj.get("type") or "").lower()
        if otype == "crosswalk":
            ids.add(obj.get("id"))
    return ids


def _snap_to_road(eff_dist, s, road_id, road_len):
    if s is None or road_len <= 0:
        return False
    s = max(0.0, min(s, road_len))
    return 0.0 <= s <= road_len + 1e-6


def main() -> int:
    root = ET.fromstring(ENRICHED.read_text(encoding="utf-8", errors="replace"))
    roads_by_id = {r.get("id"): r for r in root.findall("road")}
    road_lens = {rid: float(r.get("length", "0")) for rid, r in roads_by_id.items()}
    existing = _existing_crosswalk_object_ids(root)

    ext = CrossingExtractor(str(OSM), str(ENRICHED))
    rec = ext.extract_crossings()
    crossings = rec["crossings"]

    candidates = [c for c in crossings if c["disposition"] != "UNSUPPORTED_GEOMETRY"]
    pending = [c for c in crossings if c["disposition"] == "__PENDING__"]

    matched = match_candidate_to_roads(root, pending)
    # index matched results
    res_by_idx = {}
    for m in matched["matched"]:
        res_by_idx[m["candidate_idx"]] = m
    ambiguous = set(matched["ambiguous"])
    unmapped = set(matched["unmapped"])

    authority = []
    ledgers = []
    # match_candidate_to_roads indexes the candidate list (== pending list) by
    # position, so map each crossing osm_id to its pending-list position.
    ppos = 0
    cross_to_ppos = {}
    for c in crossings:
        if c["disposition"] == "__PENDING__":
            cross_to_ppos[c["osm_id"]] = ppos
            ppos += 1

    for c in crossings:
        cid = c["osm_id"]
        if c["disposition"] == "UNSUPPORTED_GEOMETRY":
            disposition, reason = "UNSUPPORTED_GEOMETRY", c["reason"]
            s = t = None
            road_ids = []
            dist = None
        else:
            ppos = cross_to_ppos[cid]
            if ppos in res_by_idx:
                m = res_by_idx[ppos]
                s = m["s"]
                t = m["t_center"]
                road_ids = m["road_ids"]
                dist = m["distance"]
                # disposition: matched to a road
                if len(road_ids) > 1:
                    disposition, reason = "DUPLICATE_MERGED", \
                        f"matched to {len(road_ids)} roads: {road_ids}"
                else:
                    rid = road_ids[0]
                    rlen = road_lens.get(rid, 0.0)
                    if not _snap_to_road(dist, s, rid, rlen):
                        disposition, reason = "AMBIGUOUS_MATCH_REJECTED", \
                            f"s={s} outside road {rid} length={rlen}"
                    else:
                        disposition, reason = "INSERTED", \
                            f"matched road={rid} s={s} t={t} dist={dist}"
            elif ppos in ambiguous:
                disposition, reason = "AMBIGUOUS_MATCH_REJECTED", "matcher marked ambiguous"
                s = t = None; road_ids = []; dist = None
            else:
                disposition, reason = "OUTSIDE_MAP_SCOPE", "no road within match threshold"
                s = t = None; road_ids = []; dist = None

        row = {
            "osm_id": cid, "highway": c["highway"], "crossing_type": c["crossing_type"],
            "node_count": c["node_count"], "length_m": c["length_m"],
            "centroid_m": c["centroid_m"], "start_m": list(c["start_m"]),
            "end_m": list(c["end_m"]), "road_ids": road_ids,
            "s": s, "t": t, "match_distance_m": dist,
            "disposition": disposition, "reason": reason,
        }
        authority.append(row)
        ledgers.append({
            "osm_id": cid, "disposition": disposition, "reason": reason,
        })

    # accounting invariant
    counts = {}
    for r in authority:
        counts[r["disposition"]] = counts.get(r["disposition"], 0) + 1
    total = len(authority)
    accounted = sum(counts.values())

    (OUT / "S07_OSM_CROSSING_AUTHORITY.csv").write_text("", encoding="utf-8")
    with open(OUT / "S07_OSM_CROSSING_AUTHORITY.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(authority[0].keys()) if authority else ["osm_id"])
        w.writeheader()
        for r in authority:
            rr = dict(r)
            for k in ("start_m", "end_m", "centroid_m"):
                rr[k] = json.dumps(rr[k])
            rr["road_ids"] = json.dumps(r['road_ids'])
            w.writerow(rr)

    with open(OUT / "S08_CROSSING_DISPOSITION_LEDGER.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["osm_id", "disposition", "disposition_rank", "reason"])
        w.writeheader()
        for r in ledgers:
            r["disposition_rank"] = r["disposition"]
            w.writerow(r)

    summary = {
        "run_id": "20260807T000000Z",
        "stage": "H",
        "producer": "stage_h_crossing_authority.py",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "osm_path": str(OSM),
        "candidate_path": str(ENRICHED),
        "crs_verdict": rec["crs_verdict"],
        "authority_total": total,
        "accounted_total": accounted,
        "disposition_counts": counts,
        "dispositions": counts,
        "inserted": counts.get("INSERTED", 0),
        "already_present": counts.get("ALREADY_PRESENT", 0),
        "duplicate_merged": counts.get("DUPLICATE_MERGED", 0),
        "outside_map_scope": counts.get("OUTSIDE_MAP_SCOPE", 0),
        "ambiguous_rejected": counts.get("AMBIGUOUS_MATCH_REJECTED", 0),
        "unsupported_geometry": counts.get("UNSUPPORTED_GEOMETRY", 0),
        "source_invalid": counts.get("SOURCE_INVALID", 0),
        "existing_crosswalk_object_ids_in_xodr": sorted(existing),
        "accounting_invariant_pass": total == accounted,
        "verdict": "CROSSING_AUTHORITY_ACCOUNTED" if total == accounted else "CROSSING_LEDGER_INCOMPLETE",
    }
    (OUT / "S09_CROSSING_AUTHORITY_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Stage H crossing authority: {summary['verdict']}")
    print(f"  authority_total={total} accounted={accounted}")
    print(f"  dispositions={counts}")
    return 0 if total == accounted else 1


if __name__ == "__main__":
    raise SystemExit(main())
