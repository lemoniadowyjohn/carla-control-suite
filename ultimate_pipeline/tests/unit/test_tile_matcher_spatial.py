from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ultimate_pipeline.core.georef_utils import canonical_manual_georeference
from ultimate_pipeline.domain_gap.tile_matcher import TileMatcher


def _write_tile(path: Path, x0: float, y0: float, x1: float, y1: float, georef: str) -> None:
    root = ET.Element("OpenDRIVE")
    header = ET.SubElement(root, "header", revMajor="1", revMinor="4", name=path.stem)
    geo = ET.SubElement(header, "geoReference")
    geo.text = georef

    road = ET.SubElement(root, "road", id="1", length="20", junction="-1", type="town")
    plan = ET.SubElement(road, "planView")
    ET.SubElement(plan, "geometry", s="0", x=str(x0), y=str(y0), hdg="0", length="10")
    ET.SubElement(plan, "geometry", s="10", x=str(x1), y=str(y1), hdg="0", length="10")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def test_match_tiles_one_to_one_finds_centroid_spatial_overlap(tmp_path: Path) -> None:
    manual_dir = tmp_path / "manual"
    auto_dir = tmp_path / "auto"
    manual_dir.mkdir()
    auto_dir.mkdir()
    georef = canonical_manual_georeference()

    _write_tile(manual_dir / "tile_0_0.xodr", 678000.0, 5403000.0, 678010.0, 5403010.0, georef)
    _write_tile(auto_dir / "tile_5_5.xodr", 678002.0, 5403002.0, 678012.0, 5403012.0, georef)

    matches, report = TileMatcher.match_tiles_one_to_one(str(manual_dir), str(auto_dir), min_iou=0.01, prefer_id=False)

    entry = matches["tile_0_0.xodr"]
    assert entry["match"] == "tile_5_5.xodr"
    assert entry["match_method"] == "centroid_spatial"
    assert entry["iou"] > 0.0
    assert report["pairing_method"] == "centroid_spatial"
    assert report["num_matches"] == 1


def test_match_tiles_one_to_one_reports_unmatched_when_no_spatial_candidate(tmp_path: Path) -> None:
    manual_dir = tmp_path / "manual"
    auto_dir = tmp_path / "auto"
    manual_dir.mkdir()
    auto_dir.mkdir()
    georef = canonical_manual_georeference()

    _write_tile(manual_dir / "tile_0_0.xodr", 678000.0, 5403000.0, 678010.0, 5403010.0, georef)
    _write_tile(auto_dir / "tile_9_9.xodr", 700000.0, 5600000.0, 700010.0, 5600010.0, georef)

    matches, report = TileMatcher.match_tiles_one_to_one(str(manual_dir), str(auto_dir), min_iou=0.5, prefer_id=False)

    entry = matches["tile_0_0.xodr"]
    assert entry["status"] in {"unmatched_no_candidate", "matched_low_iou"}
    if entry["match"] is not None:
        assert entry["match_method"] == "index_fallback"
        assert entry["match_quality"] == "fallback_index_match"
    assert report["num_matches"] in {0, 1}


