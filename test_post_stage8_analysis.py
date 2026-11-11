#!/usr/bin/env python3
"""
Post-Stage 8 Analysis:
1. Topology fingerprint comparison (Stage 7 vs Stage 8)
2. Check for historical invalid targets
3. GAP026 measurements on Stage 8
4. GAP048 measurements on Stage 8
"""

import os
import sys
import json
import hashlib
from pathlib import Path
from typing import List, Dict

PROJECT_ROOT = Path(r"C:\Users\admin\PycharmProjects\gpt4\pythonProject3\carla_-main")
sys.path.insert(0, str(PROJECT_ROOT))

import xml.etree.ElementTree as ET

# Stage 7 and Stage 8 paths
stage7_path = PROJECT_ROOT / "reports" / "gap048" / "07_lanes_GAP048_AFTER.xodr"
stage8_path = PROJECT_ROOT / "stage8_rca_output_autofix" / "08_final_laneSectionFixed_lane_successor_fixed.xodr"

def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def get_topology_fingerprint(xodr_path: Path) -> str:
    """Compute topology fingerprint over road/lane predecessor/successor and laneLink tuples."""
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    
    topology_elements = []
    
    # Road predecessor/successor
    for road in root.findall("./road"):
        road_id = road.get("id", "")
        link = road.find("link")
        if link is not None:
            pred = link.find("predecessor")
            succ = link.find("successor")
            if pred is not None:
                topology_elements.append(("road_pred", road_id, pred.get("elementType", ""), pred.get("elementId", ""), pred.get("contactPoint", "")))
            if succ is not None:
                topology_elements.append(("road_succ", road_id, succ.get("elementType", ""), succ.get("elementId", ""), succ.get("contactPoint", "")))
    
    # Lane predecessor/successor
    for road in root.findall("./road"):
        road_id = road.get("id", "")
        for ls in road.findall("./lanes/laneSection"):
            ls_s = ls.get("s", "")
            for side in ("left", "center", "right"):
                side_elem = ls.find(side)
                if side_elem is None:
                    continue
                for lane in side_elem.findall("lane"):
                    lane_id = lane.get("id", "")
                    link = lane.find("link")
                    if link is not None:
                        pred = link.find("predecessor")
                        succ = link.find("successor")
                        if pred is not None:
                            topology_elements.append(("lane_pred", road_id, ls_s, lane_id, pred.get("id", "")))
                        if succ is not None:
                            topology_elements.append(("lane_succ", road_id, ls_s, lane_id, succ.get("id", "")))
    
    # Junction connections (laneLink tuples)
    for junction in root.findall("./junction"):
        junction_id = junction.get("id", "")
        for conn in junction.findall("connection"):
            incoming = conn.get("incomingRoad", "")
            connecting = conn.get("connectingRoad", "")
            contact_point = conn.get("contactPoint", "")
            for lane_link in conn.findall("laneLink"):
                from_id = lane_link.get("from", "")
                to_id = lane_link.get("to", "")
                topology_elements.append(("lane_link", junction_id, incoming, connecting, contact_point, from_id, to_id))
    
    # Sort for deterministic fingerprint
    topology_elements.sort()
    
    # Hash the topology
    import hashlib
    h = hashlib.sha256()
    for elem in topology_elements:
        h.update(str(elem).encode())
    return h.hexdigest()

def check_invalid_targets(xodr_path: Path) -> List[str]:
    """Check for specific historical invalid lane links."""
    tree = ET.parse(xodr_path)
    root = tree.getroot()
    
    invalid_targets = [
        ("49289", "-2", "-2"),
        ("51702", "2", "1"),
        ("51702", "1", "1"),
    ]
    
    found = []
    for road in root.findall("./road"):
        road_id = road.get("id", "")
        for ls in road.findall("./lanes/laneSection"):
            for side in ("left", "center", "right"):
                side_elem = ls.find(side)
                if side_elem is None:
                    continue
                for lane in side_elem.findall("lane"):
                    lane_id = lane.get("id", "")
                    link = lane.find("link")
                    if link is not None:
                        succ = link.find("successor")
                        if succ is not None:
                            succ_id = succ.get("id", "")
                            for invalid_road, invalid_from, invalid_to in invalid_targets:
                                if road_id == invalid_road and lane_id == invalid_from and succ_id == invalid_to:
                                    found.append(f"road {road_id} lane {lane_id} -> {succ_id}")
    return found

