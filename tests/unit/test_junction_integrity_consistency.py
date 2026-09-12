import xml.etree.ElementTree as ET

from ultimate_pipeline.quality.check_junction_integrity import JunctionIntegrityGate


def _root(connection_xml=""):
    return ET.fromstring(
        f'''<OpenDRIVE>
          <road id="1" junction="-1"><link><successor elementType="road" elementId="2"/></link>
            <lanes><laneSection s="0"><right><lane id="-1" type="driving"/></right></laneSection></lanes>
          </road>
          <road id="2" junction="-1"><lanes><laneSection s="0"><right><lane id="-1" type="driving"/></right></laneSection></lanes></road>
          <junction id="10">{connection_xml}</junction>
        </OpenDRIVE>'''
    )


def test_valid_road_link_and_connection_pass():
    root = _root('<connection id="c1" incomingRoad="1" connectingRoad="2" contactPoint="start"><laneLink from="-1" to="-1"/></connection>')
    result = JunctionIntegrityGate.validate(root)
    assert result["ok"]


def test_missing_predecessor_or_successor_target_is_reported():
    root = _root()
    root.find("./road[@id='1']/link/successor").set("elementId", "missing")
    result = JunctionIntegrityGate.validate(root)
    assert any(i["type"] == "invalid_successor_reference" for i in result["issues"])


def test_duplicate_connection_is_reported():
    xml = (
        '<connection id="c1" incomingRoad="1" connectingRoad="2" contactPoint="start"/>'
        '<connection id="c2" incomingRoad="1" connectingRoad="2" contactPoint="start"/>'
    )
    result = JunctionIntegrityGate.validate(_root(xml))
    assert any(i["type"] == "duplicate_connection" for i in result["issues"])


def test_conflicting_duplicate_connection_is_reported():
    xml = (
        '<connection id="c1" incomingRoad="1" connectingRoad="2" contactPoint="start"><laneLink from="-1" to="-1"/></connection>'
        '<connection id="c2" incomingRoad="1" connectingRoad="2" contactPoint="start"><laneLink from="-1" to="-1"/><laneLink from="-2" to="-1"/></connection>'
    )
    result = JunctionIntegrityGate.validate(_root(xml))
    assert any(i["type"] == "conflicting_duplicate_connection" for i in result["issues"])


def test_multiple_predecessors_are_reported():
    root = _root()
    link = root.find("./road[@id='1']/link")
    ET.SubElement(link, "predecessor", elementType="road", elementId="2")
    ET.SubElement(link, "predecessor", elementType="road", elementId="2")
    result = JunctionIntegrityGate.validate(root)
    assert any(i["type"] == "conflicting_predecessor_records" for i in result["issues"])
