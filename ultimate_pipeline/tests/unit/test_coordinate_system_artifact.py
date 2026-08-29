# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/tools/coordinate_system_artifact.py.

Live: write_coordinate_system_json is called 8+ times by
run_full_domain_gap.py to record CRS/georeference provenance and
comparability between the manual and auto maps. Zero prior test coverage.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from ultimate_pipeline.core.georef_utils import CANONICAL_MANUAL_GEOREFERENCE
from ultimate_pipeline.tools.coordinate_system_artifact import (
    write_coordinate_system_json,
)


def _xodr(tmp_path, name, *, geo_ref=None, offset=None):
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header")
    if geo_ref is not None:
        geo = ET.SubElement(header, "geoReference")
        geo.text = geo_ref
    if offset is not None:
        ET.SubElement(header, "offset", **{k: str(v) for k, v in offset.items()})
    p = tmp_path / name
    ET.ElementTree(root).write(str(p), encoding="utf-8", xml_declaration=True)
    return p


def test_matching_crs_reports_crs_match(tmp_path):
    manual = _xodr(tmp_path, "manual.xodr", geo_ref=CANONICAL_MANUAL_GEOREFERENCE)
    auto = _xodr(tmp_path, "auto.xodr", geo_ref=CANONICAL_MANUAL_GEOREFERENCE)
    out = write_coordinate_system_json(tmp_path / "run", auto, manual_xodr_path=manual)
    payload = json.loads(out.read_text())
    assert payload["crs_match"] is True
    assert payload["comparability_status"] == "crs_match"
    assert payload["manual_georeference_valid"] is True
    assert payload["auto_georeference_valid"] is True


def test_mismatched_crs_reports_crs_mismatch(tmp_path):
    manual = _xodr(tmp_path, "manual.xodr", geo_ref=CANONICAL_MANUAL_GEOREFERENCE)
    auto = _xodr(tmp_path, "auto.xodr", geo_ref="+proj=utm +zone=32 +datum=WGS84 +units=m +no_defs")
    out = write_coordinate_system_json(tmp_path / "run", auto, manual_xodr_path=manual)
    payload = json.loads(out.read_text())
    assert payload["crs_match"] is False
    assert payload["comparability_status"] == "crs_mismatch"


def test_missing_manual_path_reports_manual_missing(tmp_path):
    auto = _xodr(tmp_path, "auto.xodr", geo_ref=CANONICAL_MANUAL_GEOREFERENCE)
    out = write_coordinate_system_json(tmp_path / "run", auto, manual_xodr_path=None)
    payload = json.loads(out.read_text())
    assert payload["comparability_status"] == "manual_missing"


def test_missing_georeference_reports_missing_status(tmp_path):
    manual = _xodr(tmp_path, "manual.xodr")  # no geoReference at all
    auto = _xodr(tmp_path, "auto.xodr", geo_ref=CANONICAL_MANUAL_GEOREFERENCE)
    out = write_coordinate_system_json(tmp_path / "run", auto, manual_xodr_path=manual)
    payload = json.loads(out.read_text())
    assert payload["comparability_status"] == "manual_georef_invalid"


def test_nonzero_offset_with_incomplete_crs_flagged_mixed(tmp_path):
    incomplete_crs = "+proj=tmerc +lat_0=0"  # valid ("+proj=") but not params_complete
    auto = _xodr(
        tmp_path, "auto.xodr",
        geo_ref=incomplete_crs,
        offset={"x": "832671.676", "y": "5458671.104", "z": "0.0", "hdg": "0.0"},
    )
    out = write_coordinate_system_json(tmp_path / "run", auto)
    payload = json.loads(out.read_text())
    assert payload["mixed_offset_incomplete_crs"] is True
    assert payload["offset_policy"] == "invalid_incomplete_crs_with_offset"


def test_zero_offset_with_incomplete_crs_not_flagged_mixed(tmp_path):
    incomplete_crs = "+proj=tmerc +lat_0=0"
    auto = _xodr(tmp_path, "auto.xodr", geo_ref=incomplete_crs)  # no offset -> defaults to 0
    out = write_coordinate_system_json(tmp_path / "run", auto)
    payload = json.loads(out.read_text())
    assert payload["mixed_offset_incomplete_crs"] is False
    assert payload["offset_policy"] == "allowed_with_complete_crs"


def test_sha256_computed_for_present_files(tmp_path):
    auto = _xodr(tmp_path, "auto.xodr", geo_ref=CANONICAL_MANUAL_GEOREFERENCE)
    out = write_coordinate_system_json(tmp_path / "run", auto)
    payload = json.loads(out.read_text())
    import hashlib
    assert payload["auto_xodr_sha256"] == hashlib.sha256(auto.read_bytes()).hexdigest()
    assert payload["manual_xodr_sha256"] is None


def test_coordinate_system_hash_is_deterministic_for_same_inputs(tmp_path):
    # hash_payload includes the xodr path strings themselves, so identical
    # content under different filenames legitimately hashes differently --
    # determinism must be tested with the SAME auto_xodr_path across calls.
    auto = _xodr(tmp_path, "auto.xodr", geo_ref=CANONICAL_MANUAL_GEOREFERENCE)
    out1 = write_coordinate_system_json(tmp_path / "run1", auto)
    out2 = write_coordinate_system_json(tmp_path / "run2", auto)
    p1 = json.loads(out1.read_text())
    p2 = json.loads(out2.read_text())
    assert p1["coordinate_system_hash"] == p2["coordinate_system_hash"]


def test_coordinate_system_hash_changes_with_geoReference(tmp_path):
    # Same filename both times (so the hashed path string is identical) --
    # the file must be written and read for run_a BEFORE being overwritten
    # for run_b, or both calls see the same final on-disk content.
    auto_a = _xodr(tmp_path, "auto_a.xodr", geo_ref=CANONICAL_MANUAL_GEOREFERENCE)
    out_a = write_coordinate_system_json(tmp_path / "run_a", auto_a)
    payload_a = json.loads(out_a.read_text())

    auto_b = _xodr(tmp_path, "auto_a.xodr", geo_ref="+proj=utm +zone=32 +datum=WGS84 +units=m +no_defs")
    out_b = write_coordinate_system_json(tmp_path / "run_b", auto_b)
    payload_b = json.loads(out_b.read_text())

    assert payload_a["coordinate_system_hash"] != payload_b["coordinate_system_hash"]
