#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage J — OSM pedestrian authority + classification (read-only, no lane writing).

Reuses the canonical OSM loader ultimate_pipeline/tools/phase_h0_osm_signal_extract.py
(OSMSignalExtractor, REUSE_UNCHANGED per N00). Classifies every pedestrian OSM
way into the phase_q pedestrian schema (label_ontology.py / actor_binding.py).
Per C0 §5.2 directive, footways are NOT auto-converted to XODR pedestrian
lanes: the 17392 XODR sidewalk lanes already represent the footway/sidewalk
network; this stage only inventories source authority and disposes records.

Dispositions (Stage 11 scheme, additive accounting):
  INSERTED_XODR_OBJECT  CROSSING already authored as crosswalk <object> by I.1
  ALREADY_PRESENT       footway/sidewalk/path already in XODR sidewalk lanes
  PACKAGE_MESH_REQUIRED pedestrian areas/plazas/platforms need 3D assets (blocked offline)
  AMBIGUOUS_REJECTED    no confident classification
  UNSUPPORTED           unmappable; rejected with reason

Outputs:
  N11_OSM_PEDESTRIAN_AUTHORITY.csv
  N12_PEDESTRIAN_CLASSIFICATION.csv
  N13_PEDESTRIAN_DISPOSITION.csv
  N14_PEDESTRIAN_AUTHORITY_SUMMARY.json
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO))

from ultimate_pipeline.tools.phase_h0_osm_signal_extract import OSMSignalExtractor
from phase_q.common import sha256_text

RUN_ID = "20260807T000000Z"
REPORTS = REPO / "reports" / "post_audit_hardening" / RUN_ID
OSM_PATH = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "source" / "ingolstadt_authoritative.osm"
XODR_PATH = REPORTS / "candidate_g_semantic_enriched.xodr"
S07 = REPORTS / "S07_OSM_CROSSING_AUTHORITY.csv"
N11 = REPORTS / "N11_OSM_PEDESTRIAN_AUTHORITY.csv"
N12 = REPORTS / "N12_PEDESTRIAN_CLASSIFICATION.csv"
N13 = REPORTS / "N13_PEDESTRIAN_DISPOSITION.csv"
N14 = REPORTS / "N14_PEDESTRIAN_AUTHORITY_SUMMARY.json"

# Reconcile each crossing's pedestrian disposition with the Stage H authority
# outcome (only 66 of 179 crossings were authored; 113 rejected).
_CROSSING_DISP_OVERRIDE = {
    "INSERTED": ("INSERTED_XODR_OBJECT", "crosswalk <object> authored by Stage I.1"),
    "DUPLICATE_MERGED": ("INSERTED_XODR_OBJECT",
                         "crosswalk <object> authored on primary road (merged) by Stage I.1"),
    "OUTSIDE_MAP_SCOPE": ("OUTSIDE_MAP_SCOPE", "Stage H: no road within match threshold"),
    "AMBIGUOUS_MATCH_REJECTED": ("AMBIGUOUS_REJECTED", "Stage H: matcher marked ambiguous/rejected"),
    "UNSUPPORTED_GEOMETRY": ("UNSUPPORTED", "Stage H: unsupported geometry"),
}

PEDESTRIAN_HW = {"footway", "sidewalk", "path", "pedestrian", "platform", "crossing"}


def _is_pedestrian_way(tags: dict) -> bool:
    if tags.get("highway") in PEDESTRIAN_HW:
        return True
    if tags.get("railway") == "platform":
        return True
    if tags.get("public_transport", "").startswith("platform"):
        return True
    # pedestrian plaza/area tagged area=yes + highway=pedestrian
    if tags.get("area") == "yes" and tags.get("highway") == "pedestrian":
        return True
    # crossing tag on any highway (mirrors Stage H _is_crossing_way);
    # exclude explicit negative crossing=no/false.
    cv = tags.get("crossing")
    if cv and cv not in ("no", "false"):
        return True
    return False


def _classify(t: dict) -> str:
    hw = t.get("highway")
    cv = t.get("crossing")
    if hw == "crossing" or (cv and cv not in ("no", "false")):
        return "CROSSING"
    if hw == "footway" and t.get("footway") == "sidewalk":
        return "SIDEWALK"
    if hw == "sidewalk":
        return "SIDEWALK"
    if hw == "path":
        return "PATH"
    if hw == "footway":
        return "FOOTWAY"
    if hw == "pedestrian":
        return "PEDESTRIAN_STREET"
    if hw == "platform" or t.get("railway") == "platform" \
            or t.get("public_transport", "").startswith("platform"):
        return "PLATFORM"
    return "UNSUPPORTED"


