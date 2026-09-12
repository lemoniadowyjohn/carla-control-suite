from __future__ import annotations
import math
import xml.etree.ElementTree as ET
import pytest
from ultimate_pipeline.topology.roundabout_v2 import (Anchor, build_junction_lane_links, build_segment_roads,
    build_segment_specs, detect_candidates, evaluate, evaluate_elevation, extract_endpoint_anchors,
    fit_circle, hermite_coefficients, map_lanes, RoundaboutV2Reconstructor, sample_road,
    validate_lane_mapping, validate_elevation_records, validate_segmented_ring)
from ultimate_pipeline.topology.roundabout_v2 import lane_provenance_report

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
    validate_lane_mapping({"-1":-1},source_lane_ids={-1},target_lane_ids={-1})
    with pytest.raises(ValueError): validate_lane_mapping({"-1":-1},source_lane_ids=set(),target_lane_ids={-1})

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

def test_hermite_elevation_hits_both_values_and_grades():
    coeffs=hermite_coefficients(10.0, 0.2, 14.0, -0.1, 20.0)
    start={"s":0, **dict(zip("abcd", coeffs))}
    assert evaluate(start, 0)==pytest.approx((10.0, .2))
    assert evaluate(start, 20)==pytest.approx((14.0, -.1))

def test_segmented_ring_preserves_endpoints_links_and_multiple_lanes():
    anchors=[Anchor("a","in-a","end",(-1,-2),10,0,None,math.pi/2,"entry"),
             Anchor("b","in-b","end",(-1,-2),0,10,None,math.pi,"entry"),
             Anchor("c","in-c","end",(-1,-2),-10,0,None,-math.pi/2,"entry")]
    specs=build_segment_specs(anchors,0,0,900)
    roads=build_segment_roads(specs,"j")
    assert len(roads)==3
    assert all(len(r.findall("./lanes/laneSection/right/lane"))==2 for r in roads)
    assert roads[0].find("./link/predecessor").get("elementId")=="902"
    sampled=sample_road(roads[0], .25)
    assert (sampled[0].x,sampled[0].y)==pytest.approx((10,0))
    assert (sampled[-1].x,sampled[-1].y)==pytest.approx((0,10), abs=1e-8)
    assert validate_segmented_ring(roads)["status"]=="PASS"

def test_lane_mapping_and_serialization_are_fail_closed():
    links=map_lanes({-1,-2},{-1,-2})
    assert [(x.source_lane_id,x.target_lane_id) for x in links]==[(-1,-1),(-2,-2)]
    xml=build_junction_lane_links("in","ring","c",{-1,-2},{-1,-2})
    assert len(xml.findall("laneLink"))==2
    with pytest.raises(ValueError): build_junction_lane_links("in","ring","c",{-1},{-1,-2})

def test_segmented_ring_validator_rejects_dangling_link():
    anchors=[Anchor("a","x","end",(-1,),10,0,None,math.pi/2,"entry"),
             Anchor("b","y","end",(-1,),0,10,None,math.pi,"entry"),
             Anchor("c","z","end",(-1,),-10,0,None,-math.pi/2,"entry")]
    roads=build_segment_roads(build_segment_specs(anchors,0,0,910),"j")
    roads[0].find("./link/predecessor").set("elementId","missing")
    assert validate_segmented_ring(roads)["status"]=="FAIL"

def test_lane_provenance_is_explicit_and_deterministic():
    roads=[road("b",ET.Element("line")), road("a",ET.Element("line"))]
    report=lane_provenance_report(roads)
    assert [item["road_id"] for item in report["roads"]]==["a","b"]
    assert report["roads"][0]["lanes"][0]["source"]=="existing_xodr"
