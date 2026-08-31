# -*- coding: utf-8 -*-
"""Tests for two fixes in
ultimate_pipeline/pipeline_stages/stage_09_tiling.py's _step9_tiling().

1. The tile/metadata sync invariant used a bare `assert`, which Python's
   `-O` flag silently strips -- converted to an explicit
   `if ...: raise RuntimeError(...)` so a real tiler/metadata desync can
   never be silently skipped.
2. UP_SKIP_TILE_QA's truthy-value check was {"1","true","yes","y"} while
   every other env-flag check in this same file uses
   {"1","true","yes","on"} -- "on" was missing, inconsistent with the
   file's own established convention (someone setting
   UP_SKIP_TILE_QA=on, matching every sibling flag in this file, would
   have been silently ignored). Added "on" (keeping "y" for backward
   compatibility -- nothing else in the repo sets "y" specifically, but
   removing it isn't necessary to fix the bug).

Zero prior test coverage on _step9_tiling(). Note this file's
_inject_main_pipeline_globals() (unlike most sibling stage files)
UNCONDITIONALLY overwrites (`g[k] = v`, not `g.setdefault(k, v)`) --
patches applied directly to stage_09_tiling's own module namespace get
wiped out the moment _step9_tiling() calls it. Patches must instead
target ultimate_pipeline.main_pipeline's namespace (what injection pulls
from) for anything main_pipeline.py imports at module level; TileMetadata
is a LOCAL import inside _step9_tiling itself, so it must be patched at
its own source module directly.
"""
from __future__ import annotations

import json as json_mod

from unittest import mock

import pytest

import ultimate_pipeline.main_pipeline as main_pipeline_mod
import ultimate_pipeline.pipeline_stages.stage_09_tiling as stage_mod
import ultimate_pipeline.tiling.tile_metadata as tile_metadata_mod


def _make_fake_self(tmp_path):
    fake_settings = mock.Mock()
    fake_settings.ENABLE_TILING = True
    fake_settings.TILE_SIZE = 500.0
    fake_settings.TILE_BUFFER_M = 50.0
    fake_settings.STRICT_TILE_SEMANTICS = False
    fake_settings.ENABLE_LANESECTION_FIX = False
    fake_settings.TILE_ADJ_JSON = "tile_adjacency.json"
    fake_settings.AUTO_SCENARIO_COUNT = 1
    fake_settings.TILE_QA_RUN_SUBPROCESS_BATCH = True
    fake_settings.TILE_QA_ISOLATION_MODE = "subprocess"

    fake_self = mock.Mock()
    fake_self.settings = fake_settings
    fake_self.out_dir = str(tmp_path)
    fake_self.semantic_state = {"has_lanes": True}
    fake_self.vreport = mock.Mock()
    return fake_self


def _run_with_mocks(fake_self, final_out, tiles, tile_health):
    with mock.patch.object(
        main_pipeline_mod, "TileExtractor", mock.Mock(tile=mock.Mock(return_value=(tiles, tile_health)))
    ), mock.patch.object(
        main_pipeline_mod, "_read_georef_info", mock.Mock(return_value={}), create=True
    ), mock.patch.object(
        main_pipeline_mod, "TileAdjacency", mock.Mock(build_graph=mock.Mock(return_value={}), save_graph=mock.Mock())
    ), mock.patch.object(
        main_pipeline_mod,
        "AutoScenarioGenerator",
        mock.Mock(generate_from_graph=mock.Mock(return_value=[])),
    ), mock.patch.object(
        tile_metadata_mod.TileMetadata, "generate_metadata", mock.Mock()
    ), mock.patch.object(
        tile_metadata_mod.TileMetadata, "write_manifest", mock.Mock()
    ):
        return stage_mod._step9_tiling(fake_self, final_out)


def test_tile_metadata_mismatch_raises_not_silently_passes(tmp_path, monkeypatch):
    # Disable all optional quality sub-gates so we only reach the
    # invariant check.
    for flag in (
        "UP_ENABLE_PLANVIEW_SEAM_GATE",
        "UP_ENABLE_GEOMETRIC_CONTINUITY",
        "UP_ENABLE_POST_TILING_INTEGRITY",
        "UP_ENABLE_LANE_WIDTH_CONTINUITY",
    ):
        monkeypatch.setenv(flag, "0")

    fake_self = _make_fake_self(tmp_path)
    tiles = [str(tmp_path / "tiles" / "tile_0_0.xodr")]
    # tile_health deliberately does NOT match tiles -> real desync.
    tile_health = {"tile_9_9": {}}

    with pytest.raises(RuntimeError, match="Tile/metadata mismatch"):
        _run_with_mocks(fake_self, str(tmp_path / "final.xodr"), tiles, tile_health)


def test_tile_metadata_match_does_not_raise_and_reaches_skip_check(tmp_path, monkeypatch):
    for flag in (
        "UP_ENABLE_PLANVIEW_SEAM_GATE",
        "UP_ENABLE_GEOMETRIC_CONTINUITY",
        "UP_ENABLE_POST_TILING_INTEGRITY",
        "UP_ENABLE_LANE_WIDTH_CONTINUITY",
    ):
        monkeypatch.setenv(flag, "0")
    monkeypatch.setenv("UP_SKIP_TILE_QA", "on")

    fake_self = _make_fake_self(tmp_path)
    tile_name = "tile_0_0"
    tiles = [str(tmp_path / "tiles" / f"{tile_name}.xodr")]
    tile_health = {tile_name: {}}  # matches tiles -> invariant holds

    result = _run_with_mocks(fake_self, str(tmp_path / "final.xodr"), tiles, tile_health)

    # UP_SKIP_TILE_QA="on" must be recognized (matching every other
    # truthy-flag check in this file) and short-circuit before the
    # subprocess-based tile_qa_batch runner would ever be invoked.
    assert result == str(tmp_path / "tile_adjacency.json")
    status_path = tmp_path / "tile_qa_status.json"
    assert status_path.is_file()
    status = json_mod.loads(status_path.read_text(encoding="utf-8"))
    assert status["status"] == "SKIP"
