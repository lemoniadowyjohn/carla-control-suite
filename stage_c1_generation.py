#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C1 — regenerate the crosswalk-enriched candidate after C0 acceptance
(offline; no CARLA; no governance/promotion).

Contract (Claude C1 work order):
  PARENT   = candidate_g_semantic_enriched.xodr
             (sha256_lf_text d604ac393e12730ed276f5c865d0d3e7bff26e6d3b7)
             signals 3467, junctions 3646, roads 32710, provisional=false
  MUTATION = object:INSERT_OBJECT_CROSSWALK
             cornerLocal only; name in {crosswalk,crosswalk_marked,
             crosswalk_signals}; id=crosswalk_{osm_id}; parent hard-gate;
             crossings <= 179; 66 objects (61 INSERTED + 5 DUPLICATE_MERGED)

Evidence written under the C1 run dir:
  candidate_crosswalk_enriched.xodr      (C1 candidate, build A)
  C1A_CANDIDATE_LINEAGE.json             (parent sha -> candidate sha)
  C1B_CROSSING_DISPOSITION_LEDGER.json   (179 rows, dispositions, limit)
  C1C_PEDESTRIAN_LEDGER.json             (5431 rows, class dispositions)
  S:DETERMINISM_LEDGER.json               (buildA vs buildB sha)
  C1E_IDEMPOTENCY.json                    (rerun adds 0 semantics)
  C1F_PROTECTED_INTEGRITY.json            (13 categories + TC v2 vs parent)
