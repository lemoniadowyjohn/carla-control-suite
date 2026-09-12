import json
import xml.etree.ElementTree as ET

from ultimate_pipeline.enrichment.lane_generator import LaneGenerator

def test_osm_directional_counts_emit_three_driving_lanes_and_provenance(tmp_path):
    root=ET.Element("OpenDRIVE")
    road=ET.SubElement(root,"road",id="42",junction="-1")
    ud=ET.SubElement(road,"userData")
    ET.SubElement(ud,"vector",key="osm:tag:lanes:forward",value="2")
    ET.SubElement(ud,"vector",key="osm:tag:lanes:backward",value="1")
    ET.SubElement(road,"lanes")
    report_path=tmp_path/"LANE_PROVENANCE_REPORT.json"
    assert LaneGenerator.ensure_lanes(root,verbose=False,provenance_report_path=report_path)==1
    section=road.find("./lanes/laneSection")
    assert len(section.findall("./left/lane[@type='driving']")) == 1
    assert len(section.findall("./right/lane[@type='driving']")) == 2
    lanes=section.findall("./left/lane")+section.findall("./right/lane")
    assert {lane.get("id") for lane in lanes} == {"1","-1","-2"}
    assert all(lane.find("./userData/vector[@key='lane_count_source']").get("value")=="osm:lanes:forward+backward" for lane in lanes)
    data=json.loads(report_path.read_text(encoding="utf-8"))
    assert data["roads"][0]["lanes"][0]["count"] == 3
