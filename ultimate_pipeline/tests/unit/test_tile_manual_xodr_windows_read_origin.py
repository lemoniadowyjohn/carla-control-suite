# ultimate_pipeline/tools/tile_manual_xodr_windows.py -- zero prior test
# coverage. Live: _read_origin_from_meta() is imported directly by
# run_full_domain_gap.py::_read_origin_from_meta() as a thin wrapper, used
# to recover a manual tile grid's origin for RQ1-relevant tile alignment.
#
# Reviewed carefully for the same "wrong key/wrong schema" bug class found
# elsewhere this session (e.g. evaluate_tiling.py's core_bbox/bbox/bounds
# fallback chain). Verified by cross-checking against the two real schemas
# this function must parse: TileMetadata.write_manifest()'s tile_manifest.json
# (top-level "tiles"/"origin_x"/"origin_y" keys) and
# TileMetadata.write_from_health()'s tile_metadata.json (per-tile "bounds"
# list, NOT "bbox" -- both are explicitly handled). No bug found; tests
# close coverage and pin down the two real schemas plus the min-corner
# aggregation semantics (origin = min over all tiles' own min_x, paired
# independently with min over all tiles' own min_y -- i.e. the union
# bbox's corner, not any single tile's corner).
from __future__ import annotations

import json
from pathlib import Path

from ultimate_pipeline.tools.tile_manual_xodr_windows import _read_origin_from_meta


def _write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_manifest_schema_reads_explicit_origin_and_settings(tmp_path: Path):
    manifest = {
        "schema_version": "1",
        "origin_x": 1000.5,
        "origin_y": -200.25,
        "tile_size_m": 500.0,
        "buffer_m": 50.0,
        "tiles": [{"id": "tile_0_0.xodr", "bbox": {"min_x": 1000.5, "min_y": -200.25, "max_x": 1500.5, "max_y": 299.75}}],
    }
    path = _write_json(tmp_path / "tile_manifest.json", manifest)

    ox, oy, ts, bm = _read_origin_from_meta(path)

    assert ox == 1000.5
    assert oy == -200.25
    assert ts == 500.0
    assert bm == 50.0


def test_manifest_schema_with_missing_optional_size_fields(tmp_path: Path):
    manifest = {"origin_x": 0.0, "origin_y": 0.0, "tiles": []}
    path = _write_json(tmp_path / "tile_manifest.json", manifest)

    ox, oy, ts, bm = _read_origin_from_meta(path)

    assert ox == 0.0
    assert oy == 0.0
    assert ts is None
    assert bm is None


def test_metadata_schema_uses_bounds_list_matching_write_from_health(tmp_path: Path):
    # Matches TileMetadata.write_from_health()'s real per-tile schema:
    # "bounds": [xmin, ymin, xmax, ymax] (a list, not a "bbox" dict).
    metadata = {
        "_settings_snapshot": {"some": "setting"},
        "tile_0_0.xodr": {"bounds": [100.0, 200.0, 600.0, 700.0]},
        "tile_1_0.xodr": {"bounds": [600.0, 50.0, 1100.0, 550.0]},
    }
    path = _write_json(tmp_path / "tile_metadata.json", metadata)

    ox, oy, ts, bm = _read_origin_from_meta(path)

    # union-bbox corner: min x across tiles (100.0) paired independently
    # with min y across tiles (50.0, from the OTHER tile) -- not either
    # single tile's own corner.
    assert ox == 100.0
    assert oy == 50.0
    assert ts is None
    assert bm is None


def test_metadata_schema_ignores_settings_snapshot_key(tmp_path: Path):
    metadata = {
        "_settings_snapshot": {"bounds": [-99999.0, -99999.0, 0.0, 0.0]},
        "tile_0_0.xodr": {"bounds": [10.0, 20.0, 30.0, 40.0]},
    }
    path = _write_json(tmp_path / "tile_metadata.json", metadata)

    ox, oy, _, _ = _read_origin_from_meta(path)

    assert ox == 10.0
    assert oy == 20.0


def test_metadata_schema_alternate_bbox_dict_form(tmp_path: Path):
    metadata = {
        "tile_0_0.xodr": {"bbox": {"min_x": 5.0, "min_y": 6.0, "max_x": 505.0, "max_y": 506.0}},
    }
    path = _write_json(tmp_path / "tile_metadata.json", metadata)

    ox, oy, _, _ = _read_origin_from_meta(path)

    assert ox == 5.0
    assert oy == 6.0


def test_metadata_schema_skips_malformed_tile_entries_without_crashing(tmp_path: Path):
    metadata = {
        "tile_bad.xodr": {"bounds": None},
        "tile_also_bad.xodr": "not a dict",
        "tile_ok.xodr": {"bounds": [1.0, 2.0, 3.0, 4.0]},
    }
    path = _write_json(tmp_path / "tile_metadata.json", metadata)

    ox, oy, _, _ = _read_origin_from_meta(path)

    assert ox == 1.0
    assert oy == 2.0


def test_missing_file_returns_all_none(tmp_path: Path):
    ox, oy, ts, bm = _read_origin_from_meta(tmp_path / "does_not_exist.json")
    assert (ox, oy, ts, bm) == (None, None, None, None)


def test_malformed_json_returns_all_none(tmp_path: Path):
    path = tmp_path / "broken.json"
    path.write_text("{not valid json", encoding="utf-8")

    ox, oy, ts, bm = _read_origin_from_meta(path)

    assert (ox, oy, ts, bm) == (None, None, None, None)


def test_empty_tiles_dict_returns_all_none(tmp_path: Path):
    path = _write_json(tmp_path / "tile_metadata.json", {})

    ox, oy, ts, bm = _read_origin_from_meta(path)

    assert (ox, oy, ts, bm) == (None, None, None, None)


def test_non_dict_json_returns_all_none(tmp_path: Path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    ox, oy, ts, bm = _read_origin_from_meta(path)

    assert (ox, oy, ts, bm) == (None, None, None, None)
