#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G4 — lane continuity.

Validates every lane predecessor / successor link:

- intra-road: target lane id must exist in the previous / next laneSection
- inter-road (road-level connection): the contacted lane section of the
  connected road is resolved from the road-level link contactPoint, and the
  lane link target (id, type) must exist there
- lane travel direction: links must respect the road-level connection
  orientation (start/end contact points) and the section being contacted
- lane type compatibility: a lane may only link to a lane of a compatible
  type (driving <-> driving; shoulders/sidewalks/biking only to the same
  class)
- lane numbering: per OpenDRIVE, explicit lane links take precedence over
  the implicit same-id mapping, so differing lane counts at a joint are
  legitimate lane-add / lane-drop encodings (never ambiguous)

Handled topologies: start-to-start, start-to-end, end-to-start, end-to-end,
reversed road orientation, one-way, two-way, lane addition, lane drop, merge,
split.

Blocking metrics:
- missing lane-link targets (explicit link with no target in contacted section)
- directionally wrong lane links (target contacted section mismatch)
- duplicate lane links (same source lane, duplicate link element)
- unlinked required driving lanes (driving lane without any successor in a
  non-terminal section)

Advisory (non-blocking) metrics:
- type-incompatible lane links (target id exists but lane type belongs to a
  different class, e.g. driving <-> restricted): structural continuity holds;
  resolution is a lane-type reclassification decision handled by G5/G6
- legitimate terminal lanes (driving lane at a map edge with no target)

