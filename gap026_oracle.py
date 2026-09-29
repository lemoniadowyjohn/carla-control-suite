#!/usr/bin/env python3
"""
GAP-026 Independent Oracle for sanitize_junction_lane_links

Does NOT import LaneLinkBuilder.sanitize_junction_lane_links for oracle logic.
Re-implements all semantics independently and cross-validates with both geometry authorities:
 - ultimate_pipeline/geometry/opendrive_geometry_kernel.py
 - opendrive_geometry/ (primitives + evaluator)

Semantics audited per task B:
 - road planView endpoint
 - heading/tangent
 - contactPoint semantics
 - laneSection s
 - laneOffset
 - lane width polynomial at endpoint
 - left/right sign convention
 - lane center offset
 - connection orientation
 - laneLink from/to mapping
"""

import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Tuple, Dict, List

# Geometry Authority 1: kernel
from ultimate_pipeline.geometry.opendrive_geometry_kernel import endpoint as kernel_endpoint, pose_at_s as kernel_pose_at_s, Pose as KernelPose
# Geometry Authority 2: opendrive_geometry model
import opendrive_geometry.primitives as og_prim
from opendrive_geometry.model import Pose2D, GeometrySegment
from ultimate_pipeline.carla_tools.map_registry import verify_pinned_map

def _safe_float(v, default=float('nan')):
    try:
        return float(v)
    except:
        return default

# ---------- Geometry Authority 1 wrapper ----------
def kernel_edge_pose(road: ET.Element, at_start: bool) -> Optional[Tuple[float,float,float]]:
    geoms = sorted(road.findall("./planView/geometry"), key=lambda g: _safe_float(g.get("s"), 0))
    if not geoms:
        return None
    try:
        if at_start:
            p = kernel_pose_at_s(geoms[0], 0.0)
        else:
            p = kernel_endpoint(geoms[-1])
        return float(p.x), float(p.y), float(p.heading)
    except Exception:
        return None

# ---------- Geometry Authority 2 wrapper ----------
def og_edge_pose(road: ET.Element, at_start: bool) -> Optional[Tuple[float,float,float]]:
    geoms = sorted(road.findall("./planView/geometry"), key=lambda g: _safe_float(g.get("s"), 0))
    if not geoms:
        return None
    geom = geoms[0] if at_start else geoms[-1]
    try:
        x0 = _safe_float(geom.get("x"))
        y0 = _safe_float(geom.get("y"))
        hdg0 = _safe_float(geom.get("hdg"))
        length = _safe_float(geom.get("length"))
        s_local = 0.0 if at_start else length
        # Determine primitive
        prim = next(iter(geom), None)
        if prim is None:
            return None
        tag = prim.tag.rsplit("}",1)[-1]
        if tag == "line":
            pose = og_prim.evaluate_line(x0, y0, hdg0, length, s_local)
        elif tag == "arc":
            curvature = _safe_float(prim.get("curvature"))
            pose = og_prim.evaluate_arc(x0, y0, hdg0, length, curvature, s_local)
        elif tag == "paramPoly3":
            # use evaluator
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
        else:
            return None
        return float(pose.x), float(pose.y), float(pose.hdg)
    except Exception as e:
        # Fallback to kernel for debugging
        return None

def road_length(road: ET.Element) -> float:
    # Use road attribute or sum of geometry lengths
    try:
        return _safe_float(road.get("length"), 0.0)
    except:
        geoms = road.findall("./planView/geometry")
        return sum(_safe_float(g.get("length"),0) for g in geoms)

def eval_lane_offset(road: ET.Element, s: float) -> float:
    """
    Evaluate laneOffset polynomial at s along road.
    laneOffset is defined under lanes/laneOffset with s attribute.
    Polynomial: offset = a + b*ds + c*ds^2 + d*ds^3 where ds = s - s0
    """
    offsets = sorted(road.findall("./lanes/laneOffset"), key=lambda o: _safe_float(o.get("s"),0))
    if not offsets:
        return 0.0
    chosen = None
    for off in offsets:
        if _safe_float(off.get("s"),0) <= s:
            chosen = off
        else:
            break
    if chosen is None:
        chosen = offsets[0]
    ds = s - _safe_float(chosen.get("s"),0)
    a = _safe_float(chosen.get("a"),0); b=_safe_float(chosen.get("b"),0); c=_safe_float(chosen.get("c"),0); d=_safe_float(chosen.get("d"),0)
    return a + b*ds + c*ds*ds + d*ds*ds*ds

