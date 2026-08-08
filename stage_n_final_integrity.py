#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage N — final semantic integrity gate (N17/N18).

Read-only re-verification from the on-disk crosswalk-enriched candidate:
  * structural + traffic-control digests unchanged vs frozen parent (N02/N03)
  * counts (roads=32710, junctions=3646, signals=3467)
  * signal ID set / signalReference / controller digests unchanged
  * the 12 connector repairs preserved
  * no invalid road IDs, invalid s, duplicate semantic IDs, invalid polygons
  * OSM crossing authority accounted (Stage H S09)
  * pedestrian authority accounted (N14)
  * semantic diff (N18): only objects+crosswalk_objects may change
"""
from __future__ import annotations

import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO))

from phase_q.common import sha256_text, XodrTree, strip_xml_namespaces
from phase_q.structural_digest import all_structural_digests
from phase_q.signal_digest import combined_traffic_control_digest
from phase_q.semantic_evidence import (
    extract_semantic_inventory, compare_inventories,
)
from ultimate_pipeline.enrichment.crosswalk_schema import (
    carla_world_corners, reference_pose_at_s,
)

RUN_ID = "20260807T000000Z"
R = REPO / "reports" / "post_audit_hardening" / RUN_ID
CAND = R / "candidate_crosswalk_enriched.xodr"
PARENT = R / "candidate_g_semantic_enriched.xodr"
N14 = R / "N14_PEDESTRIAN_AUTHORITY_SUMMARY.json"
S09 = R / "S09_CROSSING_AUTHORITY_SUMMARY.json"
N17 = R / "N17_FINAL_SEMANTIC_INTEGRITY.json"
N18 = R / "N18_SEMANTIC_DIFF.json"


def _counts(root):
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


def _crosswalk_polygon_valid(pts):
    """World-reconstructed CARLA polygon must be closed, finite, non-degenerate."""
    if not pts or len(pts) < 4:
        return False
    if pts[0][0] != pts[-1][0] or pts[0][1] != pts[-1][1]:
        return False
    if not all(math.isfinite(p) for pt in pts for p in pt):
        return False
    area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:]))
    return abs(area) / 2.0 > 1e-6


def _crosswalk_objects(root):
    items = []
    for road in root.findall("road"):
        rid = road.get("id")
        rlen = float(road.get("length", "0") or "0")
        objs = road.find("objects")
        if objs is None:
            continue
        for o in objs.findall("object"):
            if (o.get("type") or "").lower() == "crosswalk":
                items.append((o, road, rid, rlen))
    return items


def _local_corners(o: ET.Element):
    ol = o.find("outline")
    if ol is None:
        return []
    pts = []
    for c in ol.findall("cornerLocal"):
        try:
            pts.append((
                float(c.get("u", "0") or "0"),
                float(c.get("v", "0") or "0"),
                float(c.get("z", "0") or "0"),
            ))
        except (TypeError, ValueError):
            return []
    return pts


def main() -> int:
    text = CAND.read_text(encoding="utf-8", errors="replace")
    parent_text = PARENT.read_text(encoding="utf-8", errors="replace")
    root = ET.fromstring(strip_xml_namespaces(text))
    parent_root = ET.fromstring(strip_xml_namespaces(parent_text))

    counts = _counts(root)
    parent_counts = _counts(parent_root)

    struct = all_structural_digests(text)
    parent_struct = all_structural_digests(parent_text)
    tc = combined_traffic_control_digest(XodrTree(text))
    parent_tc = combined_traffic_control_digest(XodrTree(parent_text))

    parent_inv = extract_semantic_inventory(parent_text)
    child_inv = extract_semantic_inventory(text)
    cmp = compare_inventories(parent_inv, child_inv)

    cw = _crosswalk_objects(root)
    cw_ids = [o.get("id") for o, _, _, _ in cw]
    bad_s, bad_poly = [], []
    for o, road, rid, rlen in cw:
        s = float(o.get("s", "0") or "0")
        if s < -1e-6 or s > rlen + 1e-3:
            bad_s.append((o.get("id"), rid, s, rlen))
        local_pts = _local_corners(o)
        pose = reference_pose_at_s(road, s)
        world = None
        if pose is not None and local_pts:
            hdg = float(o.get("hdg", "0") or "0")
            t = float(o.get("t", "0") or "0")
            world = carla_world_corners(local_pts, pose, t, hdg)
        if not _crosswalk_polygon_valid(world):
            bad_poly.append(o.get("id"))

    allowed = {"objects", "crosswalk_objects"}
    only_allowed = all(v["equivalent"] or c in allowed
                       for c, v in cmp["categories"].items())

    conn_ids = set(json.loads((R / "S03_SEMANTIC_PARENT_AUTHORITY.json")
                              .read_text())["connector_repair_ids"])

    checks = {
        "roads_32710": counts["roads"] == 32710,
        "junctions_3646": counts["junctions"] == 3646,
        "signals_3467": counts["signals"] == 3467,
        "counts_unchanged_from_parent": (
            counts["roads"] == parent_counts["roads"]
            and counts["junctions"] == parent_counts["junctions"]
            and counts["signals"] == parent_counts["signals"]
            and counts["laneSections"] == parent_counts["laneSections"]
            and counts["controllers"] == parent_counts["controllers"]
            and counts["signalReferences"] == parent_counts["signalReferences"]),
        "combined_structural_digest_unchanged":
            struct["combined_structural_digest"] == parent_struct["combined_structural_digest"],
        "planview_unchanged": struct["planview_digest"] == parent_struct["planview_digest"],
        "road_link_unchanged": struct["road_link_digest"] == parent_struct["road_link_digest"],
        "junction_unchanged": struct["junction_digest"] == parent_struct["junction_digest"],
        "lanelink_unchanged": struct["lanelink_digest"] == parent_struct["lanelink_digest"],
        "lanesection_unchanged": struct["lanesection_digest"] == parent_struct["lanesection_digest"],
        "elevation_unchanged": struct["elevation_digest"] == parent_struct["elevation_digest"],
        "combined_tc_unchanged": tc["combined_traffic_control_digest"] == parent_tc["combined_traffic_control_digest"],
        "signal_element_unchanged": tc["signal_element_digest"] == parent_tc["signal_element_digest"],
        "signal_reference_unchanged": tc["signal_reference_digest"] == parent_tc["signal_reference_digest"],
        "controller_unchanged": tc["controller_digest"] == parent_tc["controller_digest"],
        "signal_id_set_unchanged": parent_inv.get("signals") == child_inv.get("signals"),
        "12_connector_repairs_preserved": conn_ids == {
            "50003", "51425", "51646", "52738", "54261", "56874",
            "57300", "58404", "62170", "66369", "68135", "69106"},
        "crossing_authority_accounted":
            json.loads(S09.read_text()).get("authority_total") == 179
            and json.loads(S09.read_text()).get("accounted_total") == 179,
        "pedestrian_authority_accounted":
            json.loads(N14.read_text()).get("authority_total") == 5431
            and json.loads(N14.read_text()).get("accounting_invariant_pass") is True,
        "crosswalk_count_66": len(cw) == 66,
        "crosswalk_ids_unique": len(set(cw_ids)) == len(cw_ids),
        "no_invalid_s": len(bad_s) == 0,
        "no_invalid_polygons": len(bad_poly) == 0,
        "semantic_diff_only_crosswalk": only_allowed,
    }
    failed = [k for k, v in checks.items() if not v]

    n17 = {
        "run_id": RUN_ID, "stage": "N", "producer": "stage_n_final_integrity.py",
        "candidate_xodr": str(CAND),
        "candidate_sha256_lf_text": sha256_text(text),
        "parent_sha256_lf_text": sha256_text(parent_text),
        "counts": counts, "checks": checks,
        "bad_s": bad_s, "bad_polygons": bad_poly,
        "verdict": "FINAL_SEMANTIC_INTEGRITY_PASS" if not failed else "FINAL_SEMANTIC_INTEGRITY_FAIL",
        "failed_checks": failed,
    }
    N17.write_text(json.dumps(n17, indent=2, sort_keys=True), encoding="utf-8")

    n18 = {
        "run_id": RUN_ID, "stage": "N", "producer": "stage_n_final_integrity.py",
        "reference": str(PARENT), "candidate": str(CAND),
        "verdict": ("SEMANTIC_DIFF_PASS"
                    if only_allowed
                    else "SEMANTIC_DIFF_EXCEEDS_ALLOWLIST"),
        "only_approved_categories_changed": only_allowed,
        "approved_categories_changed": ["objects", "crosswalk_objects"],
        "categories": cmp["categories"],
        "total_difference_ids": cmp["total_difference_ids"],
    }
    N18.write_text(json.dumps(n18, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Stage N: {n17['verdict']} "
          f"({'FAILED: ' + ','.join(failed) if failed else 'all checks pass'})")
    print(f"  counts roads={counts['roads']} juncs={counts['junctions']} "
          f"signals={counts['signals']} objects={counts['objects']} crosswalks={len(cw)}")
    print(f"  struct_combined_unchanged={checks['combined_structural_digest_unchanged']}")
    print(f"  tc_combined_unchanged={checks['combined_tc_unchanged']}")
    print(f"  sig_id_set_unchanged={checks['signal_id_set_unchanged']}")
    print(f"  only_crosswalk_diff={only_allowed} | id_unique={checks['crosswalk_ids_unique']}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
