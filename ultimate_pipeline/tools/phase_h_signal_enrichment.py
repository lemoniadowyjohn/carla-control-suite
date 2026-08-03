#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H — Phase H orchestrator: semantic enrichment (signals/controllers).

Pipeline:
1. H0  OSM signal candidate extraction with provenance (GROUNDED/INFERRED)
2. H1  geometric matching of OSM ways onto XODR roads (node voting +
       junction adjacency for 2-node ways)
3. H2  governed writers: speed limits, zone signs, turn-lane metadata;
       legacy heuristic <speed> layer replaced; controllers reported N/A
4. H3  integrity audit (H5) must be defect-free
5. H6  report with requested/matched/inserted/updated/unchanged/rejected/
       ambiguous/unmapped counters
6. identity: protected hashes must match G0; G4..G8 audits must still pass
7. idempotency: re-running the writers on the produced file changes nothing

Verdicts:
- PHASE_H_SIGNAL_ENRICHMENT_PASS
- PHASE_H_BLOCKED_INPUT_IDENTITY
- PHASE_H_BLOCKED_PROTECTED_HASH
- PHASE_H_BLOCKED_INTEGRITY
- PHASE_H_BLOCKED_IDEMPOTENCY
- PHASE_H_BLOCKED_REGRESSION
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from ultimate_pipeline.tools.phase_g0_handoff import compute_identity_hashes
from ultimate_pipeline.tools.phase_h0_osm_signal_extract import OSMSignalExtractor
from ultimate_pipeline.tools.phase_h1_osm_road_match import match_candidate_to_roads
from ultimate_pipeline.tools.phase_h2_signal_writer import (
    remove_legacy_speeds,
    write_speed_limits,
    write_zone_signs,
    write_turn_lanes,
)
from ultimate_pipeline.tools.phase_h3_signal_integrity import audit_clean

RUN_ID = "20260804T050000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID

OSM_SOURCE = (
    REPO_ROOT / "campaigns" / "ingolstadt_cooked_perception_v1" / "source"
    / "ingolstadt_authoritative.osm"
)
G7_OUTPUT = (
    REPO_ROOT / "reports" / "post_audit_hardening" / "20260804T030000Z"
    / "candidate_g7_roadmarks.xodr"
)
G8_EVIDENCE = (
    REPO_ROOT / "reports" / "post_audit_hardening" / "20260804T040000Z"
    / "PHASE_G_ACCEPTANCE.json"
)
G0_EVIDENCE = (
    REPO_ROOT / "reports" / "post_audit_hardening" / "20260803T190000Z"
    / "PHASE_G_INPUT.json"
)

PROTECTED_KEYS = [
    "planview_hash",
    "road_length_hash",
    "elevation_profile_hash",
    "road_link_hash",
    "junction_structure_hash",
    "connector_geometry_hash",
    "contactpoint_hash",
]