def eval_lane_width(width_elem: ET.Element, lane_section_s: float, target_s: float) -> float:
    """
    Evaluate width polynomial at target_s.
    width element has sOffset relative to laneSection s, and a,b,c,d.
    ds = target_s - laneSection_s - sOffset
    width = a + b*ds + c*ds^2 + d*ds^3
    For this map, b=c=d=0 and sOffset=0, so width = a.
    """
    sOffset = _safe_float(width_elem.get("sOffset"),0)
    a = _safe_float(width_elem.get("a")); b=_safe_float(width_elem.get("b"),0); c=_safe_float(width_elem.get("c"),0); d=_safe_float(width_elem.get("d"),0)
    # Determine ds: target_s is absolute s along road (distance from road start)
    # laneSection s is absolute s where section starts
    # But checker currently just uses a, ignoring ds. Oracle evaluates correctly.
    ds = target_s - lane_section_s - sOffset
    # Clamp ds >=0? If width sOffset defines segment, ds should be within segment length, but we just evaluate polynomial.
    return a + b*ds + c*ds*ds + d*ds*ds*ds

def lane_center_oracle(road: ET.Element, lane_id: int, at_start: bool, use_kernel: bool = True, include_lane_offset: bool = True, include_all_lanes: bool = False) -> Optional[Tuple[float,float,float,float]]:
    """
    Independent oracle for lane center pose.
    Returns (x,y,heading,lateral) or None.
    Implements all semantics:
      - road planView endpoint via chosen geometry authority
      - laneSection s selection (first/last)
      - laneOffset evaluation
      - lane width polynomial at endpoint
      - left/right sign convention
      - lane center offset (sum of preceding widths + half own)
      - connection orientation handled outside (heading flip)
    """
    # 1. road planView endpoint / heading
    if use_kernel:
        base = kernel_edge_pose(road, at_start)
    else:
        base = og_edge_pose(road, at_start)
    if base is None:
        return None
    x0,y0,hdg0 = base

    # 2. laneSection s & selection
    sections = sorted(road.findall("./lanes/laneSection"), key=lambda s: _safe_float(s.get("s"),0))
    if not sections:
        return None
    section = sections[0] if at_start else sections[-1]
    section_s = _safe_float(section.get("s"),0)

    # Determine road s at endpoint
    rlen = road_length(road)
    target_s = 0.0 if at_start else rlen

    # 3. side selection by lane_id sign
    side_name = "left" if lane_id > 0 else "right"
    # OpenDRIVE: lane ids negative for right, positive for left, 0 = center
    # Sign convention: lateral positive to left (CCW from heading)
    side_elem = section.find(side_name)
    if side_elem is None:
        return None

    # 4. lane width polynomial & lane selection
    # Determine lane list for preceding width calculation
    if include_all_lanes:
        lanes_all = sorted(side_elem.findall("lane"), key=lambda l: abs(int(l.get("id",0))))
        lanes_for_offset = lanes_all
    else:
        lanes_for_offset = sorted((lane for lane in side_elem.findall("lane") if lane.get("type","driving")=="driving"), key=lambda l: abs(int(l.get("id",0))))

    selected = None
    for lane in lanes_for_offset:
        try:
            if int(lane.get("id",0)) == lane_id:
                selected = lane
                break
        except:
            continue
    # If not found in driving-only list but lane exists as non-driving, try all
    if selected is None:
        for lane in side_elem.findall("lane"):
            try:
                if int(lane.get("id",0)) == lane_id:
                    selected = lane
                    break
            except:
                continue
    if selected is None:
        return None

    width_elem = selected.find("./width")
    if width_elem is None:
        return None
    # Evaluate width polynomial at target_s
    lane_width = eval_lane_width(width_elem, section_s, target_s)
    if not math.isfinite(lane_width) or lane_width <= 0:
        return None

    # 5. preceding width: sum of widths of lanes with |id| < |lane_id| on same side
    preceding = 0.0
    for lane in lanes_for_offset:
        try:
            lid = int(lane.get("id",0))
        except:
            continue
        if abs(lid) >= abs(lane_id):
            continue
        w_elem = lane.find("./width")
        if w_elem is not None:
            # Evaluate width at same target_s for preceding lanes
            # Need their section_s: they are in same section, so same section_s
            w = eval_lane_width(w_elem, section_s, target_s)
            if math.isfinite(w) and w>0:
                preceding += w

    # 6. lane center offset
    # Lateral offset from reference line to lane center:
    #   lateral = (preceding + lane_width/2) * sign + laneOffset
    # sign = +1 for left (positive id), -1 for right (negative id)
    sign = 1 if lane_id > 0 else -1
    lane_center_offset = (preceding + lane_width/2.0) * sign

    # 7. laneOffset contribution
    lane_offset = eval_lane_offset(road, target_s) if include_lane_offset else 0.0
    lateral = lane_center_offset + lane_offset
    # Note: laneOffset is defined as lateral shift of reference line? Spec says laneOffset shifts reference line.
    # Adding it as above is correct for lane center world pose.

    # 8. world pose
    x = x0 - math.sin(hdg0) * lateral
    y = y0 + math.cos(hdg0) * lateral
    return x, y, hdg0, lateral

