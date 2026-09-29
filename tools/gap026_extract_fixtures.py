"""Extract minimal deterministic GAP-026 lane-link fixtures from the pinned XODR."""
from __future__ import annotations

import argparse
import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map
from ultimate_pipeline.lanes.lanelink_builder import LaneLinkBuilder

CASES = [
    ("gap026_0_25_0_5", "12", "3", "47383", "54435", "-1", "-1"),
    ("gap026_1_3", "5", "1", "50230", "70937", "-1", "-1"),
    ("gap026_3_5", "1", "3", "42486", "52027", "-2", "-1"),
    ("gap026_5_10", "8", "2", "51971", "73103", "-3", "-1"),
    ("gap026_over_10", "411", "15", "47036", "69337", "-4", "-1"),
]


def extract(map_path: Path, output_dir: Path) -> list[dict[str, Any]]:
    source_root = ET.parse(map_path).getroot()
    roads = {str(r.get("id")): r for r in source_root.findall("road") if r.get("id")}
    junctions = {str(j.get("id")): j for j in source_root.findall("junction") if j.get("id")}
    results = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, jid, cid, incoming, connecting, from_id, to_id in CASES:
        if incoming not in roads or connecting not in roads or jid not in junctions:
            results.append({"fixture_id": name, "status": "INCOMPLETE", "reason": "source IDs not found"})
            continue
        root = ET.Element("OpenDRIVE", {"fixture_id": name, "source_map_sha256": ""})
        header = source_root.find("header")
        if header is not None:
            root.append(copy.deepcopy(header))
        for road_id in (incoming, connecting):
            road = copy.deepcopy(roads[road_id])
            root.append(road)
        junction = copy.deepcopy(junctions[jid])
        connection = next((c for c in junction.findall("connection") if c.get("id") == cid), None)
        if connection is None:
            results.append({"fixture_id": name, "status": "INCOMPLETE", "reason": f"connection {jid}/{cid} not found"})
            continue
        for child in list(junction):
            if child is not connection:
                junction.remove(child)
        for ll in list(connection.findall("laneLink")):
            if ll.get("from") != from_id or ll.get("to") != to_id:
                connection.remove(ll)
        root.append(junction)
        path = output_dir / f"{name}.xodr"
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
        result = LaneLinkBuilder.sanitize_junction_lane_links(ET.parse(path).getroot(), label=name)
        results.append({"fixture_id": name, "status": "PASS", "path": str(path), "junction_id": jid, "connection_id": cid, "incoming_road": incoming, "connecting_road": connecting, "from": from_id, "to": to_id, "summary_metrics": result["summary_metrics"], "failures": result["failures"]})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("tests/data/gap026_fixtures"))
    parser.add_argument("--report", type=Path, default=Path("GAP026_SEVERE_TAIL_FIXTURES.json"))
    args = parser.parse_args()
    pin = verify_pinned_map("auto_map_of_record")
    results = extract(Path(pin["resolved_path"]), args.out_dir)
    for result in results:
        result["source_map_sha256"] = pin["sha256"]
    payload = {"schema": "gap026_severe_tail_fixtures/v1", "status": "PASS" if all(r["status"] == "PASS" for r in results) else "INCOMPLETE", "source_map_sha256": pin["sha256"], "fixtures": results}
    args.report.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "fixtures": len(results)}, indent=2))
    return 0 if payload["status"] == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
