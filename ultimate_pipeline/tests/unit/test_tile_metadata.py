# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/tiling/tile_metadata.py.

Live tile-metadata generator (used by TileStreamer, CARLA tile
inspection, domain-gap per-tile analysis per its own docstring). Zero
prior test coverage. Reviewed for the defect classes found elsewhere this
session -- no clear bug: _parse_tile_index silently defaults to (0, 0) on
an unparseable filename rather than skipping (unlike the sibling
tile_adjacency.py's _parse_index, which returns None), but generate_metadata
still keys each tile's metadata entry by its own filename (not by (i,j)),
so this can't cause two tiles' metadata to overwrite each other -- only a
malformed-named tile's own i/j fields would be wrong. Documented as
current behavior via a named test, not fixed.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from ultimate_pipeline.tiling.tile_metadata import TileMetadata


def _write_tile(tmp_path, name: str, roads_xml: str = "") -> None:
    (tmp_path / name).write_text(
        f'<?xml version="1.0"?><OpenDRIVE>{roads_xml}</OpenDRIVE>', encoding="utf-8"
    )


def _driving_road_xml(road_id: str, x: float, y: float, width: float = 3.5) -> str:
    return (
        f'<road id="{road_id}" length="10">'
        f'<planView><geometry s="0" x="{x}" y="{y}" hdg="0" length="10"/></planView>'
        f"<lanes><laneSection s=\"0\"><right>"
        f'<lane id="-1" type="driving"><width sOffset="0" a="{width}" b="0" c="0" d="0"/>'
        f"<link><successor id=\"-1\"/></link></lane>"
        f"</right></laneSection></lanes>"
        f"</road>"
    )


# ---------------------------------------------------------------------------
# _extract_bbox_from_root / structural counters
# ---------------------------------------------------------------------------


def test_extract_bbox_computes_min_max_across_geometries():
    root = ET.fromstring(
        "<OpenDRIVE>"
        + _driving_road_xml("1", 0, 0)
        + _driving_road_xml("2", 10, 20)
        + "</OpenDRIVE>"
    )
    bbox = TileMetadata._extract_bbox_from_root(root)
    assert bbox == (0.0, 0.0, 10.0, 20.0)


def test_extract_bbox_empty_root_returns_zero_box():
    root = ET.fromstring("<OpenDRIVE></OpenDRIVE>")
    assert TileMetadata._extract_bbox_from_root(root) == (0.0, 0.0, 0.0, 0.0)


def test_count_driving_lanes_semantic_includes_was_driving_flag():
    root = ET.fromstring(
        '<OpenDRIVE><road id="1"><lanes><laneSection s="0"><right>'
        '<lane id="-1" type="none" was_driving="true"/>'
        '<lane id="-2" type="driving"/>'
        '<lane id="-3" type="sidewalk"/>'
        "</right></laneSection></lanes></road></OpenDRIVE>"
    )
    assert TileMetadata._count_driving_lanes_semantic(root) == 2
    assert TileMetadata._count_driving_lanes_xml(root) == 1


def test_has_spawn_candidate_requires_min_width():
    root = ET.fromstring(
        "<OpenDRIVE>" + _driving_road_xml("1", 0, 0, width=1.0) + "</OpenDRIVE>"
    )
    assert TileMetadata._has_spawn_candidate(root, min_width=2.5) is False
    root2 = ET.fromstring(
        "<OpenDRIVE>" + _driving_road_xml("1", 0, 0, width=3.5) + "</OpenDRIVE>"
    )
    assert TileMetadata._has_spawn_candidate(root2, min_width=2.5) is True


def test_has_local_successor_true_when_a_lane_link_successor_exists():
    root = ET.fromstring("<OpenDRIVE>" + _driving_road_xml("1", 0, 0) + "</OpenDRIVE>")
    assert TileMetadata._has_local_successor(root) is True


def test_has_local_successor_false_when_none_exists():
    root = ET.fromstring(
        '<OpenDRIVE><road id="1"><lanes><laneSection s="0"><right>'
        '<lane id="-1" type="driving"/>'
        "</right></laneSection></lanes></road></OpenDRIVE>"
    )
    assert TileMetadata._has_local_successor(root) is False


# ---------------------------------------------------------------------------
# _parse_tile_index
# ---------------------------------------------------------------------------


def test_parse_tile_index_extracts_i_j():
    assert TileMetadata._parse_tile_index("tile_2_3.xodr") == (2, 3)


def test_parse_tile_index_unparseable_name_defaults_to_zero_zero():
    # Documented current behavior (not a fix target): unlike
    # tile_adjacency.py's _parse_index (returns None on failure),
    # this defaults to (0, 0) rather than signalling failure. Confirmed
    # this can't cause a metadata-entry collision since generate_metadata
    # keys entries by filename, not by (i, j).
    assert TileMetadata._parse_tile_index("not_a_tile_name.xodr") == (0, 0)


# ---------------------------------------------------------------------------
# generate_metadata
# ---------------------------------------------------------------------------


def test_generate_metadata_scans_tiles_dir(tmp_path):
    _write_tile(tmp_path, "tile_0_0.xodr", _driving_road_xml("1", 0, 0))
    _write_tile(tmp_path, "tile_0_1.xodr", "")  # no roads -> not drivable
    out_json = tmp_path / "meta" / "tile_metadata.json"

    meta = TileMetadata.generate_metadata(str(tmp_path), str(out_json))

    assert meta["tile_0_0.xodr"]["i"] == 0
    assert meta["tile_0_0.xodr"]["j"] == 0
    assert meta["tile_0_0.xodr"]["is_drivable"] is True
    assert meta["tile_0_1.xodr"]["is_drivable"] is False
    assert "_settings_snapshot" in meta

    on_disk = json.loads(out_json.read_text(encoding="utf-8"))
    assert on_disk == meta


def test_generate_metadata_raises_for_missing_directory(tmp_path):
    try:
        TileMetadata.generate_metadata(str(tmp_path / "does_not_exist"), str(tmp_path / "out.json"))
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_generate_metadata_ignores_non_xodr_files(tmp_path):
    _write_tile(tmp_path, "tile_0_0.xodr", "")
    (tmp_path / "readme.txt").write_text("not a tile", encoding="utf-8")
    meta = TileMetadata.generate_metadata(str(tmp_path), str(tmp_path / "out.json"))
    assert "readme.txt" not in meta


# ---------------------------------------------------------------------------
# load_metadata
# ---------------------------------------------------------------------------


def test_load_metadata_adds_alias_keys_without_extension(tmp_path):
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps({"tile_0_0.xodr": {"i": 0, "j": 0}}), encoding="utf-8")
    loaded = TileMetadata.load_metadata(str(meta_path))
    assert loaded["tile_0_0.xodr"] == loaded["tile_0_0"]


