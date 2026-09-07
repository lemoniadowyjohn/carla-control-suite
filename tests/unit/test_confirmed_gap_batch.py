import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.lane_width_policy import apply_lane_width_policy
from ultimate_pipeline.enrichment.traffic_light_infer import TrafficLightInferer
from ultimate_pipeline.quality.map_hygiene import _build_adjacency
from ultimate_pipeline.tiling import tile_extractor

def _road(rid="1", **attrs):
    road=ET.Element("road", id=rid, length="10", **attrs)
    plan=ET.SubElement(road,"planView")
    ET.SubElement(plan,"geometry",s="0",x="0",y="0",hdg="0",length="10")
    ET.SubElement(ET.SubElement(plan,"geometry",s="10",x="10",y="0",hdg="0",length="1"),"line")
    lanes=ET.SubElement(road,"lanes"); section=ET.SubElement(lanes,"laneSection",s="0"); right=ET.SubElement(section,"right")
    return road

def test_valid_width_polynomial_is_not_flattened():
    root=ET.Element("OpenDRIVE"); road=_road(); lane=ET.SubElement(road.find("./lanes/laneSection/right"),"lane",id="-1",type="driving")
    ET.SubElement(lane,"width",sOffset="0",a="3.6",b="0.01",c="0",d="0"); root.append(road)
    apply_lane_width_policy(root)
    width=lane.find("width")
    assert width.get("a")=="3.6" and width.get("b")=="0.01"

def test_road_and_junction_ids_are_separate_graph_namespaces():
    road=_road("7"); junction=ET.Element("junction",id="7"); ET.SubElement(junction,"connection",incomingRoad="7",connectingRoad="7")
    graph=_build_adjacency([road],[junction])
    assert "road:7" in graph and "junction:7" in graph and graph["road:7"] != graph["junction:7"]

def test_signal_lane_reference_is_scoped_to_its_own_road():
    root=ET.Element("OpenDRIVE"); first=_road("1"); second=_road("2")
    for road in (first,second):
        section=road.find("./lanes/laneSection/right"); ET.SubElement(section,"lane",id="-1",type="driving")
    refs=ET.SubElement(ET.SubElement(first,"signals"),"signalReference",id="r",laneId="-2",s="1")
    root.extend((first,second))
    errors=TrafficLightInferer.validate_signal_references(root)
    assert len(errors)==1 and "road 1" in errors[0]

def test_bounds_cache_key_includes_geometry_content():
    tile_extractor._BOUNDS_CACHE.clear()
    first=_road("same"); second=_road("same"); second.find("./planView/geometry").set("x","100")
    tile_extractor._road_bounds(first); tile_extractor._road_bounds(second)
    assert len(tile_extractor._BOUNDS_CACHE)==2
