import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Tuple, Dict, List

# Production checker from lanelink_builder
from ultimate_pipeline.lanes.lanelink_builder import LaneLinkBuilder
from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint as kernel_endpoint, pose_at_s as kernel_pose_at_s
import opendrive_geometry.primitives as og_prim

def _safe_float(v, default=float('nan')):
    try: return float(v)
    except: return default

# Production checker thresholds
POSITION_TOLERANCE = 0.25
HEADING_TOLERANCE_RAD = math.radians(12.0)

def kernel_edge_pose(road: ET.Element, at_start: bool) -> Optional[Tuple[float,float,float]]:
    geoms = sorted(road.findall("./planView/geometry"), key=lambda g: _safe_float(g.get("s"), 0))
    if not geoms: return None
    try:
        if at_start: p = kernel_pose_at_s(geoms[0], 0.0)
        else: p = kernel_endpoint(geoms[-1])
        return float(p.x), float(p.y), float(p.heading)
    except: return None

def og_edge_pose(road: ET.Element, at_start: bool) -> Optional[Tuple[float,float,float]]:
    geoms = sorted(road.findall("./planView/geometry"), key=lambda g: _safe_float(g.get("s"), 0))
    if not geoms: return None
    geom = geoms[0] if at_start else geoms[-1]
    try:
        x0 = _safe_float(geom.get("x")); y0 = _safe_float(geom.get("y")); hdg0 = _safe_float(geom.get("hdg")); length = _safe_float(geom.get("length"))
        s_local = 0.0 if at_start else length
        prim = next(iter(geom), None)
        if prim is None: return None
        tag = prim.tag.rsplit("}",1)[-1]
        if tag == "line": pose = og_prim.evaluate_line(x0, y0, hdg0, length, s_local)
        elif tag == "arc": curvature = _safe_float(prim.get("curvature")); pose = og_prim.evaluate_arc(x0, y0, hdg0, length, curvature, s_local)
        elif tag == "paramPoly3":
            aU = _safe_float(prim.get("aU")); bU = _safe_float(prim.get("bU")); cU = _safe_float(prim.get("cU")); dU = _safe_float(prim.get("dU"))
            aV = _safe_float(prim.get("aV")); bV = _safe_float(prim.get("bV")); cV = _safe_float(prim.get("cV")); dV = _safe_float(prim.get("dV"))
            pRange = prim.get("pRange", "arcLength")
            pose = og_prim.evaluate_param_poly3(x0, y0, hdg0, length, aU,bU,cU,dU, aV,bV,cV,dV, pRange, s_local)
        elif tag == "poly3":
            a = _safe_float(prim.get("a")); b = _safe_float(prim.get("b")); c = _safe_float(prim.get("c")); d = _safe_float(prim.get("d"))
            pose = og_prim.evaluate_poly3(x0, y0, hdg0, length, a,b,c,d, s_local)
        elif tag == "spiral":
            curvStart = _safe_float(prim.get("curvStart")); curvEnd = _safe_float(prim.get("curvEnd"))
            pose = og_prim.evaluate_spiral(x0, y0, hdg0, length, curvStart, curvEnd, s_local)
        else: return None
        return float(pose.x), float(pose.y), float(pose.hdg)
    except: return None

def road_length(road: ET.Element) -> float:
    try: return _safe_float(road.get("length"), 0.0)
    except:
        geoms = road.findall("./planView/geometry")
        return sum(_safe_float(g.get("length"),0) for g in geoms)

def eval_lane_offset(road: ET.Element, s: float) -> float:
    offsets = sorted(road.findall("./lanes/laneOffset"), key=lambda o: _safe_float(o.get("s"),0))
    if not offsets: return 0.0
    chosen = None
    for off in offsets:
        if _safe_float(off.get("s"),0) <= s: chosen = off
        else: break
    if chosen is None: chosen = offsets[0]
    ds = s - _safe_float(chosen.get("s"),0)
    a = _safe_float(chosen.get("a"),0); b=_safe_float(chosen.get("b"),0); c=_safe_float(chosen.get("c"),0); d=_safe_float(chosen.get("d"),0)
    return a + b*ds + c*ds*ds + d*ds*ds*ds

def eval_lane_width(width_elem: ET.Element, lane_section_s: float, target_s: float) -> float:
    sOffset = _safe_float(width_elem.get("sOffset"),0)
    a = _safe_float(width_elem.get("a")); b=_safe_float(width_elem.get("b"),0); c=_safe_float(width_elem.get("c"),0); d=_safe_float(width_elem.get("d"),0)
    ds = target_s - lane_section_s - sOffset
    return a + b*ds + c*ds*ds + d*ds*ds*ds

