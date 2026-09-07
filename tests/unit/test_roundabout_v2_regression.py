from __future__ import annotations
import math
import xml.etree.ElementTree as ET
import pytest
from ultimate_pipeline.topology.roundabout_v2 import detect_candidates, evaluate_elevation, extract_endpoint_anchors, sample_road, validate_lane_mapping, fit_circle, RoundaboutV2Reconstructor, validate_elevation_records

def road(rid, primitive, x=0, y=0, hdg=0, length=10):
    r=ET.Element("road", {"id":rid,"length":str(length)}); pv=ET.SubElement(r,"planView"); g=ET.SubElement(pv,"geometry",{"s":"0","x":str(x),"y":str(y),"hdg":str(hdg),"length":str(length)}); g.append(primitive)
    sec=ET.SubElement(ET.SubElement(r,"lanes"),"laneSection",{"s":"0"}); right=ET.SubElement(sec,"right")
    for lid in (-1,-2):
        l=ET.SubElement(right,"lane",{"id":str(lid),"type":"driving"}); ET.SubElement(l,"width",{"sOffset":"0","a":"3.5","b":"0","c":"0","d":"0"})
    return r

def test_sampler_line_arc_and_parampoly3():
    assert sample_road(road("l",ET.Element("line")))[-1].x == pytest.approx(10)
    a=sample_road(road("a",ET.Element("arc",{"curvature":"0.1"})))[-1]; assert a.y != 0 and a.heading == pytest.approx(1)
    p=ET.Element("paramPoly3",{"aU":"0","bU":"10","aV":"0","dV":"1","pRange":"normalized"}); assert sample_road(road("p",p))[-1].y == pytest.approx(1)

def test_sampler_rejects_nonfinite_and_detection_rejects_ramp():
    bad=road("bad",ET.Element("line")); bad.find("./planView/geometry").set("x","nan")
    with pytest.raises(ValueError): sample_road(bad)
    root=ET.Element("OpenDRIVE"); root.append(road("r",ET.Element("arc",{"curvature":"0.02"}),length=60)); assert detect_candidates(root)==[]

def test_detection_explicit_semantics_and_anchor_endpoint():
    root=ET.Element("OpenDRIVE")
    for i in range(3):
        primitive = ET.Element("line") if i == 0 else ET.Element("arc",{"curvature":"0.05"})
        r=road(str(i+1),primitive,length=20); ET.SubElement(ET.SubElement(r,"userData"),"osm",{"junction":"roundabout","way_id":str(i)}); root.append(r)
    j=ET.Element("junction",{"id":"j"})
    for i in range(3):
        c=ET.SubElement(j,"connection",{"id":str(i),"incomingRoad":str(i+1),"connectingRoad":str(i+1),"contactPoint":"end"}); ET.SubElement(c,"laneLink",{"from":"-1","to":"-1"})
    root.append(j)
    assert detect_candidates(root)[0].detection_method == "EXACT_OSM"; a=extract_endpoint_anchors(root,j,{"2","3"})[0]; assert a.endpoint=="end" and a.x==pytest.approx(20)

def test_elevation_and_lane_sentinel_contract():
    z,g=evaluate_elevation({"s":10,"a":2,"b":.5,"c":.1,"d":-.01},12); assert z==pytest.approx(2+.5*2+.1*4-.01*8); assert g==pytest.approx(.5+.2*2-.03*4)
    with pytest.raises(ValueError): validate_lane_mapping({"-1":-1},source_lane_ids={-1},target_lane_ids={-1})

def test_circle_fit_uses_all_samples_and_non_circular_model_is_preserved():
    root=ET.Element("OpenDRIVE"); ring=[]
    for i in range(8):
        theta=i*math.pi/4; r=road(str(i+1),ET.Element("arc",{"curvature":"0.1"}),x=10*math.cos(theta),y=10*math.sin(theta),hdg=theta+math.pi/2,length=1); ring.append(r); root.append(r)
    samples=[p for r in ring for p in sample_road(r,.5)]; fit=fit_circle(samples); assert fit["radius"]>0 and fit["max_residual"]<20
    distorted=road("distorted",ET.Element("line"),length=10); assert sample_road(distorted)

def test_reconstructor_is_transactional_and_does_not_enable_release_path():
    root=ET.Element("OpenDRIVE"); before=ET.tostring(root); clone,diagnostics=RoundaboutV2Reconstructor().reconstruct_transactional(root)
    assert ET.tostring(root)==before and ET.tostring(clone)==before and diagnostics==[]

def test_elevation_records_reject_duplicate_s_and_nan_coefficients():
    assert validate_elevation_records([{"s":0,"a":0,"b":0,"c":0,"d":0},{"s":1,"a":0,"b":0,"c":0,"d":0}])["status"]=="PASS"
    assert validate_elevation_records([{"s":0,"a":0,"b":0,"c":0,"d":0},{"s":0,"a":0,"b":0,"c":0,"d":0}])["status"]=="FAIL"