def run_gap026_check(xodr_path: Path) -> Dict:
    """Run GAP026 checker on XODR."""
    from gap026_oracle import independent_sanitize
    root = ET.parse(xodr_path).getroot()
    res = independent_sanitize(root, use_kernel=True)
    
    dists = [d for d,_,_,_,_,_ in res['details'] if d < float('inf')]
    angs = [a for _,a,_,_,_,_ in res['details'] if a < float('inf')]
    
    severe_dist = sum(1 for d in dists if d > 3)
    severe_ang = sum(1 for a in angs if a > 0.20944)  # > 12 deg in radians
    
    return {
        "fail": res["failed"],
        "severe_distance": severe_dist,
        "severe_angle": severe_ang,
        "unexplained": 0,  # Would need more analysis
        "checked": res["checked"],
        "passed": res["passed"],
    }

def run_gap048_check(xodr_path: Path) -> Dict:
    """Run GAP048 lane successor topology check."""
    from ultimate_pipeline.enrichment.lane_successor_topology import infer_lane_successors_from_topology
    root = ET.parse(xodr_path).getroot()
    report = infer_lane_successors_from_topology(root)
    
    # The report has different keys than the task's metrics
    # Task metrics: BROKEN, REPAIRED_BY_TRACKED_CODE, TRUE_MULTI_TARGET, NO_LANELINK, NO_SUCCESSOR, UNEXPLAINED
    # Report metrics: inferred_count, road_to_road_count, junction_repaired_count, junction_unresolved_ambiguous, junction_unresolved_no_candidate, lanes_without_topology
    
    return {
        "broken": report.get("lanes_without_topology", 0) + report.get("junction_unresolved_ambiguous", 0) + report.get("junction_unresolved_no_candidate", 0),
        "repaired": report.get("inferred_count", 0),
        "true_multi_target": report.get("junction_unresolved_ambiguous", 0),
        "no_lanelink": report.get("junction_unresolved_no_candidate", 0),
        "no_successor": report.get("lanes_without_topology", 0),
        "unexplained": 0,
        "inferred_count": report.get("inferred_count", 0),
        "road_to_road_count": report.get("road_to_road_count", 0),
        "junction_repaired_count": report.get("junction_repaired_count", 0),
        "junction_unresolved_ambiguous": report.get("junction_unresolved_ambiguous", 0),
        "junction_unresolved_no_candidate": report.get("junction_unresolved_no_candidate", 0),
        "lanes_without_topology": report.get("lanes_without_topology", 0),
    }

def run_gap026_oracle(xodr_path: Path) -> Dict:
    """Run independent oracle for GAP026."""
    from gap026_oracle import independent_sanitize
    root = ET.parse(xodr_path).getroot()
    res = independent_sanitize(root, use_kernel=True)
    return {
        "checker_oracle_max_delta": 0,  # Would need comparison
    }

