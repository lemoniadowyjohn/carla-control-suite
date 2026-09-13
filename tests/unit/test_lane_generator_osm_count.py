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


def test_spatial_structural_metadata_controls_new_lane_count():
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="42", junction="-1")
    ET.SubElement(road, "lanes")

    assert LaneGenerator.ensure_lanes(
        root,
        verbose=False,
        structural_osm_meta={
            "42": {"lanes:forward": "2", "lanes:backward": "1"}
        },
    ) == 1

    section = road.find("./lanes/laneSection")
    assert len(section.findall("./left/lane[@type='driving']")) == 1
    assert len(section.findall("./right/lane[@type='driving']")) == 2
    sources = {
        vector.get("value")
        for vector in section.findall(
            ".//userData/vector[@key='lane_count_source']"
        )
    }
    assert sources == {"osm:lanes:forward+backward"}


def test_existing_lanes_are_provenanced_only_when_every_section_matches_spatial_osm():
    root = ET.fromstring(
        """<OpenDRIVE><road id="42" junction="-1"><lanes>
        <laneSection s="0"><left><lane id="1" type="driving"><width a="3.5"/></lane></left>
        <right><lane id="-1" type="driving"><width a="3.5"/></lane>
        <lane id="-2" type="driving"><width a="3.5"/></lane></right></laneSection>
        </lanes></road></OpenDRIVE>"""
    )

    assert LaneGenerator.ensure_lanes(
        root,
        verbose=False,
        structural_osm_meta={
            "42": {"lanes:forward": "2", "lanes:backward": "1"}
        },
    ) == 0

    values = root.findall(".//userData/vector[@key='lane_count_source']")
    assert {value.get("value") for value in values} == {
        "osm:lanes:forward+backward"
    }


def test_existing_lane_mismatch_is_not_relabelled_as_osm_confirmed():
    root = ET.fromstring(
        """<OpenDRIVE><road id="42" junction="-1"><lanes>
        <laneSection s="0"><left><lane id="1" type="driving"><width a="3.5"/></lane></left>
        <right><lane id="-1" type="driving"><width a="3.5"/></lane></right></laneSection>
        </lanes></road></OpenDRIVE>"""
    )

    LaneGenerator.ensure_lanes(
        root,
        verbose=False,
        structural_osm_meta={
            "42": {"lanes:forward": "2", "lanes:backward": "1"}
        },
    )

    assert root.findall(".//userData/vector[@key='lane_count_source']") == []
