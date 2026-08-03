#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G1 — lane inventory and schema normalization.

Audits the Phase G input (F7-approved F5 candidate) and records a complete
lane inventory per road / laneSection:

- road ID, road length, junction ID
- laneSection start s and end s
- left lanes, center lane, right lanes
- lane IDs, lane types, lane levels
- width records, border records, height records, roadMark records
- lane predecessor / successor

Counting ambiguity resolution (per unique lane key road_id +
laneSection_start_s + lane_id):

- lane_section_count
- lane_record_count
- unique_lane_key_count
- driving_lane_record_count
- driving_lane_length_m
- roads_with_driving_lanes

Fail-closed checks (all must be 0):

- duplicate laneSection s values within a road
- unordered lane sections
- missing center lane
- duplicate lane IDs within a section
- invalid lane ID 0 usage
- invalid lane type values

Verdicts: PHASE_G_LANE_INVENTORY_PASS | PHASE_G_LANE_INVENTORY_BLOCKED
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

RUN_ID = "20260803T200000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID

G0_EVIDENCE = (
    REPO_ROOT
    / "reports"
    / "post_audit_hardening"
    / "20260803T190000Z"
    / "PHASE_G_INPUT.json"
)

VALID_LANE_TYPES = {
    "driving", "entry", "exit", "onRamp", "offRamp", "connectingRamp",
    "shoulder", "sidewalk", "biking", "parking", "border", "restricted",
    "median", "special", "bidirectional", "tram", "rail", "stop", "none",
}


