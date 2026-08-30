# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/tiling/tile_adjacency.py.

Live: build_graph/save_graph called from stage_09_tiling.py:408-412.
are_adjacent/load_graph have zero live call sites currently (public API
awaiting a future consumer), but are_adjacent's own docstring states an
intent ("Missing keys? Treat as not adjacent (safe default)") that the
implementation only partially enforced -- see the bug below.

The bug: `if prev_name not in g and next_name not in g: return False`
only short-circuits to the safe default when BOTH names are absent from
the graph. If only ONE tile was pruned/removed from the graph's keys
after being built (e.g. quarantined post-tiling) but still lingers in a
sibling's stale `neighbors` list, are_adjacent would incorrectly report
True for a tile that no longer exists in the graph at all -- the opposite
of the documented "safe default".
"""
from __future__ import annotations

import json

from ultimate_pipeline.tiling.tile_adjacency import TileAdjacency


# ---------------------------------------------------------------------------
# _parse_index
# ---------------------------------------------------------------------------


def test_parse_index_extracts_i_j_from_filename():
    assert TileAdjacency._parse_index("tile_2_3.xodr") == (2, 3)


def test_parse_index_handles_negative_indices():
    assert TileAdjacency._parse_index("tile_-1_2.xodr") == (-1, 2)


def test_parse_index_rejects_non_tile_prefix():
    assert TileAdjacency._parse_index("road_2_3.xodr") is None


def test_parse_index_rejects_wrong_part_count():
    assert TileAdjacency._parse_index("tile_2.xodr") is None
    assert TileAdjacency._parse_index("tile_2_3_4.xodr") is None


def test_parse_index_rejects_non_numeric_parts():
    assert TileAdjacency._parse_index("tile_a_b.xodr") is None


def test_parse_index_uses_basename_not_full_path():
    assert TileAdjacency._parse_index("/some/dir/tile_5_6.xodr") == (5, 6)


# ---------------------------------------------------------------------------
# build_graph
# ---------------------------------------------------------------------------


def test_build_graph_links_four_neighborhood():
    tiles = ["tile_0_0.xodr", "tile_0_1.xodr", "tile_1_0.xodr"]
    graph = TileAdjacency.build_graph(tiles)
    assert set(graph["tile_0_0.xodr"]["neighbors"]) == {
        "tile_0_1.xodr",
        "tile_1_0.xodr",
    }
    assert graph["tile_0_1.xodr"]["neighbors"] == ["tile_0_0.xodr"]
    assert graph["tile_1_0.xodr"]["neighbors"] == ["tile_0_0.xodr"]


def test_build_graph_isolated_tile_has_no_neighbors():
    tiles = ["tile_0_0.xodr", "tile_9_9.xodr"]
    graph = TileAdjacency.build_graph(tiles)
    assert graph["tile_9_9.xodr"]["neighbors"] == []


def test_build_graph_skips_unparseable_names():
    tiles = ["tile_0_0.xodr", "not_a_tile.xodr"]
    graph = TileAdjacency.build_graph(tiles)
    assert "not_a_tile.xodr" not in graph
    assert "tile_0_0.xodr" in graph


# ---------------------------------------------------------------------------
# save_graph / load_graph
# ---------------------------------------------------------------------------


def test_save_and_load_graph_roundtrip(tmp_path):
    graph = TileAdjacency.build_graph(["tile_0_0.xodr", "tile_0_1.xodr"])
    out_path = tmp_path / "graph.json"
    TileAdjacency.save_graph(graph, str(out_path))

    on_disk = json.loads(out_path.read_text(encoding="utf-8"))
    assert on_disk == graph

    loaded = TileAdjacency.load_graph(str(out_path), use_cache=False)
    assert loaded == graph


def test_load_graph_non_dict_json_returns_empty_dict(tmp_path):
    out_path = tmp_path / "bad_graph.json"
    out_path.write_text("[1, 2, 3]", encoding="utf-8")
    assert TileAdjacency.load_graph(str(out_path), use_cache=False) == {}


# ---------------------------------------------------------------------------
# are_adjacent -- the bug
# ---------------------------------------------------------------------------


def test_are_adjacent_true_for_neighboring_tiles():
    graph = TileAdjacency.build_graph(["tile_0_0.xodr", "tile_0_1.xodr"])
    assert TileAdjacency.are_adjacent("tile_0_0.xodr", "tile_0_1.xodr", graph) is True


def test_are_adjacent_false_for_non_neighboring_tiles():
    graph = TileAdjacency.build_graph(["tile_0_0.xodr", "tile_9_9.xodr"])
    assert TileAdjacency.are_adjacent("tile_0_0.xodr", "tile_9_9.xodr", graph) is False


def test_are_adjacent_false_when_both_tiles_are_missing_from_graph():
    graph = TileAdjacency.build_graph(["tile_0_0.xodr"])
    assert (
        TileAdjacency.are_adjacent("tile_5_5.xodr", "tile_6_6.xodr", graph) is False
    )


def test_are_adjacent_false_when_the_other_tile_was_pruned_from_the_graph():
    # tile_0_1 was a real, correctly-built neighbor of tile_0_0 -- then
    # simulate it being pruned from the graph's own keys (e.g. quarantined
    # after tiling) WITHOUT the stale reference in tile_0_0's neighbor list
    # being cleaned up (build_graph never does this cleanup itself).
    graph = TileAdjacency.build_graph(["tile_0_0.xodr", "tile_0_1.xodr"])
    del graph["tile_0_1.xodr"]
    assert "tile_0_1.xodr" in graph["tile_0_0.xodr"]["neighbors"]  # stale reference

    # tile_0_1.xodr is no longer a present tile at all -- the documented
    # "safe default" (treat missing keys as not adjacent) must apply here,
    # not just when BOTH tiles are missing.
    assert (
        TileAdjacency.are_adjacent("tile_0_0.xodr", "tile_0_1.xodr", graph) is False
    )


def test_are_adjacent_accepts_a_graph_path_string(tmp_path):
    graph = TileAdjacency.build_graph(["tile_0_0.xodr", "tile_0_1.xodr"])
    graph_path = tmp_path / "graph.json"
    TileAdjacency.save_graph(graph, str(graph_path))
    assert (
        TileAdjacency.are_adjacent(
            "tile_0_0.xodr", "tile_0_1.xodr", str(graph_path)
        )
        is True
    )


def test_are_adjacent_accepts_full_paths_not_just_basenames():
    graph = TileAdjacency.build_graph(["tile_0_0.xodr", "tile_0_1.xodr"])
    assert (
        TileAdjacency.are_adjacent(
            "/out/tile_0_0.xodr", "/out/tile_0_1.xodr", graph
        )
        is True
    )
