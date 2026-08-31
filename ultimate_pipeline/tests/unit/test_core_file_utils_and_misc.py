# Zero-prior-coverage core/ files, all with real live callers in
# main_pipeline.py: file_utils.py, repair_diff.py, return_codes.py,
# xodr_lightener.py. No bugs found in any of them.
from __future__ import annotations

import os
import xml.etree.ElementTree as ET

import pytest

from ultimate_pipeline.core.file_utils import copy_file, ensure_dir, read_xodr, write_xodr
from ultimate_pipeline.core.repair_diff import RepairDiff
from ultimate_pipeline.core.return_codes import PerceptionReturnCode
from ultimate_pipeline.core.xodr_lightener import strip_heavy_xodr_layers


# ---------------------------------------------------------------------------
# file_utils.py
# ---------------------------------------------------------------------------


def test_ensure_dir_creates_nested_path(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    ensure_dir(str(target))
    assert target.is_dir()


def test_ensure_dir_idempotent_on_existing_dir(tmp_path):
    ensure_dir(str(tmp_path))
    ensure_dir(str(tmp_path))  # must not raise


def test_copy_file_creates_dest_dir_and_copies_content(tmp_path):
    src = tmp_path / "src.txt"
    src.write_text("hello", encoding="utf-8")
    dst = tmp_path / "nested" / "dst.txt"

    copy_file(str(src), str(dst))

    assert dst.read_text(encoding="utf-8") == "hello"


def test_read_xodr_returns_tree_and_root(tmp_path):
    p = tmp_path / "in.xodr"
    p.write_text("<?xml version='1.0'?><OpenDRIVE><header/></OpenDRIVE>", encoding="utf-8")

    tree, root = read_xodr(str(p))

    assert root.tag == "OpenDRIVE"
    assert tree.getroot() is root


def test_write_xodr_normalizes_georeference_text(tmp_path):
    p_in = tmp_path / "in.xodr"
    p_in.write_text(
        "<?xml version='1.0'?><OpenDRIVE><header>"
        "<geoReference>  +proj=tmerc   +lat_0=1  </geoReference>"
        "</header></OpenDRIVE>",
        encoding="utf-8",
    )
    tree, root = read_xodr(str(p_in))
    p_out = tmp_path / "out.xodr"

    write_xodr(tree, str(p_out))

    out_tree = ET.parse(p_out)
    geo_text = out_tree.getroot().find("header").find("geoReference").text
    assert geo_text == "+proj=tmerc +lat_0=1"


def test_write_xodr_no_header_does_not_raise(tmp_path):
    root = ET.Element("OpenDRIVE")
    tree = ET.ElementTree(root)
    p_out = tmp_path / "no_header.xodr"

    write_xodr(tree, str(p_out))  # must not raise

    assert p_out.exists()


def test_write_xodr_creates_missing_output_dir(tmp_path):
    root = ET.Element("OpenDRIVE")
    tree = ET.ElementTree(root)
    p_out = tmp_path / "nested" / "out.xodr"

    write_xodr(tree, str(p_out))

    assert p_out.exists()


# ---------------------------------------------------------------------------
# repair_diff.py
# ---------------------------------------------------------------------------


def test_repair_diff_add_groups_events_by_stage():
    log = RepairDiff()
    log.add("geometry_validator", "42", {"fix": "clamped_curvStart"})
    log.add("geometry_validator", "43", {"fix": "clamped_curvEnd"})
    log.add("topology_repair", "1", {"fix": "merged_short_segment"})

    d = log.to_dict()
    assert len(d["geometry_validator"]) == 2
    assert len(d["topology_repair"]) == 1
    assert d["geometry_validator"][0]["road_id"] == "42"
    assert d["geometry_validator"][0]["fix"] == "clamped_curvStart"


def test_repair_diff_save_writes_valid_json(tmp_path):
    import json

    log = RepairDiff()
    log.add("stage_x", "7", {"detail": "value"})
    out = tmp_path / "repair_diff.json"

    log.save(str(out))

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["stage_x"][0]["road_id"] == "7"


# ---------------------------------------------------------------------------
# return_codes.py
# ---------------------------------------------------------------------------


def test_perception_return_code_ok_is_zero():
    assert PerceptionReturnCode.OK == 0


def test_perception_return_code_values_are_unique():
    values = [c.value for c in PerceptionReturnCode]
    assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# xodr_lightener.py
# ---------------------------------------------------------------------------


def _write_heavy_xodr(path) -> None:
    xml = """<?xml version="1.0"?>
    <OpenDRIVE>
      <road id="1" length="10">
        <objects><object id="o1" type="pole"/></objects>
        <signals><signal id="s1"/></signals>
        <lanes/>
      </road>
      <controller id="c1"/>
      <junctionGroup id="jg1"/>
    </OpenDRIVE>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)


def test_strip_heavy_layers_default_drops_objects_and_junction_groups(tmp_path):
    src = tmp_path / "in.xodr"
    dst = tmp_path / "out.xodr"
    _write_heavy_xodr(src)

    strip_heavy_xodr_layers(str(src), str(dst))

    root = ET.parse(dst).getroot()
    assert root.find(".//objects") is None
    assert root.find(".//junctionGroup") is None
    # controllers kept by default (CARLA-safe)
    assert root.find(".//controller") is not None
    # signals kept by default
    assert root.find(".//signals") is not None
    # roads/lanes untouched
    assert root.find(".//road") is not None
    assert root.find(".//lanes") is not None


def test_strip_heavy_layers_can_drop_controllers_and_signals(tmp_path):
    src = tmp_path / "in.xodr"
    dst = tmp_path / "out.xodr"
    _write_heavy_xodr(src)

    strip_heavy_xodr_layers(
        str(src), str(dst), drop_controllers=True, drop_signals=True
    )

    root = ET.parse(dst).getroot()
    assert root.find(".//controller") is None
    assert root.find(".//signals") is None


def test_strip_heavy_layers_can_disable_all_dropping(tmp_path):
    src = tmp_path / "in.xodr"
    dst = tmp_path / "out.xodr"
    _write_heavy_xodr(src)

    strip_heavy_xodr_layers(
        str(src), str(dst), drop_objects=False, drop_junction_groups=False
    )

    root = ET.parse(dst).getroot()
    assert root.find(".//objects") is not None
    assert root.find(".//junctionGroup") is not None
