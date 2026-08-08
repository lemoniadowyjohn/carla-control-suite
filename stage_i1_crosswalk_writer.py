#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage I.1 — deterministic crosswalk <object> insertion (canonical writer).

Extends ultimate_pipeline/enrichment/object_injector.py (the canonical
object_writing module, REUSE_UNCHANGED per N00) with CrosswalkInjector.
Read-only on inputs; additive on output:

  candidate_crosswalk_enriched.xodr  (+ N09/N10 evidence)

Mutation is strictly limited to adding <object type="crosswalk"> (+ <outline>/<cornerLocal>
u v z, the only corner form CARLA 0.9.16 ObjectParser reads — R05).
under existing <road><objects>. All structural + traffic-control digests MUST
remain identical to the frozen semantic parent (N01/N02/N03).

Contract: docs/N04_CLAUDE_C0_PACKET.md §5.1 (C0 defaults: option B multi-road,
sweep_width_m=4.0, id = crosswalk_{osm_id}, idempotent).
"""
from __future__ import annotations

import csv
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO))

from ultimate_pipeline.enrichment.object_injector import (
    CrosswalkInjector, CrosswalkSpec, CROSSWALK_DEFAULT_DEPTH_M,
)
from phase_q.common import sha256_text, XodrTree, strip_xml_namespaces
from phase_q.structural_digest import all_structural_digests
from phase_q.signal_digest import combined_traffic_control_digest
from phase_q.mutation_allowlist import parent_hard_gate, effective_allowlist
from phase_q.semantic_evidence import (
    extract_semantic_inventory, compare_inventories,
)

RUN_ID = "20260807T000000Z"
REPORTS = REPO / "reports" / "post_audit_hardening" / RUN_ID
AUTHORITY_CSV = REPORTS / "S07_OSM_CROSSING_AUTHORITY.csv"
SEMANTIC_PARENT = REPORTS / "candidate_g_semantic_enriched.xodr"
CANDIDATE = REPORTS / "candidate_crosswalk_enriched.xodr"
N09_LEDGER = REPORTS / "N09_CROSSWALK_MUTATION_LEDGER.csv"
N10 = REPORTS / "N10_POST_CROSSWALK_INTEGRITY.json"
FROZEN_AUTHORITY = REPORTS / "S03_SEMANTIC_PARENT_AUTHORITY.json"
FROZEN_STRUCT = REPORTS / "S04_PROTECTED_STRUCTURAL_DIGESTS.json"
FROZEN_TC = REPORTS / "S05_TRAFFIC_CONTROL_DIGESTS.json"


def _j(p):
    return json.loads(p.read_text(encoding="utf-8"))


def _load_authority_specs() -> list:
    specs = []
    with open(AUTHORITY_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["disposition"] not in ("INSERTED", "DUPLICATE_MERGED"):
                continue
            roads = json.loads(row["road_ids"])
            specs.append(CrosswalkSpec(
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
            ))
    return specs


def _sig_id_set(root: ET.Element) -> set:
    return {sig.get("id") for sig in root.iter("signal") if sig.get("id") is not None}


def main() -> int:
    if not AUTHORITY_CSV.exists() or not SEMANTIC_PARENT.exists():
        print("Stage I.1: missing authority CSV or semantic parent; run stage 0/1 + H first.",
              file=sys.stderr)
        return 2

    # ---- Parent hard gate (R13, fail-closed; single gate for ALL enrichment) ----
    frozen_auth = _j(FROZEN_AUTHORITY)
    gate_frozen = {
        "counts": frozen_auth["counts"],
        "semantic_parent": frozen_auth["semantic_parent"],
        "traffic_control": _j(FROZEN_TC),
    }
    parent_text = SEMANTIC_PARENT.read_text(encoding="utf-8", errors="replace")
    gate_result = parent_hard_gate(parent_text, gate_frozen)
    allowlist = effective_allowlist()
    if not gate_result.allowed or "object:INSERT_OBJECT_CROSSWALK" not in allowlist:
        print(f"Stage I.1: HARD FAIL - parent gate broken: {gate_result.reasons}",
              file=sys.stderr)
        return 1
    parent_sha = sha256_text(parent_text)
    frozen_counts = frozen_auth["counts"]

    parent_struct = _j(FROZEN_STRUCT)["semantic_parent"]
    frozen_tc = _j(FROZEN_TC)
    parent_tc_digest = frozen_tc["combined_traffic_control_digest"]
    parent_sig_element = frozen_tc["signal_element_digest"]
    parent_sig_ref = frozen_tc["signal_reference_digest"]
    parent_ctrl = frozen_tc["controller_digest"]

    # Idempotent base: resume from prior enriched output if present.
    base_path = CANDIDATE if CANDIDATE.exists() else SEMANTIC_PARENT
    base_text = base_path.read_text(encoding="utf-8", errors="replace")
    base_root = ET.fromstring(strip_xml_namespaces(base_text))

    specs = _load_authority_specs()
    stats = CrosswalkInjector.inject(base_root, specs)

    out_text = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(base_root, encoding="unicode")
    CANDIDATE.write_text(out_text, encoding="utf-8")

    # ---- N09 mutation ledger (ground truth from on-disk output) ----
    out_root = ET.fromstring(strip_xml_namespaces(out_text))
    written_objs = [o for o in out_root.iter("object")
                    if (o.get("type") or "").lower() == "crosswalk"]
    by_osmid = {s.osm_id: s for s in specs}
    with open(N09_LEDGER, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=[
            "object_id", "osm_id", "type", "name", "road_id", "road_ids_all",
            "s", "t", "hdg_deg", "depth_m", "disposition", "reason"])
        w.writeheader()
        for o in written_objs:
            oid = o.get("id", "")
            osm_id = oid.split("crosswalk_", 1)[-1] if oid.startswith("crosswalk_") else ""
            spec = by_osmid.get(osm_id)
            hdg = math.degrees(float(o.get("hdg", "0") or "0"))
            w.writerow({
                "object_id": oid, "osm_id": osm_id, "type": o.get("type"),
                "name": o.get("name"), "road_id": spec.road_id if spec else "",
                "road_ids_all": json.dumps(list(spec.road_ids_all)) if spec else "[]",
                "s": o.get("s"), "t": o.get("t"), "hdg_deg": round(hdg, 4),
                "depth_m": CROSSWALK_DEFAULT_DEPTH_M,
                "disposition": spec.disposition if spec else "",
                "reason": spec.reason if spec else "",
            })

    # ---- N10 post-crosswalk integrity ----
    out_struct = all_structural_digests(out_text)
    out_tc = combined_traffic_control_digest(XodrTree(out_text))
    parent_inv = extract_semantic_inventory(
        SEMANTIC_PARENT.read_text(encoding="utf-8", errors="replace"))
    child_inv = extract_semantic_inventory(out_text)
    cmp = compare_inventories(parent_inv, child_inv)
    allowed_changed = {"objects", "crosswalk_objects"}
    other_diffs = {c: v for c, v in cmp["categories"].items() if c not in allowed_changed}
    only_crosswalk_changed = all(v["equivalent"] for v in other_diffs.values())
    expected_ids = {f"crosswalk_{s.osm_id}" for s in specs}
    delta_is_exact = (
        set(cmp["categories"]["objects"]["unexpected_ids"]) == expected_ids
        and set(cmp["categories"]["crosswalk_objects"]["unexpected_ids"]) == expected_ids
        and cmp["categories"]["objects"]["missing_count"] == 0
        and cmp["categories"]["crosswalk_objects"]["missing_count"] == 0)
    out_sig_ids = _sig_id_set(out_root)

    n10 = {
        "run_id": RUN_ID, "stage": "I.1",
        "producer": "stage_i1_crosswalk_writer.py",
        "output_xodr": str(CANDIDATE),
        "output_sha256_lf_text": sha256_text(out_text),
        "parent_sha256_lf_text": parent_sha,
        "parent_hard_gate_pass": (
            parent_sha == frozen_auth["semantic_parent"]["sha256_lf_text"]
            and frozen_counts["signals"] == 3467
            and frozen_counts["roads"] == 32710
            and frozen_counts["junctions"] == 3646),
        "parent_hard_gate": gate_result.as_dict(),
        "inject_stats": stats,
        "crosswalk_objects_written_total": len(written_objs),
        "structural_integrity": {
            "combined_structural_digest_unchanged":
                out_struct["combined_structural_digest"] == parent_struct["combined_structural_digest"],
            "planview_unchanged": out_struct["planview_digest"] == parent_struct["planview_digest"],
            "road_link_unchanged": out_struct["road_link_digest"] == parent_struct["road_link_digest"],
            "junction_unchanged": out_struct["junction_digest"] == parent_struct["junction_digest"],
            "lanelink_unchanged": out_struct["lanelink_digest"] == parent_struct["lanelink_digest"],
            "lanesection_unchanged": out_struct["lanesection_digest"] == parent_struct["lanesection_digest"],
            "elevation_unchanged": out_struct["elevation_digest"] == parent_struct["elevation_digest"],
        },
        "traffic_control_integrity": {
            "combined_tc_unchanged": out_tc["combined_traffic_control_digest"] == parent_tc_digest,
            "signal_element_unchanged": out_tc["signal_element_digest"] == parent_sig_element,
            "signal_reference_unchanged": out_tc["signal_reference_digest"] == parent_sig_ref,
            "controller_unchanged": out_tc["controller_digest"] == parent_ctrl,
            "signal_id_set_unchanged": out_sig_ids == parent_inv.get("signals"),
            "parent_signal_count": len(parent_inv.get("signals")),
            "output_signal_count": len(out_sig_ids),
        },
        "semantic_inventory_delta": {
            "only_crosswalk_objects_changed": only_crosswalk_changed,
            "delta_is_exact": delta_is_exact,
            "crosswalk_objects_left_count": cmp["categories"]["crosswalk_objects"]["left_count"],
            "crosswalk_objects_right_count": cmp["categories"]["crosswalk_objects"]["right_count"],
            "crosswalk_objects_missing": cmp["categories"]["crosswalk_objects"]["missing_count"],
            "crosswalk_objects_unexpected": cmp["categories"]["crosswalk_objects"]["unexpected_count"],
            "other_categories_changed": {
                c: v for c, v in other_diffs.items() if not v["equivalent"]},
            "total_difference_ids": cmp["total_difference_ids"],
        },
        "verdict": (
            "CROSSWALK_MUTATION_INTEGRITY_PASS"
            if (only_crosswalk_changed and delta_is_exact
                and len(written_objs) == len(specs)
                and out_struct["combined_structural_digest"] == parent_struct["combined_structural_digest"]
                and out_tc["combined_traffic_control_digest"] == parent_tc_digest
                and out_sig_ids == parent_inv.get("signals"))
            else "CROSSWALK_MUTATION_INTEGRITY_FAIL"),
    }
    N10.write_text(json.dumps(n10, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Stage I.1: {n10['verdict']}")
    print(f"  written={stats['written']} existing_skip={stats['skipped_existing']} "
          f"no_road={stats['skipped_no_road']} total_crosswalk_objects={len(written_objs)}")
    print(f"  structural_combined_unchanged={n10['structural_integrity']['combined_structural_digest_unchanged']}")
    print(f"  tc_combined_unchanged={n10['traffic_control_integrity']['combined_tc_unchanged']}")
    print(f"  sig_id_set_unchanged={n10['traffic_control_integrity']['signal_id_set_unchanged']}")
    print(f"  only_crosswalk_changed={only_crosswalk_changed} delta_exact={delta_is_exact}")
    return 0 if n10["verdict"] == "CROSSWALK_MUTATION_INTEGRITY_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
