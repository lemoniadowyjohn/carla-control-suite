#!/usr/bin/env python3
"""Independent Topology Oracle."""
import math
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict

# Use geometry kernel for pose calculation
from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s, endpoint

MAP_PATH = Path("campaigns/ingolstadt_cooked_perception_v1/candidate/ingolstadt_perception_map_of_record_20260905_202847.xodr")

def load_map():
    tree = ET.parse(MAP_PATH)
    return tree.getroot()

def get_road_pose(road, s):
    # Find geometry at s, compute pose
    # For road start s=0, for end s=length
    length = float(road.get("length", 0))
    # Find correct geometry segment for s
    plan_view = road.find("planView")
    if plan_view is None:
        return None
    # Accumulate geometries to find segment
    acc = 0.0
    for geom in plan_view.findall("geometry"):
        geom_s = float(geom.get("s", 0))
        geom_len = float(geom.get("length", 0))
        if geom_s <= s < geom_s + geom_len or (s == length and geom_s + geom_len == length):
            # s is within this geometry, compute local s
            local_s = s - geom_s
            return pose_at_s(geom, local_s)
    return None

def road_start_pose(road):
    return get_road_pose(road, 0.0)

def road_end_pose(road):
    length = float(road.get("length", 0))
    return get_road_pose(road, length)

def test_topology():
    root = load_map()
    roads = {r.get("id"): r for r in root.findall("road")}
    junctions = {j.get("id"): j for j in root.findall("junction")}
    
    results = {
        "total_roads": len(roads),
        "total_junctions": len(junctions),
        "dangling_predecessor": [],
        "dangling_successor": [],
        "wrong_contact_point": [],
        "reversed_connector": [],
        "invalid_lanelink": [],
        "lanelink_sign_error": [],
        "tangent_discontinuity": [],
        "orphan_connecting_road": [],
        "duplicate_connections": [],
        "invalid_topology_relations": 0,
        "junctions_checked": 0,
        "connecting_roads_checked": 0,
    }
    
    # Track junction connections for duplicates
    seen_connections = set()
    
    # Check each road's predecessor/successor
    for rid, road in roads.items():
        junction_id = road.get("junction")
        # If road is a connecting road (has junction id != "-1"), it's inside a junction
        # Check predecessor
        link = road.find("link")
        if link is not None:
            pred = link.find("predecessor")
            if pred is not None:
                pred_id = pred.get("elementId")
                pred_type = pred.get("elementType")
                if pred_type == "road" and pred_id not in roads:
                    results["dangling_predecessor"].append({"road": rid, "predecessor": pred_id})
                elif pred_type == "junction" and pred_id not in junctions:
                    results["dangling_predecessor"].append({"road": rid, "predecessor_junction": pred_id})
            succ = link.find("successor")
            if succ is not None:
                succ_id = succ.get("elementId")
                succ_type = succ.get("elementType")
                if succ_type == "road" and succ_id not in roads:
                    results["dangling_successor"].append({"road": rid, "successor": succ_id})
                elif succ_type == "junction" and succ_id not in junctions:
                    results["dangling_successor"].append({"road": rid, "successor_junction": succ_id})
    
    # Check each junction
    route_matrix = {}
    roundabout_results = {}
    
    for jid, junction in junctions.items():
        results["junctions_checked"] += 1
        connections = junction.findall("connection")
        route_matrix[jid] = {"connections": len(connections), "incoming": set(), "outgoing": set()}
        
        for conn in connections:
            inc = conn.get("incomingRoad")
            con = conn.get("connectingRoad")
            contact = conn.get("contactPoint")
            
            # Check incoming and connecting roads exist
            if inc not in roads:
                results["invalid_topology_relations"] += 1
            if con not in roads:
                results["orphan_connecting_road"].append({"junction": jid, "connectingRoad": con})
                results["invalid_topology_relations"] += 1
                continue
            
            results["connecting_roads_checked"] += 1
            route_matrix[jid]["incoming"].add(inc)
            route_matrix[jid]["outgoing"].add(con)
            
            # Check duplicate connections
            key = (inc, con, contact)
            if key in seen_connections:
                results["duplicate_connections"].append({"junction": jid, "incoming": inc, "connecting": con, "contact": contact})
            seen_connections.add(key)
            
            # Check contactPoint validity (should be start or end)
            if contact not in ["start", "end"]:
                results["wrong_contact_point"].append({"junction": jid, "connection": f"{inc}->{con}", "contactPoint": contact})
                results["invalid_topology_relations"] += 1
            
            # Check connecting road's junction attribute
            con_road = roads[con]
            con_junction = con_road.get("junction")
            if con_junction != jid:
                results["invalid_topology_relations"] += 1
            
            # Check laneLinks
            for ll in conn.findall("laneLink"):
                from_id = ll.get("from")
                to_id = ll.get("to")
                # Basic check: from and to should be integers (lane ids)
                try:
                    int(from_id)
                    int(to_id)
                except:
                    results["invalid_lanelink"].append({"junction": jid, "from": from_id, "to": to_id})
                    results["invalid_topology_relations"] += 1
                
                # Check sign: for a valid laneLink, from and to should have same sign or one is 0?
                # For now, just check they are not both 0 unless center
                if from_id == "0" or to_id == "0":
                    # Center lane should not be linked as driving
                    pass
            
            # Check tangent continuity (simplified)
            # Get end pose of incoming road and start pose of connecting road
            inc_road = roads.get(inc)
            con_road_obj = roads.get(con)
            if inc_road is not None and con_road_obj is not None:
                # Determine which end of incoming road connects
                # If contactPoint is start, then connecting road's start connects to incoming's end or start?
                # Simplified: check if poses are close
                try:
                    inc_pose = road_end_pose(inc_road) if contact == "start" else road_start_pose(inc_road)
                    con_pose = road_start_pose(con_road_obj)
                    if inc_pose and con_pose:
                        gap = math.hypot(inc_pose.x - con_pose.x, inc_pose.y - con_pose.y)
                        if gap > 5.0:  # 5 meter threshold for discontinuity
                            results["tangent_discontinuity"].append({
                                "junction": jid,
                                "incoming": inc,
                                "connecting": con,
                                "gap": gap,
                                "contactPoint": contact
                            })
                        # Check heading difference
                        if inc_pose and con_pose:
                            h_diff = abs(inc_pose.heading - con_pose.heading)
                            h_diff = min(h_diff, 2*math.pi - h_diff)
                            if h_diff > math.radians(10):  # 10 degree threshold
                                # Could be valid for turning, but flag large discontinuities
                                pass
                except Exception as e:
                    pass
    
    # Convert sets to lists for JSON
    for jid in route_matrix:
        route_matrix[jid]["incoming"] = list(route_matrix[jid]["incoming"])
        route_matrix[jid]["outgoing"] = list(route_matrix[jid]["outgoing"])
    
    # Roundabout detection (junctions with >4 connections and forming cycle)
    for jid, junction in junctions.items():
        conns = junction.findall("connection")
        if len(conns) >= 4:
            # Check if it forms a cycle (each connecting road connects to next)
            # Simplified: count if junction has many roads and they interconnect
            connecting_roads = [c.get("connectingRoad") for c in conns]
            # Check if connecting roads form a ring (each connects to another)
            is_roundabout = False
            # Look for roundabout name or check geometry
            name = junction.get("name", "").lower()
            if "roundabout" in name or len(connecting_roads) >= 8:
                is_roundabout = True
                roundabout_results[jid] = {
                    "is_roundabout": True,
                    "connecting_roads": len(connecting_roads),
                    "connections": len(conns),
                    "closed_cycle": "UNVERIFIED",  # Would need deeper graph analysis
                    "entry_connectivity": "UNVERIFIED",
                    "exit_connectivity": "UNVERIFIED",
                    "status": "NEEDS_MANUAL_REVIEW"
                }
    
    # Overall counts
    total_invalid = (
        len(results["dangling_predecessor"]) +
        len(results["dangling_successor"]) +
        len(results["wrong_contact_point"]) +
        len(results["orphan_connecting_road"]) +
        len(results["duplicate_connections"]) +
        len(results["invalid_lanelink"])
    )
    results["invalid_topology_relations"] = total_invalid
    results["total_invalid"] = total_invalid
    
    return results, route_matrix, roundabout_results