def lane_center_oracle(road: ET.Element, lane_id: int, at_start: bool, use_kernel: bool = True, include_lane_offset: bool = True, include_all_lanes: bool = False) -> Optional[Tuple[float,float,float,float]]:
    if use_kernel: base = kernel_edge_pose(road, at_start)
    else: base = og_edge_pose(road, at_start)
    if base is None: return None
    x0,y0,hdg0 = base
    sections = sorted(road.findall("./lanes/laneSection"), key=lambda s: _safe_float(s.get("s"),0))
    if not sections: return None
    section = sections[0] if at_start else sections[-1]
    section_s = _safe_float(section.get("s"),0)
    rlen = road_length(road)
    target_s = 0.0 if at_start else rlen
    side_name = "left" if lane_id > 0 else "right"
    side_elem = section.find(side_name)
    if side_elem is None: return None
    if include_all_lanes:
        lanes_for_offset = sorted(side_elem.findall("lane"), key=lambda l: abs(int(l.get("id",0))))
    else:
        lanes_for_offset = sorted((lane for lane in side_elem.findall("lane") if lane.get("type","driving")=="driving"), key=lambda l: abs(int(l.get("id",0))))
    selected = None
    for lane in lanes_for_offset:
        try:
            if int(lane.get("id",0)) == lane_id: selected = lane; break
        except: continue
    if selected is None:
        for lane in side_elem.findall("lane"):
            try:
                if int(lane.get("id",0)) == lane_id: selected = lane; break
            except: continue
    if selected is None: return None
    width_elem = selected.find("./width")
    if width_elem is None: return None
    lane_width = eval_lane_width(width_elem, section_s, target_s)
    if not math.isfinite(lane_width) or lane_width <= 0: return None
    preceding = 0.0
    for lane in lanes_for_offset:
        try: lid = int(lane.get("id",0))
        except: continue
        if abs(lid) >= abs(lane_id): continue
        w_elem = lane.find("./width")
        if w_elem is not None:
            w = eval_lane_width(w_elem, section_s, target_s)
            if math.isfinite(w) and w>0: preceding += w
    sign = 1 if lane_id > 0 else -1
    lane_center_offset = (preceding + lane_width/2.0) * sign
    lane_offset = eval_lane_offset(road, target_s) if include_lane_offset else 0.0
    lateral = lane_center_offset + lane_offset
    x = x0 - math.sin(hdg0) * lateral
    y = y0 + math.cos(hdg0) * lateral
    return x, y, hdg0, lateral

def production_checker_detail(root: ET.Element) -> Dict:
    """Run production checker with per-failure detail."""
    roads = {str(r.get("id")): r for r in root.findall("road") if r.get("id")}
    checked = passed = failed = 0
    failures = []
    
    def edge_pose(road: ET.Element, at_start: bool) -> Optional[tuple[float, float, float]]:
        geoms = sorted(road.findall("./planView/geometry"), key=lambda g: float(g.get("s", 0)))
        if not geoms: return None
        try:
            p = kernel_pose_at_s(geoms[0], 0.0) if at_start else kernel_endpoint(geoms[-1])
            heading = p.heading if at_start else p.heading
            return float(p.x), float(p.y), float(heading)
        except: return None

    def lane_pose(road: ET.Element, lane_id: int, at_start: bool) -> Optional[tuple[float, float, float]]:
        base = edge_pose(road, at_start)
        if base is None: return None
        sections = sorted(road.findall("./lanes/laneSection"), key=lambda s: float(s.get("s", 0)))
        if not sections: return None
        section = sections[0] if at_start else sections[-1]
        side = section.find("./left" if lane_id > 0 else "./right")
        if side is None: return None
        lanes = sorted((lane for lane in side.findall("lane") if lane.get("type", "driving") == "driving"), key=lambda l: abs(int(l.get("id", 0))))
        selected = next((lane for lane in lanes if int(lane.get("id", 0)) == lane_id), None)
        if selected is None: return None
        width = selected.find("./width")
        if width is None: return None
        lane_width = float(width.get("a", "nan"))
        if not math.isfinite(lane_width) or lane_width <= 0: return None
        preceding_width = 0.0
        for lane in lanes:
            if abs(int(lane.get("id", 0))) >= abs(lane_id): continue
            preceding = lane.find("./width")
            if preceding is not None:
                preceding_width += float(preceding.get("a", "0"))
        lateral = (preceding_width + lane_width / 2.0) * (1 if lane_id > 0 else -1)
        x, y, heading = base
        return x - math.sin(heading) * lateral, y + math.cos(heading) * lateral, heading

    for junction in root.findall("junction"):
        for connection in junction.findall("connection"):
            incoming = roads.get(str(connection.get("incomingRoad")))
            connecting = roads.get(str(connection.get("connectingRoad")))
            at_start = connection.get("contactPoint", "start") != "end"
            if incoming is None or connecting is None: continue
            for lane_link in connection.findall("laneLink"):
                checked += 1
                try:
                    source = lane_pose(incoming, int(lane_link.get("from")), False)
                    target = lane_pose(connecting, int(lane_link.get("to")), at_start)
                except (TypeError, ValueError):
                    source = target = None
                heading_target = None if target is None else target[2] + (0 if at_start else math.pi)
                
                if source is not None and target is not None:
                    dist = math.hypot(source[0] - target[0], source[1] - target[1])
                    ang_rad = abs((source[2] - heading_target + math.pi) % (2 * math.pi) - math.pi)
                    ang_deg = math.degrees(ang_rad)
                    dist_fail = dist > POSITION_TOLERANCE
                    ang_fail = ang_rad > HEADING_TOLERANCE_RAD
                    valid = not dist_fail and not ang_fail
                else:
                    dist = float('nan')
                    ang_deg = float('nan')
                    dist_fail = True
                    ang_fail = True
                    valid = False
                
                if valid:
                    passed += 1
                else:
                    failed += 1
                    failures.append({
                        "junction_id": junction.get("id"),
                        "connection_id": connection.get("id"),
                        "incomingRoad": connection.get("incomingRoad"),
                        "connectingRoad": connection.get("connectingRoad"),
                        "contactPoint": connection.get("contactPoint", "start"),
                        "from_lane": lane_link.get("from"),
                        "to_lane": lane_link.get("to"),
                        "distance_m": dist,
                        "angle_deg": ang_deg,
                        "distance_fail": dist_fail,
                        "angle_fail": ang_fail,
                        "severe_distance": dist > 10.0 if math.isfinite(dist) else False,
                        "severe_angle": ang_deg > 10.0 if math.isfinite(ang_deg) else False,
                    })
    return {"checked": checked, "passed": passed, "failed": failed, "failures": failures}