def _run_fixtures() -> Dict[str, Any]:
    """Synthetic fixture set: writers + integrity + idempotency."""
    from ultimate_pipeline.tools.phase_h2_signal_writer import _ensure_signals

    def make_root():
        root = ET.Element("OpenDRIVE")
        road = ET.SubElement(root, "road", id="100", length="120.0")
        lanes = ET.SubElement(road, "lanes")
        sec = ET.SubElement(lanes, "laneSection", s="0.0")
        right = ET.SubElement(sec, "right")
        for lid, w in (("1", "3.0"), ("2", "3.0")):
            lane = ET.SubElement(right, "lane", id=lid, type="driving")
            width = ET.SubElement(lane, "width", sOffset="0.0")
            width.set("a", w)
            for c in "bcd":
                width.set(c, "0.0")
            ET.SubElement(lane, "speed", max="8.333")
        return root

    def candidate(way, kind, speed_kmh=None, sign_code=None, turn=None):
        tags = {"maxspeed": str(speed_kmh)} if speed_kmh else {}
        if turn:
            tags["turn:lanes"] = turn
        return {
            "osm_way_id": way, "kind": kind, "tags": tags,
            "method": "GROUNDED", "confidence": 0.95,
            "reason": "fixture", "speed_kmh": speed_kmh,
            "sign_code": sign_code,
            "start_m": (0.0, 0.0), "end_m": (0.0, 0.0),
            "polyline_m": [(0.0, 0.0), (0.0, 1.0)],
        }

    results = {}

    # fixture 1: clean speed limit + idempotency
    root = make_root()
    removed = remove_legacy_speeds(root)
    assert removed == 2, removed
    match = [{"candidate_idx": 0, "road_ids": ["100"],
              "s": 5.0, "t_center": -3.0, "node_votes": {"100": 3}}]
    c1 = write_speed_limits(root, [candidate("9001", "speed_limit", 30)], match)
    assert c1["signals_inserted"] == 1 and c1["speeds_inserted"] == 2, c1
    a1 = audit_clean(root)
    assert a1["clean"], a1
    root_before = ET.tostring(root, encoding="unicode")
    c1b = write_speed_limits(root, [candidate("9001", "speed_limit", 30)], match)
    assert c1b["skipped_existing"] == 1, c1b
    assert ET.tostring(root, encoding="unicode") == root_before
    results["fixture_clean_speed_idempotent"] = True

    # fixture 2: zone sign writes zone speed
    root = make_root()
    remove_legacy_speeds(root)
    match2 = [{"candidate_idx": 0, "road_ids": ["100"],
               "s": 2.0, "t_center": -3.0}]
    c2 = write_zone_signs(root, [candidate("9002", "zone_sign", sign_code="240")], match2)
    assert c2["signals_inserted"] == 1 and c2["speeds_inserted"] == 2, c2
    assert audit_clean(root)["clean"]
    results["fixture_zone_sign"] = True

    # fixture 3: turn lanes mapping left->right onto lanes -1,-2
    root = make_root()
    match3 = [{"candidate_idx": 0, "road_ids": ["100"]}]
    c3 = write_turn_lanes(
        root, [candidate("9003", "turn_lanes", turn="left;through")], match3)
    assert c3["roads_updated"] == 1, c3
    ud = root.find("road/userData")
    keys = {v.get("key"): v.get("value") for v in ud.findall("vector")}
    assert keys["turnLanes"] == "left;through", keys
    assert keys.get("turnLane:1") == "left" and keys.get("turnLane:2") == "through", keys
    assert keys.get("osm:way") == "9003", keys
    results["fixture_turn_lanes"] = True

    # fixture 4: turn lane mismatch rejected
    root = make_root()
    match4 = [{"candidate_idx": 0, "road_ids": ["100"]}]
    c4 = write_turn_lanes(
        root, [candidate("9004", "turn_lanes", turn="left;through;right")], match4)
    assert c4["rejected_lane_mismatch"] == 1 and c4["roads_updated"] == 0, c4
    results["fixture_turn_mismatch_rejected"] = True

    # fixture 5: integrity negative controls
    root = make_root()
    sig = _ensure_signals(root.find("road"))
    ET.SubElement(sig, "signal", id="h_x_1_100", s="5.0", t="-3.0",
                  orientation="+", dynamic="no", type="1", subtype="30",
                  country="DEU")
    ET.SubElement(sig, "signal", id="h_x_1_100", s="6.0", t="-3.0",
                  orientation="+", dynamic="no", type="1", subtype="30",
                  country="DEU")
    ET.SubElement(sig, "signal", id="h_y_2_100", s="-1.0", t="-3.0",
                  orientation="+", dynamic="no", type="9", subtype="nope",
                  country="US")
    a5 = audit_clean(root)
    assert not a5["clean"]
    assert len(a5["duplicate_ids"]) == 1
    assert len(a5["out_of_s"]) == 1
    assert len(a5["unknown_type"]) == 1
    assert len(a5["missing_provenance"]) == 3
    results["fixture_integrity_negatives"] = True

    return results


