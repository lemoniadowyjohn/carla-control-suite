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

def test_quality_gate_records_clean_polygon_and_legacy_comparison_without_failure():
    report=Report(); manager=QualityGateManager(report)
    root=ET.Element("OpenDRIVE")
    manager.gate_semantic_overlap(root)
    comparison=[entry for entry in report.entries if entry[1]=="semantic_overlap_comparison"]
    assert comparison and comparison[0][2]["polygon_issue_count"] == 0
    assert manager.get_failures() == {}


def test_driving_extent_per_side_is_asymmetric_when_only_one_side_has_a_driving_lane():
    # Real fixture from the pinned map-of-record (road 42464): one driving
    # lane on the right (3.25m), only a sidewalk on the left -- no driving
    # lane there at all.
    road = ET.Element("road", id="r")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    left = ET.SubElement(section, "left")
    left_lane = ET.SubElement(left, "lane", id="1", type="sidewalk")
    ET.SubElement(left_lane, "width", a="2.0")
    right = ET.SubElement(section, "right")
    right_lane = ET.SubElement(right, "lane", id="-1", type="driving")
    ET.SubElement(right_lane, "width", a="3.25")

    left_extent, right_extent = SemanticOverlapChecker._driving_extent_per_side(road)

    assert left_extent == 0.0
    assert right_extent == 3.25


def test_building_near_non_driving_side_is_not_flagged():
    """The exact false-positive class found on the pinned map: a building
    sitting close to a road's sidewalk-only side must not be flagged as
    overlapping the road, since there is no driving lane there at all --
    a symmetric buffer using the driving lane's own width would wrongly
    reach across the centerline and catch it."""
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="r")
    plan = ET.SubElement(road, "planView")
    for x in (0, 10):
        geometry = ET.SubElement(plan, "geometry", x=str(x), y="0", hdg="0", length="10", s=str(x))
        ET.SubElement(geometry, "line")
    lanes = ET.SubElement(road, "lanes")
    section = ET.SubElement(lanes, "laneSection", s="0")
    left = ET.SubElement(section, "left")
    left_lane = ET.SubElement(left, "lane", id="1", type="sidewalk")
    ET.SubElement(left_lane, "width", a="2.0")
    right = ET.SubElement(section, "right")
    right_lane = ET.SubElement(right, "lane", id="-1", type="driving")
    ET.SubElement(right_lane, "width", a="3.25")
    obj = ET.SubElement(road, "objects")
    building = ET.SubElement(obj, "object", id="b", type="building")
    outline = ET.SubElement(building, "outline")
    # entirely on the LEFT (positive-y / positive-t) side, well outside the
    # sidewalk's own 2.0m width but well within the driving lane's 3.25m --
    # a symmetric buffer would wrongly flag this; an asymmetric one must not.
    for x, y in ((4, 2.5), (6, 2.5), (6, 3.0), (4, 3.0)):
        ET.SubElement(outline, "cornerGlobal", x=str(x), y=str(y))

    issues = SemanticOverlapChecker.check_xodr(root)

    assert issues == []


def test_quality_gate_exposes_polygon_overlap_to_strict_orchestration():
    report=Report(); manager=QualityGateManager(report)
    root=ET.Element("OpenDRIVE")
    road=ET.SubElement(root,"road",id="r")
    plan=ET.SubElement(road,"planView")
    for x in (0,10):
        geometry=ET.SubElement(plan,"geometry",x=str(x),y="0",hdg="0",length="10",s=str(x))
        ET.SubElement(geometry,"line")
    lanes=ET.SubElement(road,"lanes")
    section=ET.SubElement(lanes,"laneSection",s="0")
    right=ET.SubElement(section,"right")
    lane=ET.SubElement(right,"lane",id="-1",type="driving")
    ET.SubElement(lane,"width",a="3.5")
    obj=ET.SubElement(road,"objects")
    building=ET.SubElement(obj,"object",id="b",type="building")
    outline=ET.SubElement(building,"outline")
    for x,y in ((4,-1),(6,-1),(6,1),(4,1)):
        ET.SubElement(outline,"cornerGlobal",x=str(x),y=str(y))

    manager.gate_semantic_overlap(root)

    assert manager.get_failures() == {
        "semantic_overlap": [{"building":"b","road":"r"}]
    }
    assert any(
        entry[1] == "semantic_overlap" and entry[2]["status"] == "fail"
        for entry in report.entries
    )
