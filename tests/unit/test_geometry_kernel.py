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


def test_sampling_uses_the_declared_length_at_a_nonrepresentable_endpoint():
    # This real map segment length previously rounded above its own declared
    # OpenDRIVE domain through ``length * n / n`` at the final sample.
    g = geom("line", 58.86684289)

    points = sample(g, 5.0)

    assert len(points) == 13
    assert points[-1].x == pytest.approx(58.86684289)

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


# ---------------------------------------------------------------------------
# Additional coverage: bounding_box/project_point for curved primitives,
# and malformed/non-finite attributes for every primitive type.
# ---------------------------------------------------------------------------

def test_bounding_box_arc():
    g = geom("arc", math.pi * 5, curvature=0.2)
    bx0, by0, bx1, by1 = bounding_box(g)
    # A quarter turn of radius 5 starting heading 0: bulges up to y=5, x up to 5+something.
    assert bx0 == pytest.approx(0.0, abs=1e-2)
    assert by0 == pytest.approx(0.0, abs=1e-2)
    assert bx1 > 0
    assert by1 > 0


def test_bounding_box_spiral():
    g = geom("spiral", 10, curvStart=0, curvEnd=0.2)
    bx0, by0, bx1, by1 = bounding_box(g)
    assert bx1 > bx0
    assert by1 >= by0


def test_bounding_box_parampoly3():
    g = geom("paramPoly3", 10, aU=0, bU=10, cU=0, dU=0, aV=0, bV=0, cV=0, dV=1, pRange="normalized")
    bx0, by0, bx1, by1 = bounding_box(g)
    assert bx0 == pytest.approx(0.0, abs=1e-6)
    assert bx1 == pytest.approx(10.0, abs=1e-6)
    assert by0 == pytest.approx(0.0, abs=1e-6)
    assert by1 == pytest.approx(1.0, abs=1e-6)


def test_project_point_arc():
    g = geom("arc", math.pi * 5, curvature=0.2)
    # Project the arc's own start point onto itself: nearest station is s=0.
    s, lateral, distance = project_point(g, 0.0, 0.0)
    assert s == pytest.approx(0.0, abs=1e-2)
    assert distance == pytest.approx(0.0, abs=1e-2)


def test_project_point_spiral():
    g = geom("spiral", 10, curvStart=0, curvEnd=0.2)
    ep = endpoint(g)
    s, lateral, distance = project_point(g, ep.x, ep.y)
    assert s == pytest.approx(10.0, abs=0.5)
    assert distance == pytest.approx(0.0, abs=1e-2)


@pytest.mark.parametrize("kind,attrs", [
    ("arc", {"curvature": "nan"}),
    ("arc", {"curvature": "inf"}),
    ("spiral", {"curvStart": "nan", "curvEnd": "0.1"}),
    ("spiral", {"curvStart": "0.0", "curvEnd": "inf"}),
    ("poly3", {"a": "nan", "b": "0", "c": "0", "d": "0"}),
    ("poly3", {"a": "0", "b": "inf", "c": "0", "d": "0"}),
    ("paramPoly3", {"aU": "nan", "bU": "1", "cU": "0", "dU": "0",
                     "aV": "0", "bV": "0", "cV": "0", "dV": "0"}),
    ("paramPoly3", {"aU": "0", "bU": "1", "cU": "0", "dU": "0",
                     "aV": "0", "bV": "0", "cV": "0", "dV": "inf"}),
])
def test_nonfinite_primitive_attribute_is_rejected(kind, attrs):
    g = geom(kind, 10, **attrs)
    with pytest.raises(ValueError):
        pose_at_s(g, 5)


def test_nonfinite_geometry_header_attribute_is_rejected():
    g = ET.Element("geometry", {"x": "nan", "y": "0", "hdg": "0", "length": "10"})
    ET.SubElement(g, "line")
    with pytest.raises(ValueError):
        pose_at_s(g, 5)


def test_s_outside_geometry_domain_is_rejected():
    g = geom("line", 10)
    with pytest.raises(ValueError):
        pose_at_s(g, 10.001)
    with pytest.raises(ValueError):
        pose_at_s(g, -0.001)


def test_sample_rejects_nonpositive_spacing():
    g = geom("line", 10)
    with pytest.raises(ValueError):
        sample(g, 0.0)
    with pytest.raises(ValueError):
        sample(g, -1.0)


def test_project_point_rejects_nonfinite_query_point():
    g = geom("line", 10)
    with pytest.raises(ValueError):
        project_point(g, float("nan"), 0.0)
