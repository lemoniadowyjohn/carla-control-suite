#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage G replay: re-run the accepted Phase H enrichment onto the repaired
parent (ingolstadt_fixed_final.xodr).

The repaired candidate lost the Phase H signal layer (0 signals vs 3467 in the
accepted Phase H output).  Per governance this is not fixed by manual XML
pasting; the existing governed enrichment phase is replayed on the repaired
parent using the same OSM authority, matcher, writers, integrity audit and
idempotency gate.
"""
from __future__ import annotations

import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.tools.phase_h0_osm_signal_extract import OSMSignalExtractor
from ultimate_pipeline.tools.phase_h1_osm_road_match import match_candidate_to_roads
from ultimate_pipeline.tools.phase_h2_signal_writer import (
    remove_legacy_speeds,
    write_speed_limits,
    write_zone_signs,
    write_turn_lanes,
)
from ultimate_pipeline.tools.phase_h3_signal_integrity import audit_clean

PARENT = REPO_ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate" / "ingolstadt_fixed_final.xodr"
OSM_SOURCE = (
    REPO_ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "source"
    / "ingolstadt_authoritative.osm"
)
RUN_ID = "20260807T000000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID
OUTPUT = EVIDENCE_DIR / "candidate_g_semantic_enriched.xodr"

sys.setrecursionlimit(10000)


def _parse_args() -> tuple[Path, Path, str]:
    """Allow replaying Phase H onto an alternate parent (e.g. the corrected,
    length-invariant candidate) without overwriting the accepted chain.

    --parent PATH   parent XODR to enrich (default: ingolstadt_fixed_final.xodr)
    --out PATH      output XODR path (default: accepted candidate_g_semantic_enriched)
    --run-id ID     evidence run id / evidence dir name
    """
    global PARENT, OUTPUT, RUN_ID, EVIDENCE_DIR
    args = sys.argv[1:]
    if "--parent" in args:
        PARENT = Path(args[args.index("--parent") + 1]).resolve()
    if "--out" in args:
        OUTPUT = Path(args[args.index("--out") + 1]).resolve()
    if "--run-id" in args:
        RUN_ID = args[args.index("--run-id") + 1]
        EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID
    return PARENT, OUTPUT, RUN_ID


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    parent_path, out_path, run_id = _parse_args()
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    parent_text = PARENT.read_text(encoding="utf-8")
    parent_sha = sha256_text(parent_text)

    extractor = OSMSignalExtractor(str(OSM_SOURCE), str(PARENT))
    survey = extractor.extract()
    root = ET.fromstring(parent_text)

    legacy_removed = remove_legacy_speeds(root)
    candidates = survey["candidates"]
    matches = match_candidate_to_roads(root, candidates)
    matched = matches["matched"]
    for m in matched:
        m["s"] = max(0.0, min(m["s"], float(
            root.find(f"road[@id='{m['road_ids'][0]}']").get("length", "0"))))

    counters = {
        "requested": {
            "speed_limit": survey["counters"].get("speed_limit", 0),
            "zone_sign": survey["counters"].get("zone_sign", 0),
            "turn_lanes": survey["counters"].get("turn_lanes", 0),
            "controller": 0,
        },
        "matched": len(matched),
        "matched_roads": sum(m["roads_total"] for m in matched),
        "ambiguous": len(matches["ambiguous"]),
        "unmapped": len(matches["unmapped"]),
        "legacy_speed_removed": legacy_removed,
    }
    counters["speed_limits"] = write_speed_limits(root, candidates, matched)
    counters["zone_signs"] = write_zone_signs(root, candidates, matched)
    counters["turn_lanes"] = write_turn_lanes(root, candidates, matched)

    clone = ET.fromstring(ET.tostring(root))
    write_speed_limits(clone, candidates, matched)
    write_zone_signs(clone, candidates, matched)
    write_turn_lanes(clone, candidates, matched)
    idempotent = ET.tostring(clone, encoding="unicode") == ET.tostring(root, encoding="unicode")

    audit = audit_clean(root)
    integrity_ok = audit["clean"]

    out_text = ET.tostring(root, encoding="unicode")
    OUTPUT.write_text(out_text, encoding="utf-8")
    out_sha = sha256_text(out_text)

    from phase_q.semantic_evidence import extract_semantic_inventory, inventory_counts
    inv = extract_semantic_inventory(out_text)
    counts = inventory_counts(inv)

    verdict = "PHASE_H_REPLAY_PASS"
    if not integrity_ok:
        verdict = "PHASE_H_REPLAY_BLOCKED_INTEGRITY"
    elif not idempotent:
        verdict = "PHASE_H_REPLAY_BLOCKED_IDEMPOTENCY"
    if verdict == "PHASE_H_REPLAY_PASS" and str(parent_path) != str(
        (REPO_ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "candidate" / "ingolstadt_fixed_final.xodr").resolve()
    ):
        verdict = "PHASE_H_REPLAY_PASS_ON_CORRECTED_PARENT"

    report = {
        "run_id": run_id,
        "producer": "replay_phase_h_on_repaired.py",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "parent": str(parent_path),
        "parent_sha256": parent_sha,
        "output": str(out_path),
        "output_sha256": out_sha,
        "crs_verdict": survey["crs_verdict"],
        "counters": counters,
        "idempotent": idempotent,
        "integrity_clean": integrity_ok,
        "integrity": {k: len(v) for k, v in audit.items() if isinstance(v, list)},
        "semantic_inventory": counts,
        "h_replay_verdict": verdict,
    }
    (EVIDENCE_DIR / "G_REPLAY_PHASE_H.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"G replay verdict: {verdict}")
    print(f"signals={counts.get('signals', 0)} speed_limits={counts.get('speed_limits', 0)}")
    print(OUTPUT)
    return 0 if verdict in ("PHASE_H_REPLAY_PASS", "PHASE_H_REPLAY_PASS_ON_CORRECTED_PARENT") else 1


if __name__ == "__main__":
    raise SystemExit(main())
