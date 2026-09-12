import xml.etree.ElementTree as ET

from ultimate_pipeline.quality.semantic_overlap import SemanticOverlapChecker
from ultimate_pipeline.quality.quality_gate_manager import QualityGateManager

class Report:
    def __init__(self): self.entries=[]
    def add(self,*args): self.entries.append(args)

def test_polygon_checker_detects_building_intersecting_buffered_road():
    root=ET.Element("OpenDRIVE")
    road=ET.SubElement(root,"road",id="r")
    plan=ET.SubElement(road,"planView")
    for x in (0,10):
        geometry=ET.SubElement(plan,"geometry",x=str(x),y="0",hdg="0",length="10",s=str(x)); ET.SubElement(geometry,"line")
    lanes=ET.SubElement(road,"lanes"); section=ET.SubElement(lanes,"laneSection",s="0"); right=ET.SubElement(section,"right"); lane=ET.SubElement(right,"lane",id="-1",type="driving"); ET.SubElement(lane,"width",a="3.5")
    obj=ET.SubElement(road,"objects"); building=ET.SubElement(obj,"object",id="b",type="building"); outline=ET.SubElement(building,"outline")
    for x,y in ((4,-1),(6,-1),(6,1),(4,1)): ET.SubElement(outline,"cornerGlobal",x=str(x),y=str(y))
    issues=SemanticOverlapChecker.check_xodr(root)
    assert issues == [{"building":"b","road":"r"}]

def test_quality_gate_records_polygon_and_legacy_comparison_without_failure():
    report=Report(); manager=QualityGateManager(report)
    root=ET.Element("OpenDRIVE")
    manager.gate_semantic_overlap(root)
    comparison=[entry for entry in report.entries if entry[1]=="semantic_overlap_comparison"]
    assert comparison and comparison[0][2]["polygon_issue_count"] == 0
    assert manager.get_failures() == {}
