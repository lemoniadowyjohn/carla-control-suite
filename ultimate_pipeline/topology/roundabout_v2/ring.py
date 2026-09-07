from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .core import Anchor, Sample
from .elevation import hermite_coefficients
from .lane_links import LaneLink, map_lanes

@dataclass(frozen=True)
class RingSegmentSpec:
    road_id: str
    start: Anchor
    end: Anchor
    length: float
    heading_delta: float
    lane_ids: tuple[int, ...]

def _angle_delta(a: float, b: float) -> float:
    return (b - a + math.pi) % (2 * math.pi) - math.pi

def order_anchors(anchors: list[Anchor], center_x: float, center_y: float) -> list[Anchor]:
    if len(anchors) < 3: raise ValueError("a segmented ring requires at least three anchors")
    return sorted(anchors, key=lambda a: (math.atan2(a.y-center_y, a.x-center_x), a.anchor_id))

def build_segment_specs(anchors: list[Anchor], center_x: float, center_y: float, first_id: int) -> list[RingSegmentSpec]:
    ordered=order_anchors(anchors,center_x,center_y); specs=[]
    for i,start in enumerate(ordered):
        end=ordered[(i+1)%len(ordered)]
        length=math.hypot(end.x-start.x,end.y-start.y)
        if not math.isfinite(length) or length <= 0: raise ValueError("ring anchors are coincident")
        if not start.lane_ids or not end.lane_ids: raise ValueError("ring anchor has no driving lanes")
        if len(start.lane_ids) != len(end.lane_ids): raise ValueError("lane-count transition requires explicit mapping")
        specs.append(RingSegmentSpec(str(first_id+i),start,end,length,_angle_delta(start.heading,end.heading),tuple(start.lane_ids)))
    return specs

def _hermite_xy(spec: RingSegmentSpec, t: float) -> tuple[float, float]:
    """Evaluate a cubic Hermite path in global coordinates."""
    t = min(1.0, max(0.0, float(t)))
    chord = spec.length
    p0 = (spec.start.x, spec.start.y)
    p1 = (spec.end.x, spec.end.y)
    m0 = (math.cos(spec.start.heading) * chord, math.sin(spec.start.heading) * chord)
    m1 = (math.cos(spec.end.heading) * chord, math.sin(spec.end.heading) * chord)
    h00 = 2*t**3 - 3*t**2 + 1
    h10 = t**3 - 2*t**2 + t
    h01 = -2*t**3 + 3*t**2
    h11 = t**3 - t**2
    return tuple(h00*a + h10*b + h01*c + h11*d for a,b,c,d in zip(p0,m0,p1,m1))

def _path_length(spec: RingSegmentSpec, samples: int = 64) -> float:
    points = [_hermite_xy(spec, i / samples) for i in range(samples + 1)]
    return sum(math.hypot(x1-x0, y1-y0) for (x0,y0),(x1,y1) in zip(points, points[1:]))

def build_segment_xml(spec: RingSegmentSpec, junction_id: str, *, z_start: float = 0.0, z_end: float | None = None) -> ET.Element:
    """Build a bounded paramPoly3 segment satisfying both endpoint positions."""
    z_end = z_start if z_end is None else z_end
    length=_path_length(spec)
    if not math.isfinite(length) or length <= 0:
        raise ValueError("ring segment has invalid fitted length")
    road=ET.Element("road",{"id":spec.road_id,"name":"roundabout_v2_segment","length":f"{length:.9f}","junction":str(junction_id)})
    pv=ET.SubElement(road,"planView")
    g=ET.SubElement(pv,"geometry",{"s":"0","x":f"{spec.start.x:.9f}","y":f"{spec.start.y:.9f}","hdg":f"{spec.start.heading:.12f}","length":f"{length:.9f}"})
    # The geometry uses a normalized parameter.  Coefficients are local to the
    # geometry frame and are converted from the global Hermite constraints.
    chord=spec.length
    tx0,ty0=math.cos(spec.start.heading)*chord,math.sin(spec.start.heading)*chord
    tx1,ty1=math.cos(spec.end.heading)*chord,math.sin(spec.end.heading)*chord
    dx,dy=spec.end.x-spec.start.x,spec.end.y-spec.start.y
    ca,sa=math.cos(-spec.start.heading),math.sin(-spec.start.heading)
    ex,ey=dx*ca-dy*sa,dx*sa+dy*ca
    end_tx,end_ty=tx1*ca-ty1*sa,tx1*sa+ty1*ca
    u=[0.0,tx0,3*ex-2*tx0-end_tx,-2*ex+tx0+end_tx]
    v=[0.0,ty0,3*ey-2*ty0-end_ty,-2*ey+ty0+end_ty]
    ET.SubElement(g,"paramPoly3",{**{f"{k}U":f"{val:.12g}" for k,val in zip("abcd",u)},**{f"{k}V":f"{val:.12g}" for k,val in zip("abcd",v)},"pRange":"normalized"})
    ep=ET.SubElement(road,"elevationProfile"); a,b,c,d=hermite_coefficients(z_start,0.0,z_end,0.0,length); ET.SubElement(ep,"elevation",{"s":"0","a":f"{a:.12g}","b":f"{b:.12g}","c":f"{c:.12g}","d":f"{d:.12g}"})
    lanes=ET.SubElement(road,"lanes"); sec=ET.SubElement(lanes,"laneSection",{"s":"0"}); center=ET.SubElement(sec,"center"); ET.SubElement(center,"lane",{"id":"0","type":"none","level":"false"})
    sides={}
    for lane_id in spec.lane_ids:
        side_name="left" if lane_id > 0 else "right"
        side=sides.setdefault(side_name, ET.SubElement(sec,side_name))
        lane=ET.SubElement(side,"lane",{"id":str(lane_id),"type":"driving","level":"false"}); ET.SubElement(lane,"width",{"sOffset":"0","a":"3.5","b":"0","c":"0","d":"0"})
    return road

def build_segment_roads(specs: list[RingSegmentSpec], junction_id: str, *, z_start: float = 0.0) -> list[ET.Element]:
    """Build a closed ring and add deterministic road links between its segments."""
    roads = [build_segment_xml(spec, junction_id, z_start=z_start) for spec in specs]
    for index, road in enumerate(roads):
        links = road.find("link")
        if links is None:
            links = ET.SubElement(road, "link")
        ET.SubElement(links, "predecessor", {"elementType":"road", "elementId":specs[index-1].road_id, "contactPoint":"end"})
        ET.SubElement(links, "successor", {"elementType":"road", "elementId":specs[(index+1)%len(specs)].road_id, "contactPoint":"start"})
    return roads

def build_junction_lane_links(source_road_id: str, target_road_id: str, connection_id: str,
                              source_lane_ids: set[int], target_lane_ids: set[int]) -> ET.Element:
    """Serialize only validated lane mappings; never emit the -1/-1 sentinel."""
    links = map_lanes(source_lane_ids, target_lane_ids)
    connection = ET.Element("connection", {"id":connection_id, "incomingRoad":source_road_id,
                                            "connectingRoad":target_road_id, "contactPoint":"start"})
    for link in links:
        ET.SubElement(connection, "laneLink", {"from":str(link.source_lane_id), "to":str(link.target_lane_id)})
    return connection