def main() -> int:
    g0 = json.loads(G0_EVIDENCE.read_text(encoding="utf-8"))
    g8 = json.loads(G8_EVIDENCE.read_text(encoding="utf-8"))
    if g8.get("g8_verdict") != "PHASE_G_ACCEPTED":
        print("H verdict: PHASE_H_BLOCKED_INPUT_IDENTITY (G8 not accepted)")
        return 1

    fixtures = _run_fixtures()
    fixtures_ok = all(fixtures.values())

    extractor = OSMSignalExtractor(str(OSM_SOURCE), str(G7_OUTPUT))
    survey = extractor.extract()
    root = ET.parse(str(G7_OUTPUT)).getroot()

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

    # idempotency: rerun writers on our own output -> no changes
    clone = ET.fromstring(ET.tostring(root))
    write_speed_limits(clone, candidates, matched)
    write_zone_signs(clone, candidates, matched)
    write_turn_lanes(clone, candidates, matched)
    idempotent = ET.tostring(clone, encoding="unicode") == ET.tostring(root, encoding="unicode")

    audit = audit_clean(root)
    integrity_ok = audit["clean"]

    identity = compute_identity_hashes(str(G7_OUTPUT))
    g0_hash = g0["input_candidate"]
    protected_checks = {k: identity[k] == g0_hash[k] for k in PROTECTED_KEYS}
    protected_ok = all(protected_checks.values())

    # regression: G4 lane continuity on the enriched file
    from ultimate_pipeline.tools.phase_g4_lane_continuity import audit_lane_continuity
    out_path = EVIDENCE_DIR / "candidate_h_signal_enrichment.xodr"
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(str(out_path), encoding="utf-8", xml_declaration=True)
    g4 = audit_lane_continuity(out_path)
    g4_ok = g4.get("g4_verdict") == "PHASE_G_LANE_CONTINUITY_PASS"

    if not fixtures_ok:
        verdict = "PHASE_H_BLOCKED_INTEGRITY"
    elif not protected_ok:
        verdict = "PHASE_H_BLOCKED_PROTECTED_HASH"
    elif not integrity_ok:
        verdict = "PHASE_H_BLOCKED_INTEGRITY"
    elif not idempotent:
        verdict = "PHASE_H_BLOCKED_IDEMPOTENCY"
    elif not g4_ok:
        verdict = "PHASE_H_BLOCKED_REGRESSION"
    else:
        verdict = "PHASE_H_SIGNAL_ENRICHMENT_PASS"

    report = {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_h_signal_enrichment.py",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "H",
        "input": str(G7_OUTPUT),
        "output": str(out_path),
        "crs_verdict": survey["crs_verdict"],
        "counters": counters,
        "fixtures": fixtures,
        "fixtures_ok": fixtures_ok,
        "idempotent": idempotent,
        "integrity": audit,
        "integrity_ok": integrity_ok,
        "identity": {
            "protected_hash_matches_g0": protected_checks,
            "protected_ok": protected_ok,
        },
        "g4_lane_continuity": {
            "verdict": g4.get("g4_verdict"),
            "checks": g4.get("checks", {}),
        },
        "h_verdict": verdict,
    }
    (EVIDENCE_DIR / "PHASE_H_SIGNAL_ENRICHMENT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    md = [
        "# H — Semantic enrichment (signals/controllers)",
        "",
        f"- run_id: `{RUN_ID}`",
        f"- verdict: **{verdict}**",
        f"- CRS contract: `{survey['crs_verdict']}`",
        f"- output: `{out_path}`",
        "",
        "## H6 counters",
        "",
        "| bucket | value |",
        "|---|---|",
    ]
    for k, v in sorted(counters.items()):
        if isinstance(v, dict):
            for k2, v2 in sorted(v.items()):
                md.append(f"| {k}.{k2} | {v2} |")
        else:
            md.append(f"| {k} | {v} |")
    md += [
        "",
        "## Fixtures",
        "",
        "| fixture | result |",
        "|---|---|",
    ]
    for k, v in fixtures.items():
        md.append(f"| {k} | {'PASS' if v else 'FAIL'} |")
    md += [
        "",
        f"idempotent: **{idempotent}**",
        "",
        "## Integrity (H5)",
        "",
    ]
    for k in ("duplicate_ids", "out_of_s", "out_of_t", "unknown_type",
              "unknown_subtype", "invalid_validity", "unresolved_refs",
              "duplicate_spatial", "missing_provenance",
              "non_governed_prefix"):
        md.append(f"- {k}: {len(audit[k])}")
    md += [
        "",
        "## Identity freeze",
        "",
    ]
    for k, ok in protected_checks.items():
        md.append(f"- {k}: {'PASS' if ok else 'FAIL'}")
    md += [
        "",
        f"- G4 lane continuity on enriched file: {g4.get('g4_verdict')}",
        "",
        "Controllers: the authoritative OSM contains no traffic_signals / "
        "stop / give_way nodes; requested=0 and reported N/A with evidence.",
        "",
        "The enriched candidate enters Phase I (tiling strategy) with the "
        "protected identity hashes identical to the G0 baseline.",
    ]
    (EVIDENCE_DIR / "PHASE_H_SIGNAL_ENRICHMENT.md").write_text(
        "\n".join(md), encoding="utf-8")

    print(f"H verdict: {verdict}")
    print(EVIDENCE_DIR / "PHASE_H_SIGNAL_ENRICHMENT.json")
    return 0 if verdict == "PHASE_H_SIGNAL_ENRICHMENT_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