if __name__ == "__main__":
    stage7 = Path("regen_20261014T000000Z/pipeline_out/07_lanes_20261014_155337_691757.xodr")
    if not stage7.exists():
        print("Stage7 artifact not found at expected path")
        # Try to find it
        import glob
        matches = list(Path(".").rglob("07_lanes_*.xodr"))
        if matches:
            print(f"Found: {matches}")
            stage7 = matches[0]
        else:
            exit(1)
    
    root = ET.parse(str(stage7)).getroot()
    
    # Run production checker with detail
    result = production_checker_detail(root)
    
    print(f"PRODUCTION_DISTANCE_THRESHOLD=0.25")
    print(f"PRODUCTION_ANGLE_THRESHOLD=12.0")
    print(f"GAP026_FAIL={result['failed']}")
    
    max_dist = 0
    max_angle = 0
    angle_gt_12 = 0
    angle_gt_10 = 0
    dist_gt_025 = 0
    dist_gt_10 = 0
    
    for f in result['failures']:
        d = f['distance_m']
        a = f['angle_deg']
        if math.isfinite(d):
            if d > max_dist: max_dist = d
            if d > 0.25: dist_gt_025 += 1
            if d > 10.0: dist_gt_10 += 1
        if math.isfinite(a):
            if a > max_angle: max_angle = a
            if a > 12.0: angle_gt_12 += 1
            if a > 10.0: angle_gt_10 += 1
    
    print(f"TRUE_MAX_DISTANCE={max_dist:.2f}")
    print(f"TRUE_MAX_ANGLE={max_angle:.2f}")
    print(f"ANGLE_GT_12_COUNT={angle_gt_12}")
    print(f"ANGLE_GT_10_COUNT={angle_gt_10}")
    print(f"DIST_GT_025_COUNT={dist_gt_025}")
    print(f"DIST_GT_10_COUNT={dist_gt_10}")
    
    # Print all failures
    for i, f in enumerate(result['failures']):
        print(f"\nFailure {i+1}:")
        print(f"  junction={f['junction_id']} connection={f['connection_id']}")
        print(f"  incoming={f['incomingRoad']} connecting={f['connectingRoad']} cp={f['contactPoint']}")
        print(f"  from={f['from_lane']} to={f['to_lane']}")
        print(f"  distance={f['distance_m']:.3f}m angle={f['angle_deg']:.2f}deg")
        print(f"  dist_fail={f['distance_fail']} ang_fail={f['angle_fail']}")
        print(f"  severe_dist={f['severe_distance']} severe_ang={f['severe_angle']}")
    
    # Save to JSON
    import json
    with open("CLOSURE19_GAP026_18_RESIDUALS.json", "w") as out:
        json.dump(result, out, indent=2, default=str)
    print("\nSaved CLOSURE19_GAP026_18_RESIDUALS.json")