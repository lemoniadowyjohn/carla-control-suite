from __future__ import annotations
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from statistics import median
from typing import Literal

@dataclass(frozen=True)
class Sample:
    road_id: str; s: float; x: float; y: float; heading: float; curvature: float | None = None

@dataclass(frozen=True)
class Candidate:
    junction_ids: tuple[str, ...]; road_ids: tuple[str, ...]; osm_way_ids: tuple[str, ...]
    detection_method: Literal["EXACT_OSM", "TOPOLOGY_HIGH", "GEOMETRY_HIGH", "HEURISTIC", "AMBIGUOUS", "REJECTED"]
    detection_confidence: float; reason: str

@dataclass(frozen=True)
class Anchor:
    anchor_id: str; road_id: str; endpoint: Literal["start", "end"]; lane_ids: tuple[int, ...]
    x: float; y: float; z: float | None; heading: float
    contact_role: Literal["entry", "exit", "bidirectional_unknown"]; connection_id: str | None = None

@dataclass
class RoundaboutModel:
    candidate: Candidate; samples: list[Sample] = field(default_factory=list)
    anchors: list[Anchor] = field(default_factory=list); geometry_kind: str = "SOURCE_PRESERVED"
    circle_fit: dict | None = None; action: str = "PRESERVED_VALID"

def fit_circle(samples: list[Sample]) -> dict:
    if len(samples) < 3: raise ValueError("circle fit requires at least three samples")
    m=[[0.0]*3 for _ in range(3)]; b=[0.0]*3
    for p in samples:
        row=(p.x,p.y,1.0); value=-(p.x*p.x+p.y*p.y)
        for i in range(3):
            b[i]+=row[i]*value
            for j in range(3): m[i][j]+=row[i]*row[j]
    for i in range(3):
        pivot=max(range(i,3),key=lambda k:abs(m[k][i]))
        if abs(m[pivot][i])<1e-12: raise ValueError("degenerate circle sample set")
        m[i],m[pivot]=m[pivot],m[i]; b[i],b[pivot]=b[pivot],b[i]; scale=m[i][i]
        m[i]=[x/scale for x in m[i]]; b[i]/=scale
        for k in range(3):
            if k==i: continue
            scale=m[k][i]; m[k]=[x-scale*y for x,y in zip(m[k],m[i])]; b[k]-=scale*b[i]
    cx,cy=-b[0]/2,-b[1]/2; r2=cx*cx+cy*cy-b[2]
    if not math.isfinite(r2) or r2<=0: raise ValueError("invalid fitted circle radius")
    radius=math.sqrt(r2); residuals=[abs(math.hypot(p.x-cx,p.y-cy)-radius) for p in samples]
    return {"center_x":cx,"center_y":cy,"radius":radius,"rmse":math.sqrt(sum(x*x for x in residuals)/len(residuals)),"median_abs_residual":median(residuals),"max_residual":max(residuals),"inlier_ratio":sum(x<=max(.25,2*math.sqrt(sum(y*y for y in residuals)/len(residuals))) for x in residuals)/len(residuals)}

def choose_geometry_model(samples: list[Sample], threshold: float) -> tuple[str,dict]:
    fit=fit_circle(samples)
    return ("CIRCLE_FIT" if fit["rmse"]<=threshold else "SOURCE_PRESERVED_NON_CIRCULAR", fit)

def _primitive(geometry: ET.Element) -> ET.Element:
    child = next(iter(geometry), None)
    if child is None: raise ValueError("geometry has no primitive")
    return child

def sample_road(road: ET.Element, spacing_m: float = 1.0) -> list[Sample]:
    if not math.isfinite(spacing_m) or spacing_m <= 0: raise ValueError("spacing_m must be finite and positive")
    rid = road.get("id") or ""; result: list[Sample] = []
    for g in road.findall("./planView/geometry"):
        s0, x0, y0, hdg, length = [float(g.get(k, "0")) for k in ("s", "x", "y", "hdg", "length")]
        if not all(math.isfinite(v) for v in (s0, x0, y0, hdg, length)) or length <= 0: raise ValueError(f"road {rid} has non-finite geometry")
        p = _primitive(g); n = max(1, math.ceil(length / spacing_m))
        for i in range(n + 1):
            u = length * i / n; tag = p.tag
            if tag == "line": lx, ly, lh, curv = u, 0.0, 0.0, None
            elif tag == "arc":
                curv = float(p.get("curvature", "0"));
                if not math.isfinite(curv): raise ValueError("non-finite arc curvature")
                if abs(curv) < 1e-12: lx, ly, lh = u, 0.0, 0.0
                else: lx, ly, lh = math.sin(curv*u)/curv, (1-math.cos(curv*u))/curv, curv*u
            elif tag == "paramPoly3":
                q = u / length if p.get("pRange", "normalized") == "normalized" else u
                lx = sum(float(p.get(f"{c}U", "0"))*q**j for j,c in enumerate("abcd")); ly = sum(float(p.get(f"{c}V", "0"))*q**j for j,c in enumerate("abcd"))
                du = sum(j*float(p.get(f"{c}U", "0"))*q**(j-1) for j,c in enumerate("abcd") if j); dv = sum(j*float(p.get(f"{c}V", "0"))*q**(j-1) for j,c in enumerate("abcd") if j)
                lh, curv = math.atan2(dv, du), None
            elif tag == "poly3":
                ly = sum(float(p.get(c, "0"))*u**j for j,c in enumerate("abcd")); lx, lh, curv = u, math.atan2(sum(j*float(p.get(c, "0"))*u**(j-1) for j,c in enumerate("abcd") if j), 1), None
            else: raise ValueError(f"unsupported OpenDRIVE geometry primitive: {tag}")
            x, y = x0 + math.cos(hdg)*lx - math.sin(hdg)*ly, y0 + math.sin(hdg)*lx + math.cos(hdg)*ly
            if not all(math.isfinite(v) for v in (x, y, hdg+lh)): raise ValueError(f"road {rid} has non-finite sampled geometry")
            result.append(Sample(rid, s0+u, x, y, hdg+lh, curv))
    if not result: raise ValueError(f"road {rid} has no planView geometry")
    return result