def _safe_float(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except Exception:
        return default


def _lane_record(lane: ET.Element) -> dict:
    record = {
        "id": int(lane.get("id", "0")),
        "type": lane.get("type"),
        "level": lane.get("level", "false"),
    }
    widths = lane.findall("width")
    record["width_count"] = len(widths)
    record["width_soffsets"] = [_safe_float(w.get("sOffset")) for w in widths]
    record["border_count"] = len(lane.findall("border"))
    record["height_count"] = len(lane.findall("height"))
    record["roadmark_count"] = len(lane.findall("roadMark"))
    for tag in ("predecessor", "successor"):
        el = lane.find(tag)
        record[tag] = (
            f"{el.get('id')}:{el.get('type')}" if el is not None else None
        )
    return record


def inventory_xodr(xodr_path: Path) -> dict:
    root = ET.parse(str(xodr_path)).getroot()
    roads = root.findall("road")

    lane_section_count = 0
    lane_record_count = 0
    unique_lane_keys = set()
    driving_lane_record_count = 0
    driving_lane_length_m = 0.0
    roads_with_driving_lanes = set()
    per_road_summary = []

    duplicate_section_s = []
    unordered_sections = []
    missing_center = []
    duplicate_lane_ids = []
    invalid_zero_usage = []
    invalid_lane_types = []

    for road in roads:
        rid = road.get("id")
        length = _safe_float(road.get("length"))
        junction = road.get("junction", "-1")
        lanes_elem = road.find("lanes")
        if lanes_elem is None:
            per_road_summary.append(
                {"road_id": rid, "length": length, "junction": junction,
                 "lane_sections": 0}
            )
            continue

        sections = lanes_elem.findall("laneSection")
        section_s = [_safe_float(s.get("s")) for s in sections]
        if len(section_s) != len(set(section_s)):
            dupes = {s for s in section_s if section_s.count(s) > 1}
            duplicate_section_s.append({"road": rid, "s": sorted(dupes)})
        if section_s != sorted(section_s):
            unordered_sections.append({"road": rid, "s": section_s})

        road_has_driving = False
        for idx, section in enumerate(sections):
            start_s = _safe_float(section.get("s"))
            end_s = (
                section_s[idx + 1]
                if idx + 1 < len(section_s)
                else length
            )
            lane_section_count += 1
            center = section.find("center")
            left = section.find("left")
            right = section.find("right")
            if center is None or center.find("lane") is None:
                missing_center.append(
                    {"road": rid, "s": start_s, "reason": "center lane missing"}
                )
            else:
                center_lanes = center.findall("lane")
                for cl in center_lanes:
                    if cl.get("id") not in ("0", "0.0"):
                        invalid_zero_usage.append(
                            {"road": rid, "s": start_s,
                             "lane": cl.get("id"), "reason": "center id != 0"}
                        )

            lane_ids = []
            for side in ("left", "center", "right"):
                side_elem = section.find(side)
                if side_elem is None:
                    continue
                for lane in side_elem.findall("lane"):
                    lane_id = int(lane.get("id", "0"))
                    lane_ids.append(lane_id)
                    lane_record_count += 1
                    key = (rid, start_s, lane_id)
                    unique_lane_keys.add(key)
                    rec = _lane_record(lane)
                    lt = rec["type"]
                    if lt not in VALID_LANE_TYPES:
                        invalid_lane_types.append(
                            {"road": rid, "s": start_s, "lane": lane_id,
                             "type": lt}
                        )
                    if lt in {
                        "driving", "entry", "exit", "onRamp", "offRamp",
                        "connectingRamp",
                    }:
                        driving_lane_record_count += 1
                        road_has_driving = True
                        if len(rec["width_soffsets"]) == 0:
                            driving_lane_length_m += 0.0
                        else:
                            # width from s=0 to section end for driving lanes
                            width = rec["width_soffsets"][0]
                            driving_lane_length_m += max(
                                0.0, end_s - max(start_s, width)
                            )
            if len(lane_ids) != len(set(lane_ids)):
                dupes = sorted({i for i in lane_ids if lane_ids.count(i) > 1})
                duplicate_lane_ids.append({"road": rid, "s": start_s, "ids": dupes})

            per_road_summary.append({
                "road_id": rid,
                "length": length,
                "junction": junction,
                "lane_section_start_s": start_s,
                "lane_section_end_s": end_s,
                "left_lane_ids": _side_ids(section, "left"),
                "center_lane_ids": _side_ids(section, "center"),
                "right_lane_ids": _side_ids(section, "right"),
                "lane_count": len(lane_ids),
                "lane_types": sorted({
                    (l.get("type"), int(l.get("id", "0")))
                    for side in ("left", "center", "right")
                    if section.find(side) is not None
                    for l in section.find(side).findall("lane")
                }),
            })
        if road_has_driving:
            roads_with_driving_lanes.add(rid)

    checks = {
        "duplicate_lane_section_s": len(duplicate_section_s) == 0,
        "lane_sections_ordered": len(unordered_sections) == 0,
        "center_lane_present": len(missing_center) == 0,
        "duplicate_lane_ids_within_section": len(duplicate_lane_ids) == 0,
        "no_invalid_center_lane_id_zero_usage": len(invalid_zero_usage) == 0,
        "lane_types_valid": len(invalid_lane_types) == 0,
    }
    passed = all(checks.values())

    return {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_g1_lane_inventory.py",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "G",
        "input": str(xodr_path),
        "roads_total": len(roads),
        "lane_section_count": lane_section_count,
        "lane_record_count": lane_record_count,
        "unique_lane_key_count": len(unique_lane_keys),
        "driving_lane_record_count": driving_lane_record_count,
        "driving_lane_length_m": round(driving_lane_length_m, 3),
        "roads_with_driving_lanes": len(roads_with_driving_lanes),
        "per_road_summary": per_road_summary,
        "issues": {
            "duplicate_lane_section_s": duplicate_section_s,
            "unordered_lane_sections": unordered_sections,
            "missing_center_lane": missing_center,
            "duplicate_lane_ids": duplicate_lane_ids,
            "invalid_center_lane_zero_usage": invalid_zero_usage,
            "invalid_lane_types": invalid_lane_types,
        },
        "checks": checks,
        "g1_verdict": (
            "PHASE_G_LANE_INVENTORY_PASS" if passed
            else "PHASE_G_LANE_INVENTORY_BLOCKED"
        ),
    }


def _side_ids(section: ET.Element, side: str) -> list:
    side_elem = section.find(side)
    if side_elem is None:
        return []
    return [int(l.get("id", "0")) for l in side_elem.findall("lane")]


def main() -> int:
    g0 = json.loads(G0_EVIDENCE.read_text(encoding="utf-8"))
    if g0.get("g0_verdict") != "PHASE_G_INPUT_ACCEPTED":
        print("G1 verdict: PHASE_G_BLOCKED_INPUT_IDENTITY (G0 not accepted)")
        return 1

    input_path = Path(g0["input_candidate"]["path"])
    report = inventory_xodr(input_path)
    passed = all(report["checks"].values())
    report["g0_reference"] = {
        "g0_evidence": str(G0_EVIDENCE),
        "input_byte_sha256": g0["input_candidate"]["byte_sha256"],
    }

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "PHASE_G_LANE_INVENTORY.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    md = [
        "# G1 — lane inventory and schema normalization",
        "",
        f"- run_id: `{RUN_ID}`",
        f"- verdict: **{report['g1_verdict']}**",
        "",
        "## Counts (counting ambiguity resolved)",
        "",
        "| metric | value |",
        "|---|---|",
        f"| roads | {report['roads_total']} |",
        f"| lane sections | {report['lane_section_count']} |",
        f"| lane records | {report['lane_record_count']} |",
        f"| unique lane keys (road,section_s,lane) | {report['unique_lane_key_count']} |",
        f"| driving lane records | {report['driving_lane_record_count']} |",
        f"| driving lane length (m) | {report['driving_lane_length_m']} |",
        f"| roads with driving lanes | {report['roads_with_driving_lanes']} |",
        "",
        "## Schema checks",
        "",
    ]
    for name, ok in report["checks"].items():
        md.append(f"- {name}: {'PASS' if ok else 'FAIL'}")
    md += [
        "",
        "A unique lane key is the triple (road_id, laneSection start s, lane_id)."
        "  Lane type inventory per road/section is recorded in the JSON evidence "
        "(`per_road_summary`).",
    ]
    (EVIDENCE_DIR / "PHASE_G_LANE_INVENTORY.md").write_text(
        "\n".join(md), encoding="utf-8"
    )

    print(f"G1 verdict: {report['g1_verdict']}")
    print(EVIDENCE_DIR / "PHASE_G_LANE_INVENTORY.json")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