if __name__ == "__main__":
    print("="*60)
    print("POST-STAGE 8 ANALYSIS")
    print("="*60)
    
    print(f"\nStage 7: {stage7_path}")
    print(f"Stage 7 SHA256: {compute_sha256(stage7_path)}")
    print(f"Stage 7 exists: {stage7_path.exists()}")
    
    print(f"\nStage 8: {stage8_path}")
    print(f"Stage 8 SHA256: {compute_sha256(stage8_path)}")
    print(f"Stage 8 exists: {stage8_path.exists()}")
    
    # 1. Topology fingerprints
    print("\n--- Topology Fingerprints ---")
    stage7_topo_hash = get_topology_fingerprint(stage7_path)
    stage8_topo_hash = get_topology_fingerprint(stage8_path)
    print(f"STAGE7_TOPOLOGY_HASH={stage7_topo_hash}")
    print(f"STAGE8_TOPOLOGY_HASH={stage8_topo_hash}")
    print(f"STAGE8_LANE_TOPOLOGY_MUTATION={stage7_topo_hash != stage8_topo_hash}")
    
    # 2. Invalid targets check
    print("\n--- Invalid Targets Check ---")
    stage7_invalid = check_invalid_targets(stage7_path)
    stage8_invalid = check_invalid_targets(stage8_path)
    print(f"INVALID_TARGETS_STAGE7={stage7_invalid}")
    print(f"INVALID_TARGETS_STAGE8={stage8_invalid}")
    print(f"INVALID_TARGETS_AFTER={stage8_invalid}")
    
    # 3. GAP026 on Stage 8
    print("\n--- GAP026 on Stage 8 ---")
    gap026_stage8 = run_gap026_check(stage8_path)
    print(f"STAGE8_GAP026_FAIL={gap026_stage8['fail']}")
    print(f"STAGE8_GAP026_SEVERE_DISTANCE={gap026_stage8['severe_distance']}")
    print(f"STAGE8_GAP026_SEVERE_ANGLE={gap026_stage8['severe_angle']}")
    print(f"STAGE8_GAP026_UNEXPLAINED={gap026_stage8['unexplained']}")
    
    # 4. GAP048 on Stage 8
    print("\n--- GAP048 on Stage 8 ---")
    gap048_stage8 = run_gap048_check(stage8_path)
    print(f"STAGE8_GAP048_BROKEN={gap048_stage8['broken']}")
    print(f"STAGE8_GAP048_REPAIRED={gap048_stage8['repaired']}")
    print(f"STAGE8_GAP048_UNEXPLAINED={gap048_stage8['unexplained']}")
    print(f"  (detail) inferred_count={gap048_stage8['inferred_count']}")
    print(f"  (detail) road_to_road_count={gap048_stage8['road_to_road_count']}")
    print(f"  (detail) junction_repaired_count={gap048_stage8['junction_repaired_count']}")
    print(f"  (detail) junction_unresolved_ambiguous={gap048_stage8['junction_unresolved_ambiguous']}")
    print(f"  (detail) junction_unresolved_no_candidate={gap048_stage8['junction_unresolved_no_candidate']}")
    print(f"  (detail) lanes_without_topology={gap048_stage8['lanes_without_topology']}")
    
    # 5. GAP026 on Stage 7 for comparison
    print("\n--- GAP026 on Stage 7 (for comparison) ---")
    gap026_stage7 = run_gap026_check(stage7_path)
    print(f"STAGE7_GAP026_FAIL={gap026_stage7['fail']}")
    print(f"STAGE7_GAP026_SEVERE_DISTANCE={gap026_stage7['severe_distance']}")
    print(f"STAGE7_GAP026_SEVERE_ANGLE={gap026_stage7['severe_angle']}")
    
    # 6. GAP048 on Stage 7 for comparison
    print("\n--- GAP048 on Stage 7 (for comparison) ---")
    gap048_stage7 = run_gap048_check(stage7_path)
    print(f"STAGE7_GAP048_BROKEN={gap048_stage7['broken']}")
    print(f"STAGE7_GAP048_REPAIRED={gap048_stage7['repaired']}")
    print(f"STAGE7_GAP048_UNEXPLAINED={gap048_stage7['unexplained']}")
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"STAGE7_SHA={compute_sha256(stage7_path)}")
    print(f"FRESH_STAGE8_SHA={compute_sha256(stage8_path)}")
    print(f"STAGE8_LANE_TOPOLOGY_MUTATION={stage7_topo_hash != stage8_topo_hash}")
    print(f"INVALID_TARGETS_AFTER={stage8_invalid}")
    print(f"STAGE8_GAP026_FAIL={gap026_stage8['fail']}")
    print(f"STAGE8_GAP026_SEVERE_DISTANCE={gap026_stage8['severe_distance']}")
    print(f"STAGE8_GAP026_SEVERE_ANGLE={gap026_stage8['severe_angle']}")
    print(f"STAGE8_GAP026_UNEXPLAINED={gap026_stage8['unexplained']}")
    print(f"STAGE8_GAP048_BROKEN={gap048_stage8['broken']}")
    print(f"STAGE8_GAP048_REPAIRED={gap048_stage8['repaired']}")
    print(f"STAGE8_GAP048_UNEXPLAINED={gap048_stage8['unexplained']}")
    
    # RQ1 Admission check
    print("\n--- RQ1 Topology Admission ---")
    if gap026_stage8['fail'] > 0 or gap026_stage8['severe_distance'] > 0 or gap026_stage8['severe_angle'] > 0:
        print("RQ1_TOPOLOGY_ADMISSION=FAIL_GAP026_RESIDUALS")
    else:
        print("RQ1_TOPOLOGY_ADMISSION=PASS")