def test_match_tiles_one_to_one_uses_metadata_bbox_for_centroid_when_available(tmp_path: Path) -> None:
    manual_dir = tmp_path / "manual"
    auto_dir = tmp_path / "auto"
    manual_dir.mkdir()
    auto_dir.mkdir()
    georef = canonical_manual_georeference()

    _write_tile(manual_dir / "tile_62_23.xodr", 0.0, 0.0, 10.0, 10.0, georef)

    auto_root = ET.Element("OpenDRIVE")
    header = ET.SubElement(auto_root, "header", revMajor="1", revMinor="4", name="tile_0_0")
    geo = ET.SubElement(header, "geoReference")
    geo.text = georef
    ET.SubElement(header, "offset", x="-838640.80", y="-5464783.89", z="0", hdg="0")
    road = ET.SubElement(auto_root, "road", id="1", length="20", junction="-1", type="town")
    plan = ET.SubElement(road, "planView")
    ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="10")
    ET.SubElement(plan, "geometry", s="10", x="10", y="10", hdg="0", length="10")
    ET.ElementTree(auto_root).write(auto_dir / "tile_0_0.xodr", encoding="utf-8", xml_declaration=True)

    manual_meta = {
        "tile_62_23.xodr": {
            "bbox": {
                "min_x": 678000.0,
                "min_y": 5403000.0,
                "max_x": 678010.0,
                "max_y": 5403010.0,
            }
        }
    }
    auto_meta = {
        "tile_0_0.xodr": {
            "bbox": {
                "min_x": 678002.0,
                "min_y": 5403002.0,
                "max_x": 678012.0,
                "max_y": 5403012.0,
            }
        }
    }
    (manual_dir / "tile_metadata.json").write_text(json.dumps(manual_meta), encoding="utf-8")
    (auto_dir / "tile_metadata.json").write_text(json.dumps(auto_meta), encoding="utf-8")

    matches, report = TileMatcher.match_tiles_one_to_one(str(manual_dir), str(auto_dir), min_iou=0.01, prefer_id=False)

    entry = matches["tile_62_23.xodr"]
    assert entry["match"] == "tile_0_0.xodr"
    assert entry["match_method"] == "centroid_spatial"
    assert entry["iou"] > 0.0
    assert report["pairing_method"] == "centroid_spatial"


def test_match_tiles_one_to_one_uses_parent_bundle_metadata_for_tiles_subdir(tmp_path: Path) -> None:
    manual_root = tmp_path / "manual_bundle"
    auto_root = tmp_path / "auto_bundle"
    manual_dir = manual_root / "tiles"
    auto_dir = auto_root / "tiles"
    manual_dir.mkdir(parents=True)
    auto_dir.mkdir(parents=True)
    georef = canonical_manual_georeference()

    _write_tile(manual_dir / "tile_0_2.xodr", 0.0, 0.0, 10.0, 10.0, georef)

    auto_root_xml = ET.Element("OpenDRIVE")
    header = ET.SubElement(auto_root_xml, "header", revMajor="1", revMinor="4", name="tile_0_2")
    geo = ET.SubElement(header, "geoReference")
    geo.text = georef
    ET.SubElement(header, "offset", x="-838640.80", y="-5464783.89", z="0", hdg="0")
    road = ET.SubElement(auto_root_xml, "road", id="1", length="20", junction="-1", type="town")
    plan = ET.SubElement(road, "planView")
    ET.SubElement(plan, "geometry", s="0", x="0", y="0", hdg="0", length="10")
    ET.SubElement(plan, "geometry", s="10", x="10", y="10", hdg="0", length="10")
    ET.ElementTree(auto_root_xml).write(auto_dir / "tile_0_2.xodr", encoding="utf-8", xml_declaration=True)

    manual_meta = {
        "_settings_snapshot": {"TILE_BUFFER_M": 50.0},
        "tile_0_2.xodr": {
            "bounds": [678000.0, 5403000.0, 678010.0, 5403010.0],
        },
    }
    auto_meta = {
        "_settings_snapshot": {"TILE_BUFFER_M": 50.0},
        "tile_0_2.xodr": {
            "bounds": [678002.0, 5403002.0, 678012.0, 5403012.0],
        },
    }
    (manual_root / "tile_metadata.json").write_text(json.dumps(manual_meta), encoding="utf-8")
    (auto_root / "tile_metadata.json").write_text(json.dumps(auto_meta), encoding="utf-8")

    matches, report = TileMatcher.match_tiles_one_to_one(str(manual_dir), str(auto_dir), min_iou=0.01, prefer_id=False)

    entry = matches["tile_0_2.xodr"]
    assert entry["match"] == "tile_0_2.xodr"
    assert entry["match_method"] == "centroid_spatial"
    assert entry["match_quality"] == "good"
    assert entry["iou"] > 0.0
    assert report["pairing_method"] == "centroid_spatial"
    assert report["index_fallback_matches"] == 0