def test_load_metadata_does_not_overwrite_existing_base_key(tmp_path):
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "tile_0_0.xodr": {"i": 0, "j": 0, "marker": "ext"},
                "tile_0_0": {"marker": "base_original"},
            }
        ),
        encoding="utf-8",
    )
    loaded = TileMetadata.load_metadata(str(meta_path))
    assert loaded["tile_0_0"]["marker"] == "base_original"


def test_load_metadata_non_dict_json_returns_empty_dict(tmp_path):
    meta_path = tmp_path / "meta.json"
    meta_path.write_text("[1, 2, 3]", encoding="utf-8")
    assert TileMetadata.load_metadata(str(meta_path)) == {}


# ---------------------------------------------------------------------------
# write_manifest
# ---------------------------------------------------------------------------


def test_write_manifest_computes_origin_from_min_bbox_by_default(tmp_path):
    meta_path = tmp_path / "tile_metadata.json"
    meta_path.write_text(
        json.dumps(
            {
                "tile_0_0.xodr": {
                    "bbox": {"min_x": 5.0, "min_y": 10.0, "max_x": 15.0, "max_y": 20.0},
                    "center": {"x": 10.0, "y": 15.0},
                }
            }
        ),
        encoding="utf-8",
    )
    manifest = TileMetadata.write_manifest(
        str(tmp_path),
        str(meta_path),
        str(tmp_path / "manifest.json"),
        proj4_norm="+proj=utm",
        tile_size_m=100.0,
        buffer_m=5.0,
    )
    assert manifest["origin_x"] == 5.0
    assert manifest["origin_y"] == 10.0
    assert len(manifest["tiles"]) == 1
    assert manifest["tiles"][0]["id"] == "tile_0_0.xodr"


def test_write_manifest_skips_settings_snapshot_key(tmp_path):
    meta_path = tmp_path / "tile_metadata.json"
    meta_path.write_text(
        json.dumps(
            {
                "_settings_snapshot": {"TILE_BUFFER_M": 5},
                "tile_0_0.xodr": {
                    "bbox": {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 1.0},
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = TileMetadata.write_manifest(
        str(tmp_path),
        str(meta_path),
        str(tmp_path / "manifest.json"),
        proj4_norm="",
        tile_size_m=100.0,
        buffer_m=5.0,
    )
    assert len(manifest["tiles"]) == 1
    assert all(t["id"] != "_settings_snapshot" for t in manifest["tiles"])


def test_write_manifest_explicit_origin_overrides_computed(tmp_path):
    meta_path = tmp_path / "tile_metadata.json"
    meta_path.write_text(
        json.dumps(
            {
                "tile_0_0.xodr": {
                    "bbox": {"min_x": 5.0, "min_y": 10.0, "max_x": 15.0, "max_y": 20.0},
                }
            }
        ),
        encoding="utf-8",
    )
    manifest = TileMetadata.write_manifest(
        str(tmp_path),
        str(meta_path),
        str(tmp_path / "manifest.json"),
        proj4_norm="",
        tile_size_m=100.0,
        buffer_m=5.0,
        origin_x=999.0,
        origin_y=888.0,
    )
    assert manifest["origin_x"] == 999.0
    assert manifest["origin_y"] == 888.0


# ---------------------------------------------------------------------------
# write_from_health
# ---------------------------------------------------------------------------


def test_write_from_health_builds_metadata_from_tile_health_dict(tmp_path):
    tile_health = {
        "tile_1_2": {
            "num_roads": 3,
            "num_driving_lanes_xml": 2,
            "num_driving_lanes_semantic": 2,
            "is_drivable": True,
            "bounds": {"core": {"xmin": 0, "ymin": 0, "xmax": 10, "ymax": 10}},
        }
    }
    out = TileMetadata.write_from_health(
        str(tmp_path), tile_health, str(tmp_path / "meta.json")
    )
    assert out["tile_1_2.xodr"]["i"] == 1
    assert out["tile_1_2.xodr"]["j"] == 2
    assert out["tile_1_2.xodr"]["is_drivable"] is True
    assert out["tile_1_2.xodr"]["bounds"] == [0, 0, 10, 10]
