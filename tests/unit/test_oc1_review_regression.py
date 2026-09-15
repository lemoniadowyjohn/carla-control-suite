"""Regression tests for OC-1 review fixes: paramPoly3 pRange and GEOM-FREEZE-001."""
import xml.etree.ElementTree as ET
import pytest
from ultimate_pipeline.geometry.opendrive_geometry_kernel import pose_at_s
from ultimate_pipeline.core.stage_context import StageContext
from ultimate_pipeline.geometry.geometry_validator import canonical_horizontal_geometry_fingerprint

def test_paramPoly3_unknown_pRange_raises():
    geom = ET.Element('geometry', attrib={'x':'0','y':'0','hdg':'0','length':'10','s':'0'})
    prim = ET.Element('paramPoly3', attrib={'aU':'0','bU':'1','cU':'0','dU':'0','aV':'0','bV':'0','cV':'0','dV':'0','pRange':'foo'})
    geom.append(prim)
    with pytest.raises(ValueError, match="unsupported pRange"):
        pose_at_s(geom, 5)

def test_paramPoly3_normalized_works():
    geom = ET.Element('geometry', attrib={'x':'0','y':'0','hdg':'0','length':'10','s':'0'})
    prim = ET.Element('paramPoly3', attrib={'aU':'0','bU':'1','cU':'0','dU':'0','aV':'0','bV':'0','cV':'0','dV':'0','pRange':'normalized'})
    geom.append(prim)
    pose = pose_at_s(geom, 5)
    assert abs(pose.x - 0.5) < 1e-6

def test_paramPoly3_omitted_defaults_to_arclength():
    geom = ET.Element('geometry', attrib={'x':'0','y':'0','hdg':'0','length':'10','s':'0'})
    prim = ET.Element('paramPoly3', attrib={'aU':'0','bU':'1','cU':'0','dU':'0','aV':'0','bV':'0','cV':'0','dV':'0'})
    geom.append(prim)
    pose = pose_at_s(geom, 5)
    assert abs(pose.x - 5.0) < 1e-6

def test_geometry_freeze_fingerprint_mismatch_raises():
    root = ET.Element('OpenDRIVE')
    road = ET.SubElement(root, 'road', id='1', length='10')
    plan = ET.SubElement(road, 'planView')
    geom = ET.SubElement(plan, 'geometry', s='0', x='0', y='0', hdg='0', length='10')
    ET.SubElement(geom, 'line')
    ctx = StageContext()
    fp1 = canonical_horizontal_geometry_fingerprint(root)
    ctx.set_geometry_fingerprint(fp1)
    ctx.verify_geometry_fingerprint(fp1)  # should not raise
    geom.set('length', '20')
    fp2 = canonical_horizontal_geometry_fingerprint(root)
    with pytest.raises(RuntimeError, match="GEOM-FREEZE-001"):
        ctx.verify_geometry_fingerprint(fp2)