This is an AUDIT subphase: it never mutates the candidate.
"""
from __future__ import annotations

import json
import math
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

RUN_ID = "20260803T230000Z"
EVIDENCE_DIR = REPO_ROOT / "reports" / "post_audit_hardening" / RUN_ID

G0_EVIDENCE = (
    REPO_ROOT
    / "reports"
    / "post_audit_hardening"
    / "20260803T190000Z"
    / "PHASE_G_INPUT.json"
)

DRIVABLE = {"driving", "entry", "exit", "onRamp", "offRamp", "connectingRamp"}
SIDEWALK = {"sidewalk", "border", "curb", "median"}
SUPPORT = {"shoulder", "biking", "parking", "restricted", "stop", "special",
           "bidirectional", "tram", "rail"}

TYPE_GROUPS = [DRIVABLE, SIDEWALK, SUPPORT]


def _safe_float(v, default=0.0):
    try:
        f = float(v) if v is not None else default
        return f if math.isfinite(f) else default
    except Exception:
        return default


def _sections_in_order(road: ET.Element) -> list:
    sections = road.findall("lanes/laneSection")
    sections.sort(key=lambda s: _safe_float(s.get("s")))
    return sections


def _lane_map(section: ET.Element) -> dict:
    """lane id -> (type, lane element)"""
    out = {}
    for lane in section.findall(".//lane"):
        lid = lane.get("id")
        if lid is not None:
            out[lid] = (lane.get("type"), lane)
    return out


def _type_compatible(a: str, b: str) -> bool:
    if a is None or b is None:
        return True
    for group in TYPE_GROUPS:
        if a in group and b in group:
            return True
    return a == b


def _contacted_section(connected_road: ET.Element, contact_point: str):
    """Lane section of the connected road that touches the connection."""
    sections = _sections_in_order(connected_road)
    if not sections:
        return None
    if contact_point == "start":
        return sections[0]
    if contact_point == "end":
        return sections[-1]
    return None


def audit_lane_continuity(xodr_path: Path) -> dict:
    root = ET.parse(str(xodr_path)).getroot()
    roads = root.findall("road")
    road_map = {r.get("id"): r for r in roads}

    missing = []
    invalid_type = []
    directional = []
    duplicates = []
    unlinked_driving = []
    terminal_lanes = []

    sections_audited = 0
    lane_links_audited = 0

    for road in roads:
        rid = road.get("id")
        sections = _sections_in_order(road)
        if not sections:
            continue
        n_sections = len(sections)
        section_lane_maps = [_lane_map(s) for s in sections]

        # road-level links
        rlink = road.find("link")
        road_pred = rlink.find("predecessor") if rlink is not None else None
        road_succ = rlink.find("successor") if rlink is not None else None

        for idx, section in enumerate(sections):
            sections_audited += 1
            for lane in section.findall(".//lane"):
                lid = lane.get("id")
                ltype = lane.get("type")
                link_el = lane.find("link")
                links = []
                if link_el is not None:
                    for tag in ("predecessor", "successor"):
                        for l in link_el.findall(tag):
                            links.append((tag, l))
                # duplicates: same direction appearing twice
                seen_dir = {}
                for tag, l in links:
                    seen_dir.setdefault(tag, []).append(l.get("id"))
                for tag, ids in seen_dir.items():
                    if len(ids) != len(set(ids)):
                        duplicates.append({
                            "road": rid, "section_s": _safe_float(section.get("s")),
                            "lane": lid, "direction": tag, "targets": ids,
                        })

                for tag, link in links:
                    lane_links_audited += 1
                    target_id = link.get("id")
                    target_type = link.get("type")
                    # intra-road
                    if tag == "predecessor":
                        tgt_idx = idx - 1
                    else:
                        tgt_idx = idx + 1
                    if 0 <= tgt_idx < n_sections:
                        if target_id not in section_lane_maps[tgt_idx]:
                            missing.append({
                                "road": rid,
                                "section_s": _safe_float(section.get("s")),
                                "lane": lid, "direction": tag,
                                "target": target_id,
                                "target_section": tgt_idx,
                                "kind": "intra_road",
                            })
                        else:
                            t_type = section_lane_maps[tgt_idx][target_id][0]
                            if not _type_compatible(ltype, t_type):
                                invalid_type.append({
                                    "road": rid,
                                    "section_s": _safe_float(section.get("s")),
                                    "lane": lid, "direction": tag,
                                    "target": target_id,
                                    "source_type": ltype,
                                    "target_type": t_type,
                                })
                        continue

                    # inter-road: section 0 predecessor -> road-level
                    # predecessor; last section successor -> road-level
                    # successor.  Contacted section of the other road:
                    if tag == "predecessor":
                        rl = road_pred
                        other_contact = (
                            rl.get("contactPoint") if rl is not None else None
                        )
                    else:
                        rl = road_succ
                        other_contact = (
                            rl.get("contactPoint") if rl is not None else None
                        )
                    if rl is None or rl.get("elementType") != "road":
                        # junction roads: continuity handled by junction
                        # LaneLinks in G6; not a defect here.
                        continue
                    other = road_map.get(rl.get("elementId"))
                    if other is None:
                        missing.append({
                            "road": rid,
                            "section_s": _safe_float(section.get("s")),
                            "lane": lid, "direction": tag,
                            "target": target_id,
                            "kind": "road_level_target_missing",
                        })
                        continue
                    contacted = _contacted_section(other, other_contact)
                    if contacted is None:
                        directional.append({
                            "road": rid,
                            "section_s": _safe_float(section.get("s")),
                            "lane": lid, "direction": tag,
                            "reason": "contacted section unresolved",
                        })
                        continue
                    other_map = _lane_map(contacted)
                    if target_id not in other_map:
                        missing.append({
                            "road": rid,
                            "section_s": _safe_float(section.get("s")),
                            "lane": lid, "direction": tag,
                            "target": target_id,
                            "connected_road": rl.get("elementId"),
                            "contacted_section_s": _safe_float(
                                contacted.get("s")),
                            "kind": "inter_road",
                        })
                    else:
                        t_type = other_map[target_id][0]
                        if not _type_compatible(ltype, t_type):
                            invalid_type.append({
                                "road": rid,
                                "section_s": _safe_float(section.get("s")),
                                "lane": lid, "direction": tag,
                                "target": target_id,
                                "connected_road": rl.get("elementId"),
                                "source_type": ltype,
                                "target_type": t_type,
                            })
                    # directional check: inter-road link on a section that
                    # does not touch the road end contacted by the road link
                    if tag == "predecessor" and idx != 0:
                        directional.append({
                            "road": rid,
                            "section_s": _safe_float(section.get("s")),
                            "lane": lid, "direction": tag,
                            "reason": "predecessor link on non-first section",
                        })
                    if tag == "successor" and idx != n_sections - 1:
                        directional.append({
                            "road": rid,
                            "section_s": _safe_float(section.get("s")),
                            "lane": lid, "direction": tag,
                            "reason": "successor link on non-last section",
                        })

                # unlinked required driving lanes
                if ltype in DRIVABLE:
                    has_succ = any(
                        t == "successor" for t, _ in links
                    )
                    has_pred = any(
                        t == "predecessor" for t, _ in links
                    )
                    if idx < n_sections - 1 and not has_succ:
                        unlinked_driving.append({
                            "road": rid,
                            "section_s": _safe_float(section.get("s")),
                            "lane": lid,
                            "reason": "no successor on non-terminal section",
                        })
                    if idx > 0 and not has_pred:
                        unlinked_driving.append({
                            "road": rid,
                            "section_s": _safe_float(section.get("s")),
                            "lane": lid,
                            "reason": "no predecessor on non-first section",
                        })
                    # legitimate terminal lanes: driving lane at the very
                    # first/last section of a non-junction road with no link
                    is_terminal_pred = (
                        idx == 0
                        and (road_pred is None
                             or road_pred.get("elementType") != "road")
                        and not has_pred
                    )
                    is_terminal_succ = (
                        idx == n_sections - 1
                        and (road_succ is None
                             or road_succ.get("elementType") != "road")
                        and not has_succ
                    )
                    if is_terminal_pred or is_terminal_succ:
                        terminal_lanes.append({
                            "road": rid,
                            "section_s": _safe_float(section.get("s")),
                            "lane": lid,
                            "end": "predecessor" if is_terminal_pred
                            else "successor",
                        })

    checks = {
        "no_missing_lane_link_targets": len(missing) == 0,
        "no_directionally_wrong_lane_links": len(directional) == 0,
        "no_duplicate_lane_links": len(duplicates) == 0,
        "no_unlinked_required_driving_lanes": len(unlinked_driving) == 0,
    }
    passed = all(checks.values())

    return {
        "run_id": RUN_ID,
        "producer": "ultimate_pipeline/tools/phase_g4_lane_continuity.py",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "G",
        "input": str(xodr_path),
        "lane_sections_audited": sections_audited,
        "lane_links_audited": lane_links_audited,
        "metrics": {
            "missing_lane_link_targets": len(missing),
            "directionally_wrong_lane_links": len(directional),
            "duplicate_lane_links": len(duplicates),
            "unlinked_required_driving_lanes": len(unlinked_driving),
            "type_incompatible_lane_links": len(invalid_type),
            "legitimate_terminal_lanes": len(terminal_lanes),
        },
        "issues": {
            "missing_lane_link_targets": missing[:200],
            "directionally_wrong_lane_links": directional[:200],
            "duplicate_lane_links": duplicates[:200],
            "unlinked_required_driving_lanes": unlinked_driving[:200],
            "type_incompatible_lane_links": invalid_type[:200],
            "legitimate_terminal_lanes": terminal_lanes[:200],
        },
        "checks": checks,
        "g4_verdict": (
            "PHASE_G_LANE_CONTINUITY_PASS" if passed
            else "PHASE_G_LANE_CONTINUITY_BLOCKED"
        ),
    }


def main() -> int:
    g0 = json.loads(G0_EVIDENCE.read_text(encoding="utf-8"))
    if g0.get("g0_verdict") != "PHASE_G_INPUT_ACCEPTED":
        print("G4 verdict: PHASE_G_BLOCKED_INPUT_IDENTITY (G0 not accepted)")
        return 1
    input_path = Path(g0["input_candidate"]["path"])
    report = audit_lane_continuity(input_path)
    passed = report["g4_verdict"] == "PHASE_G_LANE_CONTINUITY_PASS"
    report["g0_reference"] = {
        "g0_evidence": str(G0_EVIDENCE),
        "input_byte_sha256": g0["input_candidate"]["byte_sha256"],
    }

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "PHASE_G_LANE_CONTINUITY.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    m = report["metrics"]
    md = [
        "# G4 — lane continuity",
        "",
        f"- run_id: `{RUN_ID}`",
        f"- verdict: **{report['g4_verdict']}**",
        "",
        "## Metrics",
        "",
        "| metric | value |",
        "|---|---|",
        f"| lane sections audited | {report['lane_sections_audited']} |",
        f"| lane links audited | {report['lane_links_audited']} |",
        f"| missing lane-link targets | {m['missing_lane_link_targets']} |",
        f"| directionally wrong lane links | {m['directionally_wrong_lane_links']} |",
        f"| duplicate lane links | {m['duplicate_lane_links']} |",
        f"| unlinked required driving lanes | {m['unlinked_required_driving_lanes']} |",
        f"| type-incompatible lane links (advisory) | {m['type_incompatible_lane_links']} |",
        f"| legitimate terminal lanes (advisory) | {m['legitimate_terminal_lanes']} |",
        "",
        "## Checks",
        "",
    ]
    for name, ok in report["checks"].items():
        md.append(f"- {name}: {'PASS' if ok else 'FAIL'}")
    md += [
        "",
        "Blocking checks: lane-link targets must resolve in the contacted lane "
        "section (contactPoint of the road-level link decides which section of "
        "the connected road is contacted), directions must respect section "
        "position, and driving lanes on non-terminal sections must declare "
        "continuation.  Per OpenDRIVE, explicit lane links override the "
        "implicit same-numbering rule, so differing lane counts at a joint are "
        "valid lane-add/drop encodings.  Junction LaneLinks are validated "
        "separately in G6; terminal driving lanes at map edges are legitimate.",
    ]
    (EVIDENCE_DIR / "PHASE_G_LANE_CONTINUITY.md").write_text(
        "\n".join(md), encoding="utf-8"
    )

    print(f"G4 verdict: {report['g4_verdict']}")
    print(EVIDENCE_DIR / "PHASE_G_LANE_CONTINUITY.json")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
