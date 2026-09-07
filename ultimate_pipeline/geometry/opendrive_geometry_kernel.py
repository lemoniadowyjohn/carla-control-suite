"""Canonical, deterministic evaluation of OpenDRIVE plan-view primitives."""
from __future__ import annotations

import math
from dataclasses import dataclass
from xml.etree.ElementTree import Element

@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    heading: float
    curvature: float | None = None

def _f(element: Element, name: str) -> float:
    value = float(element.get(name, "nan"))
    if not math.isfinite(value):
        raise ValueError(f"non-finite geometry attribute: {name}")
    return value

def _primitive(geometry: Element) -> Element:
    child = next(iter(geometry), None)
    if child is None or child.tag.rsplit("}", 1)[-1] not in {"line", "arc", "spiral", "poly3", "paramPoly3"}:
        raise ValueError("unsupported or missing OpenDRIVE primitive")
    return child

def _local(primitive: Element, s: float, length: float) -> tuple[float, float, float, float | None]:
    kind = primitive.tag.rsplit("}", 1)[-1]
    if not 0.0 <= s <= length:
        raise ValueError("local s outside geometry")
    if kind == "line":
        return s, 0.0, 0.0, 0.0
    if kind == "arc":
        k = _f(primitive, "curvature")
        if abs(k) < 1e-14:
            return s, 0.0, 0.0, 0.0
        return math.sin(k*s)/k, (1-math.cos(k*s))/k, k*s, k
    if kind == "poly3":
        a,b,c,d=(_f(primitive, key) for key in "abcd")
        v=a+b*s+c*s*s+d*s*s*s
        dv=b+2*c*s+3*d*s*s
        ddv=2*c+6*d*s
        return s,v,math.atan2(dv,1.0),ddv/(1+dv*dv)**1.5
    if kind == "paramPoly3":
        p_range=primitive.get("pRange", "arcLength")
        p=s/length if p_range == "normalized" else s
        u=[_f(primitive,f"{c}U") for c in "abcd"]
        v=[_f(primitive,f"{c}V") for c in "abcd"]
        x=sum(value*p**i for i,value in enumerate(u)); y=sum(value*p**i for i,value in enumerate(v))
        dx=sum(i*value*p**(i-1) for i,value in enumerate(u) if i)
        dy=sum(i*value*p**(i-1) for i,value in enumerate(v) if i)
        ddx=sum(i*(i-1)*value*p**(i-2) for i,value in enumerate(u) if i > 1)
        ddy=sum(i*(i-1)*value*p**(i-2) for i,value in enumerate(v) if i > 1)
        denom=(dx*dx+dy*dy)**1.5
        return x,y,math.atan2(dy,dx),None if denom == 0 else (dx*ddy-dy*ddx)/denom
    # OpenDRIVE spiral/clothoid: deterministic RK4 integration of Frenet pose.
    k0,k1=_f(primitive,"curvStart"),_f(primitive,"curvEnd")
    if length <= 0: raise ValueError("geometry length must be positive")
    n=max(16, int(math.ceil(s/0.25))*4)
    h=s/n; x=y=heading=0.0
    def deriv(q: float, angle: float) -> tuple[float,float,float]:
        k=k0+(k1-k0)*q/length
        return math.cos(angle),math.sin(angle),k
    for i in range(n):
        q=i*h; a1=deriv(q,heading); a2=deriv(q+h/2,heading+a1[2]*h/2); a3=deriv(q+h/2,heading+a2[2]*h/2); a4=deriv(q+h,heading+a3[2]*h)
        x += h*(a1[0]+2*a2[0]+2*a3[0]+a4[0])/6; y += h*(a1[1]+2*a2[1]+2*a3[1]+a4[1])/6; heading += h*(a1[2]+2*a2[2]+2*a3[2]+a4[2])/6
    return x,y,heading,k0+(k1-k0)*s/length

def pose_at_s(geometry: Element, s: float) -> Pose:
    length=_f(geometry,"length"); x0,y0,hdg=_f(geometry,"x"),_f(geometry,"y"),_f(geometry,"hdg")
    lx,ly,lh,k=_local(_primitive(geometry),float(s),length)
    x=x0+math.cos(hdg)*lx-math.sin(hdg)*ly; y=y0+math.sin(hdg)*lx+math.cos(hdg)*ly
    return Pose(x,y,hdg+lh,k)

def heading_at_s(geometry: Element, s: float) -> float: return pose_at_s(geometry,s).heading
def curvature_at_s(geometry: Element, s: float) -> float | None: return pose_at_s(geometry,s).curvature
def endpoint(geometry: Element) -> Pose: return pose_at_s(geometry,_f(geometry,"length"))

def sample(geometry: Element, spacing: float) -> list[Pose]:
    if not math.isfinite(spacing) or spacing <= 0: raise ValueError("spacing must be positive")
    length=_f(geometry,"length"); n=max(1,math.ceil(length/spacing)); return [pose_at_s(geometry,length*i/n) for i in range(n+1)]

def bounding_box(geometry: Element, spacing: float = 0.25) -> tuple[float,float,float,float]:
    points=sample(geometry,spacing); xs=[p.x for p in points]; ys=[p.y for p in points]; return min(xs),min(ys),max(xs),max(ys)

def project_point(geometry: Element, x: float, y: float, spacing: float = 0.25) -> tuple[float,float,float]:
    if not all(math.isfinite(float(v)) for v in (x,y)): raise ValueError("point must be finite")
    length=_f(geometry,"length"); points=sample(geometry,spacing); best=None
    n=len(points)-1
    for index,(a,b) in enumerate(zip(points,points[1:])):
        vx,vy=b.x-a.x,b.y-a.y; den=vx*vx+vy*vy; t=0.0 if den == 0 else max(0.0,min(1.0,((x-a.x)*vx+(y-a.y)*vy)/den)); px,py=a.x+t*vx,a.y+t*vy; dx,dy=x-px,y-py; distance=math.hypot(dx,dy); lateral=-(x-a.x)*math.sin(a.heading)+(y-a.y)*math.cos(a.heading)
        lateral=-(x-px)*math.sin(a.heading)+(y-py)*math.cos(a.heading)
        candidate=(distance,(index+t)*length/n,lateral)
        if best is None or candidate[0]<best[0]: best=candidate
    return best[1],best[2],best[0]
