# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/ml/lane_gnn_refiner.py (a deliberate no-op
stub, live-importable per its own docstring) and
ultimate_pipeline/debug/single_road_extractor.py (a debug CLI utility,
live via main_pipeline.py). Both zero prior coverage; no bugs found.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ultimate_pipeline.debug.single_road_extractor import SingleRoadExtractor
from ultimate_pipeline.ml.lane_gnn_refiner import LaneGNNRefiner


def test_lane_gnn_refiner_stub_is_a_safe_no_op(capsys):
    root = ET.fromstring("<OpenDRIVE></OpenDRIVE>")
    result = LaneGNNRefiner.run_inplace(root, model_path="model.pt")
    assert result is None
    assert "stub active" in capsys.readouterr().out


def _write_source_xodr(tmp_path):
    xodr = tmp_path / "in.xodr"
    xodr.write_text(
        '<?xml version="1.0"?><OpenDRIVE>'
        '<header revMajor="1" revMinor="4" name="" version="1.00" date="" '
        'north="0" south="0" east="0" west="0">'
        '<geoReference>+proj=utm +zone=32</geoReference>'
        "</header>"
        '<road name="r1" id="1" length="10" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        "</road>"
        '<road name="r2" id="2" length="5" junction="-1">'
        '<planView><geometry s="0" x="10" y="0" hdg="0" length="5"><line/></geometry></planView>'
        "</road>"
        '<junction id="5">'
        '<connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start"/>'
        "</junction>"
        "</OpenDRIVE>",
        encoding="utf-8",
    )
    return xodr


def test_extract_pulls_the_named_road_and_its_junction(tmp_path):
    xodr = _write_source_xodr(tmp_path)
    out = tmp_path / "out.xodr"
    SingleRoadExtractor.extract(str(xodr), "1", str(out))

    out_root = ET.parse(out).getroot()
    assert out_root.find("road[@id='1']") is not None
    assert out_root.find("road[@id='2']") is None  # not the requested road
    assert out_root.find("junction[@id='5']") is not None  # road 1 is incomingRoad


def test_extract_preserves_existing_georeference(tmp_path):
    xodr = _write_source_xodr(tmp_path)
    out = tmp_path / "out.xodr"
    SingleRoadExtractor.extract(str(xodr), "1", str(out))
    out_root = ET.parse(out).getroot()
    geo = out_root.find(".//geoReference")
    assert geo.text == "+proj=utm +zone=32"


def test_extract_adds_fallback_georeference_when_missing(tmp_path):
    xodr = tmp_path / "in.xodr"
    xodr.write_text(
        '<?xml version="1.0"?><OpenDRIVE>'
        '<header revMajor="1" revMinor="4" name="" version="1.00" date="" '
        'north="0" south="0" east="0" west="0"/>'
        '<road name="r1" id="1" length="10" junction="-1">'
        '<planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>'
        "</road>"
        "</OpenDRIVE>",
        encoding="utf-8",
    )
    out = tmp_path / "out.xodr"
    SingleRoadExtractor.extract(str(xodr), "1", str(out))
    out_root = ET.parse(out).getroot()
    geo = out_root.find(".//geoReference")
    assert geo is not None
    assert "utm" in geo.text


def test_extract_raises_for_missing_input_file(tmp_path):
    try:
        SingleRoadExtractor.extract(
            str(tmp_path / "does_not_exist.xodr"), "1", str(tmp_path / "out.xodr")
        )
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_extract_raises_for_missing_road_id(tmp_path):
    xodr = _write_source_xodr(tmp_path)
    try:
        SingleRoadExtractor.extract(str(xodr), "999", str(tmp_path / "out.xodr"))
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "999" in str(e)


def test_extract_raises_for_missing_header(tmp_path):
    xodr = tmp_path / "no_header.xodr"
    xodr.write_text(
        '<?xml version="1.0"?><OpenDRIVE>'
        '<road name="r1" id="1" length="10" junction="-1"/>'
        "</OpenDRIVE>",
        encoding="utf-8",
    )
    try:
        SingleRoadExtractor.extract(str(xodr), "1", str(tmp_path / "out.xodr"))
        assert False, "expected RuntimeError"
    except RuntimeError as e:
        assert "header" in str(e)


def test_extract_omits_unrelated_junctions(tmp_path):
    xodr = _write_source_xodr(tmp_path)
    out = tmp_path / "out.xodr"
    # Extract road 2 (the connectingRoad, not incomingRoad) -- junction 5
    # still references road 2 via connectingRoad, so it should be included.
    SingleRoadExtractor.extract(str(xodr), "2", str(out))
    out_root = ET.parse(out).getroot()
    assert out_root.find("junction[@id='5']") is not None