def independent_sanitize(root: ET.Element, use_kernel=True) -> Dict:
    roads = {str(r.get("id")): r for r in root.findall("road") if r.get("id")}
    checked=passed=failed=0
    failures=[]
    details=[]
    for j in root.findall("junction"):
        for conn in j.findall("connection"):
            incoming = roads.get(str(conn.get("incomingRoad")))
            connecting = roads.get(str(conn.get("connectingRoad")))
            at_start = conn.get("contactPoint","start") != "end"
            if incoming is None or connecting is None:
                continue
            for ll in conn.findall("laneLink"):
                checked+=1
                try:
                    from_id=int(ll.get("from")); to_id=int(ll.get("to"))
                except:
                    failed+=1
                    failures.append({"junction_id":j.get("id"),"connection_id":conn.get("id"),"from":ll.get("from"),"to":ll.get("to"),"reason":"invalid_id"})
                    continue
                src = lane_center_oracle(incoming, from_id, False, use_kernel=use_kernel, include_lane_offset=True, include_all_lanes=False)
                tgt = lane_center_oracle(connecting, to_id, at_start, use_kernel=use_kernel, include_lane_offset=True, include_all_lanes=False)
                if src is None or tgt is None:
                    failed+=1
                    failures.append({"junction_id":j.get("id"),"connection_id":conn.get("id"),"from":ll.get("from"),"to":ll.get("to"),"reason":"missing_lane"})
                    details.append((float('nan'), float('nan'), j.get("id"), conn.get("id"), ll.get("from"), ll.get("to")))
                    continue
                # connection orientation: flip heading if contactPoint==end
                heading_target = tgt[2] + (0 if at_start else math.pi)
                dist = math.hypot(src[0]-tgt[0], src[1]-tgt[1])
                ang = abs((src[2] - heading_target + math.pi) % (2*math.pi) - math.pi)
                valid = dist <= 0.25 and ang <= math.radians(12)
                if valid:
                    passed+=1
                else:
                    failed+=1
                    failures.append({"junction_id":j.get("id"),"connection_id":conn.get("id"),"from":ll.get("from"),"to":ll.get("to"),"dist":dist,"ang_deg":math.degrees(ang)})
                details.append((dist, ang, j.get("id"), conn.get("id"), ll.get("from"), ll.get("to")))
    return {"checked":checked,"passed":passed,"failed":failed,"failures":failures,"details":details}

if __name__ == "__main__":
    pinned = verify_pinned_map("auto_map_of_record")
    print(f"Verified pin: {pinned['path']} sha256={pinned['sha256']} bytes={pinned['bytes']}")
    root = ET.parse(pinned["resolved_path"]).getroot()
    # Run both oracles
    res_kernel = independent_sanitize(root, use_kernel=True)
    res_og = independent_sanitize(root, use_kernel=False)
    print(f"Kernel oracle: checked={res_kernel['checked']} passed={res_kernel['passed']} failed={res_kernel['failed']}")
    print(f"OG oracle: checked={res_og['checked']} passed={res_og['passed']} failed={res_og['failed']}")
    # Compare kernel vs OG distances
    max_delta=0
    for (d1,_,_,_,_,_), (d2,_,_,_,_,_) in zip(res_kernel["details"], res_og["details"]):
        if math.isfinite(d1) and math.isfinite(d2):
            max_delta = max(max_delta, abs(d1-d2))
    print(f"max delta between authorities: {max_delta:.9f} m")
    # Compare oracle vs production checker
    from ultimate_pipeline.lanes.lanelink_builder import LaneLinkBuilder
    import xml.etree.ElementTree as ET
    root2 = ET.parse(pinned["resolved_path"]).getroot()
    prod = LaneLinkBuilder.sanitize_junction_lane_links(root2, label="prod")
    print(f"Production checker: checked={prod['summary_metrics']['checked']} failed={prod['summary_metrics']['failed']}")
    # Compare failure sets
    # Check if counts match
    print(f"Oracle kernel vs prod delta failed: {res_kernel['failed'] - prod['summary_metrics']['failed']}")
    # Find mismatches
    prod_set = set((f["junction_id"], f["connection_id"], f["from"], f["to"]) for f in prod["failures"])
    oracle_set = set((f["junction_id"], f["connection_id"], f["from"], f["to"]) for f in res_kernel["failures"])
    print(f"Intersection {len(prod_set & oracle_set)} prod only {len(prod_set - oracle_set)} oracle only {len(oracle_set - prod_set)}")
