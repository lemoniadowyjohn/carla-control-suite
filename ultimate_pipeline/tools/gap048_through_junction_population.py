#!/usr/bin/env python3
"""
GAP-048 Phase 2: classify every broken driving lane in a stage-7 artifact.

Buckets partition the full broken population (sum check enforced):
  - reason: missing_successor | missing_link
  - section position: terminal(last laneSection) | intermediate
  - road-level successor type: junction | road | none
  - for elementType=junction: junction/connection/laneLink/target-existence funnel
  - for elementType=road: strategy-1 (lane id at boundary) applicability

Output: GAP048_THROUGH_JUNCTION_POPULATION.json
Policy: read-only analysis of the input artifact; never mutates it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sections(road: ET.Element) -> List[ET.Element]:
    secs = list(road.findall("./lanes/laneSection"))
    secs.sort(key=lambda e: float(e.get("s", "0") or 0.0))
    return secs


def _driving_ids(section: ET.Element) -> Set[str]:
    out: Set[str] = set()
    for side in ("left", "right"):
        side_elem = section.find(side)
        if side_elem is None:
            continue
        for lane in side_elem.findall("lane"):
            if lane.get("type") == "driving":
                out.add(lane.get("id"))
    return out


def _road_successor(road: ET.Element) -> Optional[Tuple[str, str, str]]:
    link = road.find("link")
    if link is None:
        return None
    succ = link.find("successor")
    if succ is None:
        return None
    return (
        succ.get("elementType"),
        succ.get("elementId"),
        succ.get("contactPoint", "start"),
    )


def _lane_is_broken(lane: ET.Element, junction: str, road_succ: Optional[tuple]) -> Optional[str]:
    """Replicate check_lane_connectivity.find_broken_lanes_detailed per-lane rule."""
    link = lane.find("link")
    if link is None:
        if junction == "-1" and road_succ is None:
            return None
        return "missing_link"
    if link.find("successor") is None:
        if junction == "-1" and road_succ is None:
            return None
        return "missing_successor"
    return None


def classify(xodr_path: Path) -> Dict:
    tree = ET.parse(str(xodr_path))
    root = tree.getroot()
    roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}

    # Junction index: (incomingRoad, from_lane) -> {to_lane: [(connecting, contactPoint, junction_id)]}
    junc_candidates: Dict[Tuple[str, str], Dict[str, List[Tuple[str, str, str]]]] = defaultdict(lambda: defaultdict(list))
    junction_ids: Set[str] = set()
    for j in root.findall("junction"):
        jid = j.get("id")
        junction_ids.add(jid)
        for conn in j.findall("connection"):
            inc = conn.get("incomingRoad")
            con = conn.get("connectingRoad")
            cp = conn.get("contactPoint", "start")
            for ll in conn.findall("laneLink"):
                junc_candidates[(inc, ll.get("from"))][ll.get("to")].append((con, cp, jid))

    broken: List[Dict] = []
    bucket = Counter()
    junction_funnel = Counter()
    unambiguous_records: List[Dict] = []
    ambiguous_records: List[Dict] = []
    no_candidate_records: List[Dict] = []
    strategy1_records: List[Dict] = []

    for road_id, road in roads.items():
        junction_attr = road.get("junction", "-1")
        road_succ = _road_successor(road)
        secs = _sections(road)
        if not secs:
            continue
        n = len(secs)

        for idx, sec in enumerate(secs):
            is_terminal = idx == n - 1
            for side in ("left", "right"):
                side_elem = sec.find(side)
                if side_elem is None:
                    continue
                for lane in side_elem.findall("lane"):
                    if lane.get("type") != "driving":
                        continue
                    lane_id = lane.get("id")
                    reason = _lane_is_broken(lane, junction_attr, road_succ)
                    if reason is None:
                        continue

                    rec = {
                        "road_id": road_id,
                        "lane_id": lane_id,
                        "lane_section_index": idx,
                        "lane_section_s": sec.get("s"),
                        "road_junction_attr": junction_attr,
                        "reason": reason,
                        "section_position": "terminal" if is_terminal else "intermediate",
                        "road_successor_type": road_succ[0] if road_succ else "none",
                    }
                    broken.append(rec)
                    bucket["reason_" + reason] += 1
                    bucket["pos_terminal" if is_terminal else "pos_intermediate"] += 1
                    bucket["succ_" + (road_succ[0] if road_succ else "none")] += 1

                    if road_succ and road_succ[0] == "junction":
                        bucket["through_junction_total"] += 1
                        jid_target = road_succ[1]
                        if jid_target not in junction_ids:
                            junction_funnel["junction_element_missing"] += 1
                            rec["junction_funnel"] = "junction_element_missing"
                            continue
                        junction_funnel["junction_element_exists"] += 1
                        if not is_terminal:
                            junction_funnel["non_terminal_section"] += 1
                            rec["junction_funnel"] = "non_terminal_section"
                            continue
                        junction_funnel["terminal_section"] += 1
                        cands = junc_candidates.get((road_id, lane_id), {})
                        # validate each candidate to-id exists on its connecting road contact section
                        valid: Set[str] = set()
                        for to_id, occs in cands.items():
                            for (con, cp, _jid) in occs:
                                croad = roads.get(con)
                                if croad is None:
                                    continue
                                cs = _sections(croad)
                                if not cs:
                                    continue
                                csec = cs[0] if cp == "start" else cs[-1]
                                if to_id in _driving_ids(csec):
                                    valid.add(to_id)
                                    break
                        if not cands:
                            junction_funnel["no_laneLink_from_this_lane"] += 1
                            rec["junction_funnel"] = "no_laneLink_from_this_lane"
                            no_candidate_records.append(rec)
                        elif not valid:
                            junction_funnel["laneLink_target_invalid_on_connecting"] += 1
                            rec["junction_funnel"] = "laneLink_target_invalid_on_connecting"
                        elif len(valid) == 1:
                            junction_funnel["unambiguous_single_candidate"] += 1
                            rec["junction_funnel"] = "unambiguous_single_candidate"
                            rec["resolved_to_lane_id"] = next(iter(valid))
                            unambiguous_records.append(rec)
                        else:
                            junction_funnel["ambiguous_multiple_candidates"] += 1
                            rec["junction_funnel"] = "ambiguous_multiple_candidates"
                            rec["candidate_lane_ids"] = sorted(valid)
                            ambiguous_records.append(rec)

                    elif road_succ and road_succ[0] == "road":
                        bucket["strategy1_applicable_total"] += 1
                        target = roads.get(road_succ[1])
                        if target is None:
                            bucket["strategy1_target_road_missing"] += 1
                            rec["strategy1"] = "target_road_missing"
                        else:
                            ts = _sections(target)
                            cp = road_succ[2]
                            tsec = ts[0] if cp == "start" else (ts[-1] if ts else None)
                            if tsec is None:
                                bucket["strategy1_target_section_missing"] += 1
                                rec["strategy1"] = "target_section_missing"
                            elif lane_id in _driving_ids(tsec):
                                bucket["strategy1_lane_exists_at_boundary"] += 1
                                rec["strategy1"] = "lane_exists_at_boundary"
                                strategy1_records.append(rec)
                            else:
                                bucket["strategy1_lane_absent_at_boundary"] += 1
                                rec["strategy1"] = "lane_absent_at_boundary"
                    else:
                        bucket["road_succ_none_but_not_exempt"] += 1
                        rec["junction_funnel"] = "road_succ_none_but_not_exempt"

    total_broken = len(broken)
    # Partition checks
    sum_pos = bucket["pos_terminal"] + bucket["pos_intermediate"]
    sum_reason = bucket["reason_missing_successor"] + bucket["reason_missing_link"]
    sum_succ = (
        bucket["succ_junction"] + bucket["succ_road"] + bucket["succ_none"]
    )
    partition_ok = (sum_pos == total_broken) and (sum_reason == total_broken) and (sum_succ == total_broken)

    report = {
        "artifact": str(xodr_path),
        "artifact_sha256": _sha256(xodr_path),
        "broken_total": total_broken,
        "buckets": dict(bucket),
        "partition_ok": partition_ok,
        "partition": {
            "by_position": {"terminal": bucket["pos_terminal"], "intermediate": bucket["pos_intermediate"]},
            "by_reason": {
                "missing_successor": bucket["reason_missing_successor"],
                "missing_link": bucket["reason_missing_link"],
            },
            "by_road_successor": {
                "junction": bucket["succ_junction"],
                "road": bucket["succ_road"],
                "none": bucket["succ_none"],
            },
        },
        "junction_funnel": dict(junction_funnel),
        "through_junction_candidates": bucket["through_junction_total"],
        "through_junction_unambiguous": len(unambiguous_records),
        "through_junction_ambiguous": len(ambiguous_records),
        "through_junction_no_candidate": len(no_candidate_records),
        "unambiguous_records": unambiguous_records,
        "ambiguous_records": ambiguous_records[:200],
        "no_candidate_records": no_candidate_records[:200],
        "strategy1_records": strategy1_records[:200],
        "broken_records": broken,
    }
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="GAP-048 Phase 2 broken-lane population classifier")
    ap.add_argument("--xodr", required=True, help="Stage-7 (or later) XODR to classify (read-only)")
    ap.add_argument("--out", required=True, help="Output JSON report path")
    args = ap.parse_args(argv)

    xodr = Path(args.xodr)
    if not xodr.is_file():
        print(f"ERROR: input not found: {xodr}", file=sys.stderr)
        return 2
    report = classify(xodr)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"broken_total={report['broken_total']}")
    print(f"partition_ok={report['partition_ok']}")
    print(f"through_junction_candidates={report['through_junction_candidates']}")
    print(f"through_junction_unambiguous={report['through_junction_unambiguous']}")
    print(f"through_junction_ambiguous={report['through_junction_ambiguous']}")
    print(f"through_junction_no_candidate={report['through_junction_no_candidate']}")
    print(f"report -> {out}")
    return 0 if report["partition_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