"""
from __future__ import annotations

import csv
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO))

import stage_j_pedestrian_authority as stagej_mod  # noqa: E402
from stage_j_pedestrian_authority import (  # noqa: E402
    _is_pedestrian_way, _classify, _disposition, _crossing_disposition,
    _reason,
)

from ultimate_pipeline.enrichment.object_injector import (  # noqa: E402
    CrosswalkInjector, CrosswalkSpec,
)
from phase_q.common import sha256_text, XodrTree, strip_xml_namespaces  # noqa: E402
from phase_q.structural_digest import all_structural_digests  # noqa: E402
from phase_q.signal_digest import combined_traffic_control_digest  # noqa: E402
from phase_q.mutation_allowlist import (  # noqa: E402
    parent_hard_gate, effective_allowlist,
)
from phase_q.semantic_evidence import (  # noqa: E402
    extract_semantic_inventory, compare_inventories,
)

C1_RUN_ID = "20260809T000000Z_C1"
C1_RUN_DIR = REPO / "reports" / "post_audit_hardening" / "20260809T000000Z_C1_GENERATION"
C0_RUN_DIR = REPO / "reports" / "post_audit_hardening" / "20260807T000000Z"
PARENT_XODR = C0_RUN_DIR / "candidate_g_semantic_enriched.xodr"
CANDIDATE_A = C1_RUN_DIR / "candidate_crosswalk_enriched.xodr"
FROZEN_AUTHORITY = C0_RUN_DIR / "S03_SEMANTIC_PARENT_AUTHORITY.json"
FROZEN_STRUCT = C0_RUN_DIR / "S04_PROTECTED_STRUCTURAL_DIGESTS.json"
FROZEN_TC = C0_RUN_DIR / "S05_TRAFFIC_CONTROL_DIGESTS.json"
S07_AUTHORITY = C0_RUN_DIR / "S07_OSM_CROSSING_AUTHORITY.csv"
OSM_SOURCE = REPO / "campaigns" / "ingolstadt_cooked_perception_v1" / "source" / "ingolstadt_authoritative.osm"

LIMIT_CROSSINGS = 179
LIMIT_OBJECTS = 66


def _j(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _sig_id_set(root: ET.Element) -> set:
    return {sig.get("id") for sig in root.iter("signal") if sig.get("id") is not None}


def _build(specs: list, base_text: str):
    """Fresh deterministic writer run over a base XODR text."""
    root = ET.fromstring(strip_xml_namespaces(base_text))
    stats = CrosswalkInjector.inject(root, specs)
    out_text = '<?xml version="1.0" encoding="UTF-8"?>\n' + \
        ET.tostring(root, encoding="unicode")
    return stats, out_text, root


def _crossing_ledger() -> dict:
    """C1B: recompute the 179-crossing disposition ledger (authoritative CSV)."""
    led = []
    counts = {}
    with open(S07_AUTHORITY, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            disp = row["disposition"]
            counts[disp] = counts.get(disp, 0) + 1
            led.append({
                "osm_id": row["osm_id"],
                "disposition": disp,
                "reason": row.get("reason", ""),
                "object_id": f"crosswalk_{row['osm_id']}" if disp in (
                    "INSERTED", "DUPLICATE_MERGED") else "",
            })
    return {
        "producer": "stage_c1_generation.py (C1B)",
        "authority_total": len(led),
        "crossings_limit": LIMIT_CROSSINGS,
        "within_limit": len(led) <= LIMIT_CROSSINGS,
        "accounted_total": sum(counts.values()),
        "accounting_invariant": len(led) == sum(counts.values()),
        "disposition_counts": counts,
        "ledger": led,
    }


def _pedestrian_ledger() -> dict:
    """C1C: pedestrian authority ledger (5431 source ways)."""
    ext = stagej_mod.OSMSignalExtractor(
        str(OSM_SOURCE), str(PARENT_XODR))
    ext._load_nodes()
    ext._load_ways()

    rows = []
    for way_id, w in ext.ways.items():
        tags = w.get("tags", {})
        if not _is_pedestrian_way(tags):
            continue
        cls = _classify(tags)
        if cls == "CROSSING":
            disp, _ = _crossing_disposition(way_id)
        else:
            disp = _disposition(cls, False)
        rows.append({
            "osm_id": way_id,
            "classification": cls,
            "disposition": disp,
            "reason": _reason(cls, disp, way_id),
            "node_count": len(w.get("polyline_m", []) or []),
        })

    counts = {}
    cls_counts = {}
    for r in rows:
        counts[r["disposition"]] = counts.get(r["disposition"], 0) + 1
        cls_counts[r["classification"]] = cls_counts.get(r["classification"], 0) + 1
    return {
        "producer": "stage_c1_generation.py (stage_j recompute)",
        "authority_total": len(rows),
        "accounting_invariant": len(rows) == sum(counts.values()),
        "classification_counts": cls_counts,
        "disposition_counts": counts,
        "ledger": rows,
    }


def main() -> int:
    C1_RUN_DIR.mkdir(parents=True, exist_ok=True)

    parent_text = PARENT_XODR.read_text(encoding="utf-8", errors="replace")
    parent_sha = sha256_text(parent_text)

    frozen_auth = _j(FROZEN_AUTHORITY)
    frozen_struct = _j(FROZEN_STRUCT)["semantic_parent"]
    frozen_tc = _j(FROZEN_TC)
    gate = parent_hard_gate(parent_text, {
        "counts": frozen_auth["counts"],
        "semantic_parent": frozen_auth.get("semantic_parent"),
        "traffic_control": frozen_tc,
    })
    allow = effective_allowlist()
    if not gate.allowed or "object:INSERT_OBJECT_CROSSWALK" not in allow:
        print(f"C1: HARD FAIL parent gate: {gate.reasons}", file=sys.stderr)
        return 1

    # specs from the accepted crossing authority (INSERTED + DUPLICATE_MERGED)
    specs = {}
    with open(S07_AUTHORITY, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["disposition"] not in ("INSERTED", "DUPLICATE_MERGED"):
                continue
            roads = json.loads(row["road_ids"])
            specs[row["osm_id"]] = CrosswalkSpec(
                osm_id=row["osm_id"],
                crossing_type=row["crossing_type"],
                start_m=tuple(json.loads(row["start_m"])),
                end_m=tuple(json.loads(row["end_m"])),
                road_id=(roads or [None])[0],
                s=float(row["s"]) if row["s"] not in ("", "None") else 0.0,
                t=float(row["t"]) if row["t"] not in ("", "None") else 0.0,
                road_ids_all=tuple(roads),
                disposition=row["disposition"],
                reason=row.get("reason", ""),
            )
    spec_list = list(specs.values())

    # ---- C1.1 build A (authoritative) ----
    stats_a, cand_a_text, cand_a_root = _build(spec_list, parent_text)
    CANDIDATE_A.write_text(cand_a_text, encoding="utf-8")
    sha_a = sha256_text(cand_a_text)

    # ---- C1.5 build B: determinism ----
    stats_b, cand_b_text, _ = _build(spec_list, parent_text)
    sha_b = sha256_text(cand_b_text)
    determinism = {
        "build_a_sha256_lf": sha_a,
        "build_b_sha256_lf": sha_b,
        "identical": sha_a == sha_b,
        "stats_equal": {
            "a": stats_a, "b": stats_b,
        },
    }
    (C1_RUN_DIR / "C1D_DETERMINISM.json").write_text(
        json.dumps(determinism, indent=2, sort_keys=True), encoding="utf-8")

    # ---- C1.5 idempotency: rerun over the build A output ----
    stats_idem, cand_re_text, _ = _build(spec_list, cand_a_text)
    idem_sha = sha256_text(cand_re_text)
    idem = {
        "rerun_written": stats_idem["written"],
        "rerun_skipped_existing": stats_idem["skipped_existing"],
        "sha_unchanged": idem_sha == sha_a,
        "sha256_after_rerun": idem_sha,
    }
    (C1_RUN_DIR / "C1E_IDEMPOTENCY.json").write_text(
        json.dumps(idem, indent=2, sort_keys=True), encoding="utf-8")

    # ---- protected integrity recompute ----
    out_struct = all_structural_digests(cand_a_text)
    out_tc = combined_traffic_control_digest(XodrTree(cand_a_text))
    out_sig_ids = _sig_id_set(cand_a_root)
    parent_inv = extract_semantic_inventory(parent_text)
    child_inv = extract_semantic_inventory(cand_a_text)
    cmp_res = compare_inventories(parent_inv, child_inv)
    expected_ids = {f"crosswalk_{k}" for k in specs}
    allowed_changed = {"objects", "crosswalk_objects"}
    other_diffs = {c: v for c, v in cmp_res["categories"].items()
                   if c not in allowed_changed}
    only_crosswalk_changed = all(v["equivalent"] for v in other_diffs.values())
    delta_exact = (
        set(cmp_res["categories"]["objects"]["unexpected_ids"]) == expected_ids
        and set(cmp_res["categories"]["crosswalk_objects"]["unexpected_ids"]) == expected_ids
        and cmp_res["categories"]["objects"]["missing_count"] == 0
        and cmp_res["categories"]["crosswalk_objects"]["missing_count"] == 0)

    corner_counts = {}
    corner_none = 0
    for o in cand_a_root.iter("object"):
        if (o.get("type") or "").lower() != "crosswalk":
            continue
        corner = o.findall("./outline/cornerLocal")
        corner_counts[o.get("id", "")] = len(corner)
        if len(corner) == 0:
            corner_none += 1

    integrity = {
        "parent_sha256_lf_text": parent_sha,
        "structural": {
            "combined_structural_digest": out_struct["combined_structural_digest"],
            "unchanged": (
                out_struct["combined_structural_digest"]
                == frozen_struct.get("combined_structural_digest")),
            "category_checks": {
                "planview": out_struct["planview_digest"] == frozen_struct.get(
                    "planview_digest"),
                "road_link": out_struct["road_link_digest"] == frozen_struct.get(
                    "road_link_digest"),
                "junction": out_struct["junction_digest"] == frozen_struct.get(
                    "junction_digest"),
                "lanelink": out_struct["lanelink_digest"] == frozen_struct.get(
                    "lanelink_digest"),
                "lanesection": out_struct["lanesection_digest"] == frozen_struct.get(
                    "lanesection_digest"),
                "elevation": out_struct["elevation_digest"] == frozen_struct.get(
                    "elevation_digest"),
                "superelevation_crossfall": out_struct.get(
                    "superelevation_crossfall_digest") == frozen_struct.get(
                    "superelevation_crossfall_digest"),
                "roadmark": out_struct.get("roadmark_digest") == frozen_struct.get(
                    "roadmark_digest"),
                "connector_repair": out_struct.get("connector_repair_digest")
                == frozen_struct.get("connector_repair_digest"),
            },
        },
        "traffic_control": {
            "combined": out_tc["combined_traffic_control_digest"],
            "unchanged": (
                out_tc["combined_traffic_control_digest"]
                == frozen_tc["combined_traffic_control_digest"]),
            "signal_element": {
                "digest": out_tc["signal_element_digest"],
                "unchanged": out_tc["signal_element_digest"] == frozen_tc["signal_element_digest"],
            },
            "signal_reference": {
                "digest": out_tc["signal_reference_digest"],
                "unchanged": out_tc["signal_reference_digest"] == frozen_tc["signal_reference_digest"],
            },
            "controller": {
                "digest": out_tc["controller_digest"],
                "unchanged": out_tc["controller_digest"] == frozen_tc["controller_digest"],
            },
        },
        "signal_id_set": {
            "parent_count": len(parent_inv.get("signals")),
            "candidate_count": len(out_sig_ids),
            "unchanged": out_sig_ids == parent_inv.get("signals"),
        },
        "semantic_inventory_delta": {
            "only_crosswalk_objects_changed": only_crosswalk_changed,
            "delta_is_exact": delta_exact,
            "crosswalk_objects_written": len(expected_ids),
        },
        "crosswalk_corners": {
            "objects_with_nonempty_cornerLocal": (
                len(corner_counts) - corner_none),
            "objects_with_empty_cornerLocal": corner_none,
            "per_object_corner_counts": corner_counts,
        },
    }
    (C1_RUN_DIR / "C1F_PROTECTED_INTEGRITY.json").write_text(
        json.dumps(integrity, indent=2, sort_keys=True), encoding="utf-8")

    # ---- C1.2 crossing ledger ----
    crossing = _crossing_ledger()
    (C1_RUN_DIR / "C1B_CROSSING_DISPOSITION_LEDGER.json").write_text(
        json.dumps(crossing, indent=2, sort_keys=True), encoding="utf-8")

    # ---- C1.3 pedestrian ledger ----
    pedestrian = _pedestrian_ledger()
    (C1_RUN_DIR / "C1C_PEDESTRIAN_LEDGER.json").write_text(
        json.dumps(pedestrian, indent=2, sort_keys=True), encoding="utf-8")

    # ---- C1A lineage ----
    lineage = {
        "producer": "stage_cc + object_injector + allowed mutation",
        "run_id": C1_RUN_ID,
        "parent": {
            "path": str(PARENT_XODR),
            "sha256_lf_text": parent_sha,
            "signals": frozen_auth["counts"]["signals"],
            "junctions": frozen_auth["counts"]["junctions"],
            "roads": frozen_auth["counts"]["roads"],
            "provisional": frozen_auth.get("semantic_parent", {}).get("provisional"),
        },
        "candidate": {
            "path": str(CANDIDATE_A),
            "sha256_lf_text": sha_a,
            "crosswalk_objects": len(corner_counts),
            "specs": len(spec_list),
        },
        "gate": gate.as_dict(),
        "verdict": "C1_CANDIDATE_GENERATED",
    }
    (C1_RUN_DIR / "C1A_CANDIDATE_LINEAGE.json").write_text(
        json.dumps(lineage, indent=2, sort_keys=True), encoding="utf-8")

    print("C1: candidate generated")
    print(f"  parent sha256_lf   = {parent_sha}")
    print(f"  candidate sha256_lf= {sha_a}")
    print(f"  determinism        = {sha_a == sha_b} (buildB {sha_b[:12]}...)")
    print(f"  idempotency        = {idem['sha_unchanged']} "
          f"(rerun_written {idem['rerun_written']})")
    print(f"  crossing_total     = {crossing['authority_total']} "
          f"within_limit {crossing['within_limit']}")
    print(f"  pedestrian_total   = {pedestrian['authority_total']}")
    print(f"  protected: struct={integrity['structural']['unchanged']} "
          f"tc={integrity['traffic_control']['unchanged']} "
          f"signal_ids={integrity['signal_id_set']['unchanged']} "
          f"corners_empty={integrity['crosswalk_corners']['objects_with_empty_cornerLocal']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())