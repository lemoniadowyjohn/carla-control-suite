#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage 1 — freeze the semantic parent.

Verifies candidate_g_semantic_enriched.xodr is the accepted 3467-signal
semantic parent, proves it descends from the repaired candidate (structural
digests identical), and writes frozen authority records:

  S03_SEMANTIC_PARENT_AUTHORITY.json
  S04_PROTECTED_STRUCTURAL_DIGESTS.json
  S05_TRAFFIC_CONTROL_DIGESTS.json

Read-only; no mutation.
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO))

from phase_q.signal_digest import combined_traffic_control_digest
from phase_q.structural_digest import all_structural_digests
from phase_q.common import sha256_text, XodrTree

REPAIRED = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate" / "ingolstadt_fixed_final.xodr"
ENRICHED = REPO / "reports" / "post_audit_hardening" / "20260807T000000Z" / "candidate_g_semantic_enriched.xodr"
SRC = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate" / "raw_xodr_run_1_epsg32632_header_pinned.xodr"
OUT = REPO / "reports" / "post_audit_hardening" / "20260807T000000Z"


def _text(p):
    return p.read_text(encoding="utf-8", errors="replace")


def _counts(xodr_text):
    root = XodrTree(xodr_text).root
    return {
        "roads": len(root.findall("road")),
        "junctions": len(root.findall("junction")),
        "laneSections": len(root.findall(".//laneSection")),
        "lanes": len(root.findall(".//lane")),
        "roadMarks": len(root.findall(".//roadMark")),
        "signals": len(root.findall(".//signal")),
        "controllers": len(root.findall(".//controller")),
        "signalReferences": len(root.findall(".//signalReference")),
        "objects": len(root.findall(".//object")),
    }


def _connector_repair_ids(repaired_text):
    fixed = []
    if not SRC.exists():
        return fixed
    src_root = ET.fromstring(_text(SRC))
    rep_root = ET.fromstring(repaired_text)
    # Source has roads with a zero-length sole connector geometry (length 0.0);
    # the repair patched them to road_length 0.1. Detect from the source.
    for s in src_root.findall("road"):
        pv = s.find("planView")
        if pv is None:
            continue
        has_zero = any(
            float(g.get("length", "0") or "0") == 0.0
            for g in pv.findall("geometry")
        )
        if not has_zero:
            continue
        rid = s.get("id")
        # confirm the repaired candidate retains the road with a positive length
        r = rep_root.find(f"road[@id='{rid}']")
        if r is not None and float(r.get("length", "0") or "0") > 0:
            fixed.append(rid)
    return sorted(fixed, key=lambda x: (len(x), x))


def main():
    rep_text = _text(REPAIRED)
    enr_text = _text(ENRICHED)
    rep_counts = _counts(rep_text)
    enr_counts = _counts(enr_text)
    connector_ids = _connector_repair_ids(rep_text)

    rep_struct = all_structural_digests(rep_text)
    enr_struct = all_structural_digests(enr_text)
    rep_tc = combined_traffic_control_digest(XodrTree(rep_text))
    enr_tc = combined_traffic_control_digest(XodrTree(enr_text))

    invariants = {
        "planview": rep_struct["planview_digest"] == enr_struct["planview_digest"],
        "road_link": rep_struct["road_link_digest"] == enr_struct["road_link_digest"],
        "junction": rep_struct["junction_digest"] == enr_struct["junction_digest"],
        "lanelink": rep_struct["lanelink_digest"] == enr_struct["lanelink_digest"],
        "lanesection": rep_struct["lanesection_digest"] == enr_struct["lanesection_digest"],
        "elevation": rep_struct["elevation_digest"] == enr_struct["elevation_digest"],
    }
    structure_preserved = rep_struct["combined_structural_digest"] == enr_struct["combined_structural_digest"]

    authority = {
        "run_id": "20260807T000000Z",
        "stage": "1",
        "producer": "stage_1_freeze_semantic_parent.py",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "semantic_parent": {
            "path": str(ENRICHED),
            "name": "candidate_g_semantic_enriched",
            "sha256_lf_text": sha256_text(enr_text),
            "parent": {
                "path": str(REPAIRED),
                "sha256_raw_bytes": sha256_text(REPAIRED.read_bytes().decode("utf-8", "replace")),
                "sha256_lf_text": sha256_text(rep_text),
                "descended_from_repaired": structure_preserved,
            },
        },
        "counts": enr_counts,
        "repaired_counts": rep_counts,
        "structural_invariants": invariants,
        "structure_preserved": structure_preserved,
        "traffic_control": enr_tc,
        "connector_repair_ids": connector_ids,
        "connector_count": len(connector_ids),
        "verdict": "SEMANTIC_PARENT_FROZEN" if (
            structure_preserved
            and enr_counts["signals"] == 3467
            and enr_counts["roads"] == 32710
            and enr_counts["junctions"] == 3646
            and len(connector_ids) == 12
        ) else "SEMANTIC_PARENT_REJECTED",
    }
    (OUT / "S03_SEMANTIC_PARENT_AUTHORITY.json").write_text(
        json.dumps(authority, indent=2, sort_keys=True), encoding="utf-8")

    s04 = {
        "run_id": authority["run_id"],
        "repaired": rep_struct,
        "semantic_parent": enr_struct,
        "structural_identicals": invariants,
        "structure_preserved": structure_preserved,
        "note": "All protected structural digests MUST equal the repaired parent.",
    }
    (OUT / "S04_PROTECTED_STRUCTURAL_DIGESTS.json").write_text(
        json.dumps(s04, indent=2, sort_keys=True), encoding="utf-8")

    (OUT / "S05_TRAFFIC_CONTROL_DIGESTS.json").write_text(
        json.dumps({
            "run_id": authority["run_id"],
            "schema": enr_tc["schema"],
            "signal_count": enr_tc["signal_count"],
            "signal_reference_count": enr_tc["signal_reference_count"],
            "controller_count": enr_tc["controller_count"],
            "signal_element_digest": enr_tc["signal_element_digest"],
            "signal_reference_digest": enr_tc["signal_reference_digest"],
            "controller_digest": enr_tc["controller_digest"],
            "combined_traffic_control_digest": enr_tc["combined_traffic_control_digest"],
            "repaired_parent_combined": rep_tc["combined_traffic_control_digest"],
            "expected_signal_count": 3467,
            "signal_count_matches": enr_tc["signal_count"] == 3467,
        }, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Stage 1: {authority['verdict']}")
    print(f"  enriched LF sha: {sha256_text(enr_text)[:16]}...")
    print(f"  signals={enr_counts['signals']} roads={enr_counts['roads']} juncs={enr_counts['junctions']}")
    print(f"  connectors repaired={len(connector_ids)}")
    print(f"  structure_preserved={structure_preserved}")
    print(f"  traffic-control digest={enr_tc['combined_traffic_control_digest'][:16]}...")
    return 0 if authority["verdict"] == "SEMANTIC_PARENT_FROZEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
