import math
import xml.etree.ElementTree as ET
import pytest

from ultimate_pipeline.geometry.geometry_validator import GeometryValidator

def test_missing_geometry_origin_uses_previous_arc_endpoint():
    root=ET.Element("OpenDRIVE")
    road=ET.SubElement(root,"road",id="arc-backfill")
    plan=ET.SubElement(road,"planView")
    first=ET.SubElement(plan,"geometry",s="0",x="0",y="0",hdg="0",length=str(math.pi/2/.1))
    ET.SubElement(first,"arc",curvature=".1")
    second=ET.SubElement(plan,"geometry",s="15.7079632679",hdg="1.5707963268",length="5")
    ET.SubElement(second,"line")
    GeometryValidator.validate(root)
    assert float(second.get("x")) == pytest.approx(10.0)
    assert float(second.get("y")) == pytest.approx(10.0)
