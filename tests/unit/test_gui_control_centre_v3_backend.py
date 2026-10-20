"""Offline source tests for v3 operator workspaces (no Qt or CARLA required)."""
from pathlib import Path
import pytest

from ultimate_pipeline.gui.control_center.map_analysis import (
    MapInspectionError, inspect_xml_map, inspect_dem, sample_geometry, evaluate_elevation,
)
from ultimate_pipeline.gui.control_center.plans import (
    EXPERIMENTS, ExperimentPlan, read_plan, save_plan,
)


def test_line_sampling_endpoints():
    pts = sample_geometry(0, 0, 0, 40)
    assert pts[0] == (0, 0)
    assert abs(pts[-1][0] - 40) < 1e-9


def test_arc_sampling_endpoints():
    pts = sample_geometry(3, -2, 0, 10, 0.1)
    assert pts[0] == (3, -2)
    assert 8 < pts[-1][0] < 13
    assert pts[-1][1] > -2


def test_invalid_segment_refused():
    with pytest.raises(MapInspectionError):
        sample_geometry(0, 0, 0, -1)
    with pytest.raises(MapInspectionError):
        sample_geometry(float('nan'), 0, 0, 5)


def test_opendrive_geometry_and_elevation(tmp_path):
    xodr = tmp_path / 'local.xodr'
    xodr.write_text('''<OpenDRIVE><header><geoReference>+proj=utm</geoReference></header>
    <road id="1"><planView><geometry x="0" y="1" hdg="0" length="20"><line/>
    </geometry></planView><elevationProfile><elevation s="0" a="42" b="0" c="0" d="0"/>
    </elevationProfile></road><junction id="2"/></OpenDRIVE>''')
    m = inspect_xml_map(xodr)
    assert m['roads'] == 1 and m['junctions'] == 1
    assert m['elevation_records'] == 1
    assert m['elevation_a_min'] == 42
    assert len(m['segments']) == 1
    assert m['georeference'] == '+proj=utm'


def test_malicious_doctype_rejected(tmp_path):
    p = tmp_path / 'bad.xodr'
    p.write_text('<!DOCTYPE OpenDRIVE [<!ENTITY a "text">]><OpenDRIVE>&a;</OpenDRIVE>')
    with pytest.raises(Exception):
        inspect_xml_map(p)


def test_invalid_map_type_and_size(tmp_path):
    p = tmp_path / 'map.json'
    p.write_text('{}')
    with pytest.raises(MapInspectionError):
        inspect_xml_map(p)
    p = tmp_path / 'empty.osm'
    p.touch()
    with pytest.raises(MapInspectionError):
        inspect_xml_map(p)


def test_experiment_plan_roundtrip(tmp_path):
    plan = ExperimentPlan('elevation_run', EXPERIMENTS[0], 9021, 'test.xodr', notes='sample')
    path = save_plan(plan, tmp_path / 'case.json')
    assert read_plan(path) == plan
    assert read_plan(path).execution_state == 'PLAN_ONLY_NOT_EXECUTED'


def test_plan_rejects_fabricated_execution(tmp_path):
    with pytest.raises(ValueError):
        ExperimentPlan('a', EXPERIMENTS[0], 2, execution_state='PASS')
    with pytest.raises(ValueError):
        ExperimentPlan('a', 'made up experiment', 2)
    with pytest.raises(ValueError):
        save_plan(ExperimentPlan('a', EXPERIMENTS[0], 2), tmp_path / 'unsafe.txt')


def test_plan_tampering_rejected(tmp_path):
    plan = ExperimentPlan('plan', EXPERIMENTS[-1], 1)
    path = save_plan(plan, tmp_path / 'case.json')
    path.write_text(path.read_text().replace('"schema":', '"extra": 1, "schema":'))
    with pytest.raises(ValueError):
        read_plan(path)


def test_elevation_polynomial_sections():
    records = [[0, 10, 0.2, 0, 0], [20, 14, -0.1, 0, 0]]
    assert evaluate_elevation(records, 10) == pytest.approx(12)
    assert evaluate_elevation(records, 20) == pytest.approx(14)
    assert evaluate_elevation(records, 30) == pytest.approx(13)