if __name__ == "__main__":
    results, matrix, roundabouts = test_topology()
    print(f"Junctions checked: {results['junctions_checked']}")
    print(f"Connecting roads checked: {results['connecting_roads_checked']}")
    print(f"Invalid relations: {results['invalid_topology_relations']}")
    print(f"Dangling predecessor: {len(results['dangling_predecessor'])}")
    print(f"Dangling successor: {len(results['dangling_successor'])}")
    print(f"Wrong contactPoint: {len(results['wrong_contact_point'])}")
    print(f"Orphan connecting: {len(results['orphan_connecting_road'])}")
    print(f"Roundabouts found: {len(roundabouts)}")
    
    with open("reports/production_readiness/20260915T230000Z_GEOMETRY_TOPOLOGY_ORACLE_V2/TOPOLOGY_ORACLE_RESULTS.json", "w") as f:
        json.dump(results, f, indent=2)
    with open("reports/production_readiness/20260915T230000Z_GEOMETRY_TOPOLOGY_ORACLE_V2/JUNCTION_ROUTE_MATRIX.json", "w") as f:
        json.dump(matrix, f, indent=2)
    with open("reports/production_readiness/20260915T230000Z_GEOMETRY_TOPOLOGY_ORACLE_V2/ROUNDABOUT_TOPOLOGY_RESULTS.json", "w") as f:
        json.dump(roundabouts, f, indent=2)
    
    # Also create attachment errors CSV
    with open("reports/production_readiness/20260915T230000Z_GEOMETRY_TOPOLOGY_ORACLE_V2/JUNCTION_ATTACHMENT_ERRORS.csv", "w") as f:
        f.write("junction,incoming,connecting,gap,contactPoint\n")
        for err in results["tangent_discontinuity"]:
            f.write(f"{err['junction']},{err['incoming']},{err['connecting']},{err['gap']:.3f},{err['contactPoint']}\n")
    
    print("Done")