def _marker(road: ET.Element) -> tuple[bool, str | None]:
    for node in road.findall(".//userData/*"):
        values = {str(k).lower(): str(v).lower() for k,v in node.attrib.items()}
        if values.get("junction") in {"roundabout", "circular"}:
            return True, node.get("way_id") or node.get("id")
    return False, None

def detect_candidates(root: ET.Element) -> list[Candidate]:
    roads = {r.get("id"): r for r in root.findall("road") if r.get("id")}; out=[]
    for j in root.findall("junction"):
        ids=sorted({rid for c in j.findall("connection") for rid in (c.get("incomingRoad"),c.get("connectingRoad")) if rid in roads})
        if len(j.findall("connection")) < 3 or len(ids) < 3: continue
        marks=[_marker(roads[r]) for r in ids]; ways=sorted(w for ok,w in marks if ok and w)
        if ways: out.append(Candidate((j.get("id") or "",),tuple(ids),tuple(ways),"EXACT_OSM",1.0,"explicit OSM semantics")); continue
        curvy=sum(any(g.find("arc") is not None or g.find("spiral") is not None for g in roads[r].findall("./planView/geometry")) for r in ids)
        if curvy >= 3: out.append(Candidate((j.get("id") or "",),tuple(ids),(),"TOPOLOGY_HIGH",0.8,"junction-connected curved component"))
    return out

def _lanes(road: ET.Element) -> tuple[int,...]:
    ids=[]
    for lane in road.findall("./lanes/laneSection/*/lane"):
        if lane.get("type") == "driving": ids.append(int(lane.get("id","0")))
    return tuple(sorted(set(i for i in ids if i)))

def extract_endpoint_anchors(root: ET.Element, junction: ET.Element, ring_road_ids: set[str]) -> list[Anchor]:
    roads={r.get("id"):r for r in root.findall("road") if r.get("id")}; out=[]
    for c in sorted(junction.findall("connection"), key=lambda e:e.get("id", "")):
        rid=c.get("incomingRoad") or ""; road=roads.get(rid)
        if road is None or rid in ring_road_ids: continue
        cp=(c.get("contactPoint") or "").lower()
        if cp not in {"start","end"}: raise ValueError("ambiguous contact point")
        s=sample_road(road); p=s[0] if cp == "start" else s[-1]; z=None
        records=[]
        for e in road.findall("./elevationProfile/elevation"):
            records.append({k:float(e.get(k,"0")) for k in ("s","a","b","c","d")})
        if records:
            active=max((r for r in records if r["s"] <= p.s), key=lambda r:r["s"], default=records[0])
            z,_=evaluate_elevation(active,p.s)
        out.append(Anchor(f"{junction.get('id')}:{c.get('id')}:{rid}",rid,cp,_lanes(road),p.x,p.y,z,p.heading,"entry",c.get("id")))
    return out

def evaluate_elevation(record: dict, s: float) -> tuple[float,float]:
    ds=float(s)-float(record["s"]); a,b,c,d=(float(record[k]) for k in "abcd")
    z=a+b*ds+c*ds**2+d*ds**3; grade=b+2*c*ds+3*d*ds**2
    if not all(math.isfinite(v) for v in (z,grade)): raise ValueError("non-finite elevation evaluation")
    return z,grade

def validate_lane_mapping(mapping: dict[str,int], *, source_lane_ids: set[int], target_lane_ids: set[int]) -> None:
    """Validate explicit lane IDs; ``-1`` is valid when present in both sections.

    The former implementation treated the rightmost driving lane ID as an
    unknown sentinel.  Missing or implicit mappings are rejected by the
    caller, while an explicit OpenDRIVE ``-1`` lane reference is legitimate.
    """
    for source,target in mapping.items():
        source,target=int(source),int(target)
        if source not in source_lane_ids or target not in target_lane_ids: raise ValueError("lane-link references missing lane")

def infer_lane_model(roads: list[ET.Element]) -> tuple[tuple[int,...], tuple[dict,...]]:
    ids=[]
    for road in roads: ids.extend(_lanes(road))
    unique=tuple(sorted(set(ids),key=lambda x:(abs(x),x))) or (-1,)
    source="existing_xodr" if ids else "explicit_fallback"
    confidence=1.0 if ids else 0.0
    return unique,tuple({"lane_id":i,"source":source,"confidence":confidence} for i in unique)