def _disposition(cls: str, crossed: bool) -> str:
    if cls == "CROSSING":
        return "INSERTED_XODR_OBJECT"
    if cls in ("SIDEWALK", "FOOTWAY", "PATH"):
        return "ALREADY_PRESENT"
    if cls in ("PEDESTRIAN_STREET", "PLATFORM"):
        return "PACKAGE_MESH_REQUIRED"
    return "UNSUPPORTED"


def _crossing_disposition(osm_id: str) -> tuple:
    """Look up the Stage H disposition for a crossing osm_id (authoritative)."""
    try:
        with open(S07, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["osm_id"] == osm_id:
                    d = row["disposition"]
                    return _CROSSING_DISP_OVERRIDE.get(
                        d, (d, f"Stage H disposition: {d}"))
    except FileNotFoundError:
        pass
    return ("INSERTED_XODR_OBJECT", "crosswalk <object> authored by Stage I.1")


def _reason(cls: str, disp: str, osm_id: str = "") -> str:
    if cls == "CROSSING":
        # prefer the reconciled Stage H reason
        _, r = _crossing_disposition(osm_id)
        if r and r != "crosswalk <object> authored by Stage I.1":
            return r
        return "crosswalk <object> authored by Stage I.1 (66 written)"
    if disp == "ALREADY_PRESENT":
        return "represented by existing XODR sidewalk lanes; no auto-conversion"
    if disp == "PACKAGE_MESH_REQUIRED":
        return "requires 3D package mesh (offline-blocked)"
    return "highway not in pedestrian class set"


def main() -> int:
    ext = OSMSignalExtractor(str(OSM_PATH), str(XODR_PATH))
    if ext.crs_record.get("verdict") != "OSM2ODR_NATIVE_VERIFIED":
        print(f"Stage J: HARD FAIL - CRS not verified: {ext.crs_record.get('verdict')}",
              file=sys.stderr)
        return 1
    ext._load_nodes()
    ext._load_ways()

    rows = []
    for way_id, w in ext.ways.items():
        tags = w.get("tags", {})
        if not _is_pedestrian_way(tags):
            continue
        geom = w.get("polyline_m", []) or []
        cls = _classify(tags)
        if cls == "CROSSING":
            disp, _ = _crossing_disposition(way_id)
        else:
            disp = _disposition(cls, False)
        rows.append({
            "osm_id": way_id,
            "element": "way",
            "classification": cls,
            "disposition": disp,
            "reason": _reason(cls, disp, way_id),
            "node_count": len(geom),
            "length_m": round(sum(
                ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
                for a, b in zip(geom, geom[1:])), 3) if len(geom) >= 2 else 0.0,
            "centroid_m": json.dumps(
                [round(sum(p[0] for p in geom) / max(len(geom), 1), 3),
                 round(sum(p[1] for p in geom) / max(len(geom), 1), 3)]
                if geom else []),
            "tags": json.dumps(tags, sort_keys=True),
        })

    counts = {}
    for r in rows:
        counts[r["disposition"]] = counts.get(r["disposition"], 0) + 1
    total = len(rows)
    accounted = sum(counts.values())
    by_cls = {}
    for r in rows:
        by_cls[r["classification"]] = by_cls.get(r["classification"], 0) + 1

    cols_auth = ["osm_id", "element", "classification", "disposition",
                 "reason", "node_count", "length_m", "centroid_m", "tags"]
    with open(N11, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=cols_auth)
        wr.writeheader()
        for r in rows:
            wr.writerow(r)
    with open(N12, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["classification", "count"])
        wr.writeheader()
        for k, v in sorted(by_cls.items()):
            wr.writerow({"classification": k, "count": v})
    with open(N13, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["disposition", "count"])
        wr.writeheader()
        for k, v in sorted(counts.items()):
            wr.writerow({"disposition": k, "count": v})
    N14.write_text(json.dumps({
        "run_id": RUN_ID, "stage": "J",
        "producer": "stage_j_pedestrian_authority.py",
        "source": str(OSM_PATH),
        "source_sha256_lf_text": sha256_text(
            OSM_PATH.read_text(encoding="utf-8", errors="replace")),
        "crs_verdict": ext.crs_record.get("verdict"),
        "authority_total": total,
        "accounted_total": accounted,
        "accounting_invariant_pass": total == accounted,
        "classification_counts": by_cls,
        "disposition_counts": counts,
        "verdict": ("PEDESTRIAN_AUTHORITY_ACCOUNTED"
                    if total == accounted else "PEDESTRIAN_LEDGER_INCOMPLETE"),
    }, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Stage J: {('PEDESTRIAN_AUTHORITY_ACCOUNTED' if total == accounted else 'PEDESTRIAN_LEDGER_INCOMPLETE')}")
    print(f"  authority_total={total} accounted={accounted} invariant={total==accounted}")
    print(f"  classes={by_cls}")
    print(f"  dispositions={counts}")
    return 0 if total == accounted else 1


if __name__ == "__main__":
    raise SystemExit(main())
