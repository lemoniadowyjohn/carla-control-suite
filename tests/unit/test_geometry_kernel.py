import math
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.geometry.opendrive_geometry_kernel import (
    bounding_box, curvature_at_s, endpoint, pose_at_s, project_point, sample,
)

def geom(kind, length, **attrs):
    g=ET.Element("geometry", {"x":"0","y":"0","hdg":"0","length":str(length), **attrs})
    ET.SubElement(g, kind, {k:str(v) for k,v in attrs.items() if k not in {"x","y","hdg","length"}})
    return g

def test_line_oracle():
    g=geom("line",10)
    assert (pose_at_s(g,5).x,pose_at_s(g,5).y,pose_at_s(g,5).heading,pose_at_s(g,5).curvature)==pytest.approx((5,0,0,0))
    assert (endpoint(g).x,endpoint(g).y,endpoint(g).heading,endpoint(g).curvature)==pytest.approx((10,0,0,0))
    assert bounding_box(g)==pytest.approx((0,0,10,0))
    assert project_point(g,4,2)==pytest.approx((4,2,2),abs=1e-6)

def test_arc_quarter_circle_oracle():
    g=geom("arc",math.pi*5, curvature=.2)
    p=pose_at_s(g,math.pi/2/.2)
    assert (p.x,p.y,p.heading,p.curvature)==pytest.approx((5,5,math.pi/2,.2),abs=1e-9)

def test_poly3_and_parampoly3_oracles():
    p=geom("poly3",2,a=0,b=1,c=0,d=0)
    assert pose_at_s(p,1).y==pytest.approx(1)
    assert curvature_at_s(p,0)==pytest.approx(0)
    n=geom("paramPoly3",10,aU=0,bU=10,cU=0,dU=0,aV=0,bV=0,cV=0,dV=1,pRange="normalized")
    assert pose_at_s(n,5).y==pytest.approx(.125)
    assert endpoint(n).y==pytest.approx(1)

def test_parampoly3_arclength_parameterization():
    g=geom("paramPoly3",10,aU=0,bU=1,cU=0,dU=0,aV=0,bV=2,cV=0,dV=0,pRange="arcLength")
    assert (pose_at_s(g,5).x,pose_at_s(g,5).y)==pytest.approx((5,10))

def test_clothoid_is_curved_and_deterministic():
    g=geom("spiral",10,curvStart=0,curvEnd=.2)
    a=pose_at_s(g,5); b=pose_at_s(g,5)
    assert a==b and a.y>0 and a.curvature==pytest.approx(.1,abs=1e-12)
    assert len(sample(g,1))==11

def test_invalid_primitive_is_rejected():
    g=ET.Element("geometry", {"x":"0","y":"0","hdg":"0","length":"1"})
    with pytest.raises(ValueError): pose_at_s(g,0)
