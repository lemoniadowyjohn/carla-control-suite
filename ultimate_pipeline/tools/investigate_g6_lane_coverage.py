#!/usr/bin/env python3
"""Offline G6 coverage/reachability investigation.

G6 coverage and acceptance reachability are different metrics.  This utility
captures the existing acceptance graph, identifies singleton driving lanes,
and intersects them with G6's ``missing_driving_from_coverage`` records.  It
never mutates its input; a repair candidate is written only outside the input
path when an overlap actually exists.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from ultimate_pipeline.quality import map_acceptance
from ultimate_pipeline.tools.phase_g6_junction_lanelinks import (
    audit_junction_lanelinks,
    repair_coverage_gaps,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def acceptance_component_details(root: ET.Element) -> Dict[str, Any]:
    """Return singleton nodes from the exact current acceptance graph.

    ``component_reachability_summary`` intentionally exposes only aggregate
    counts.  Capturing its local union-find is safer than maintaining a second
    graph implementation merely to expose the singleton identities.
    """
    original_union_find = map_acceptance._UnionFind

    class CapturingUnionFind(original_union_find):
        latest = None

        def __init__(self) -> None:
            super().__init__()
            type(self).latest = self

    map_acceptance._UnionFind = CapturingUnionFind
    try:
        summary = map_acceptance.component_reachability_summary(root)
        union_find = CapturingUnionFind.latest
    finally:
        map_acceptance._UnionFind = original_union_find
    if summary is None or union_find is None:
        raise RuntimeError("acceptance reachability graph was unavailable")

    components: Dict[str, list[str]] = defaultdict(list)
    for node in sorted(union_find._parent):
        components[union_find._find(node)].append(node)
    isolated = sorted(
        node for nodes in components.values() if len(nodes) == 1 for node in nodes
    )
    if len(isolated) != summary["isolated_lane_component_count"]:
        raise RuntimeError("captured component count disagrees with acceptance summary")
    return {**summary, "isolated_lane_nodes": isolated}


def _node_key(node: str) -> tuple[str, str]:
    road_id, _section_index, lane_id = node.rsplit(":", 2)
    return road_id, lane_id


def _audit_counts(audit: Dict[str, Any]) -> Dict[str, int]:
    return {
        name: len(audit[name])
        for name in (
            "missing_from_lanes",
            "missing_to_lanes",
            "duplicate_from_lanes",
            "missing_driving_from_coverage",
            "missing_driving_to_coverage",
            "type_incompatible_lanelinks",
            "lane_link_consistency_advisory",
        )
    }


def investigate(input_path: Path, output_dir: Path) -> Dict[str, Any]:
    """Measure G6 overlap, producing an external candidate only if it is real."""
    input_hash_before = sha256(input_path)
    root = ET.parse(input_path).getroot()
    audit_before = audit_junction_lanelinks(root)
    components_before = acceptance_component_details(root)
    coverage_keys = {
        (str(record["incoming"]), str(record["lane"]))
        for record in audit_before["missing_driving_from_coverage"]
    }
    overlap = [
        node
        for node in components_before["isolated_lane_nodes"]
        if _node_key(node) in coverage_keys
    ]
    report: Dict[str, Any] = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "input": {
            "path": str(input_path),
            "sha256_before": input_hash_before,
            "sha256_after": sha256(input_path),
        },
        "audit_before": _audit_counts(audit_before),
        "component_before": components_before,
        "overlap": {"isolated_lane_nodes": overlap, "count": len(overlap)},
        "repair": {"attempted": False, "reason": "no_overlap"},
    }
    report["input"]["unchanged"] = input_hash_before == report["input"]["sha256_after"]
    if not overlap:
        return report

    candidate_root = copy.deepcopy(root)
    repair = repair_coverage_gaps(candidate_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = output_dir / "g6_lane_coverage_candidate.xodr"
    ET.ElementTree(candidate_root).write(candidate_path, encoding="utf-8", xml_declaration=True)
    repaired_root = ET.parse(candidate_path).getroot()
    report["repair"] = {
        "attempted": True,
        "output_path": str(candidate_path),
        "sha256": sha256(candidate_path),
        "added_lanelinks": repair["added_lanelinks"],
        "repair_issues": repair["repair_issues"],
        "audit_after": _audit_counts(audit_junction_lanelinks(repaired_root)),
        "component_after": acceptance_component_details(repaired_root),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_xodr", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    report = investigate(args.input_xodr.resolve(), output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "G6_LANE_COVERAGE_INVESTIGATION.json"
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"report_path": str(output_path), "overlap": report["overlap"]["count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
