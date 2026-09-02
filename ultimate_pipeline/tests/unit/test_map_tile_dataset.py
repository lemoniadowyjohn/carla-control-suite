# ultimate_pipeline/domain_gap_gnn/map_tile_dataset.py -- zero prior test
# coverage. Live and consequential: imported by
# domain_gap_gnn/train_map_encoder.py (the actual training script used
# for this session's real 5-seed GNN retrain that produced the currently
# AUTHORITATIVE RQ3-GNN evidence) and collapse_check.py. Wraps a directory
# of .xodr tiles as a PyTorch Dataset, delegating graph construction to
# the already-fixed-this-session MapGraphBuilder.build_from_xodr.
#
# Reviewed for correctness: deterministic file ordering (sorted at init,
# so dataset index -> filename mapping is stable across runs -- important
# for the "Deterministic loading" contract stated in its own docstring),
# invalid-tile skip vs strict-raise behavior, and the pre-validation vs
# access-time re-validation split. __getitem__ rebuilds the graph from
# disk on every access rather than caching it (a real inefficiency, not a
# correctness bug -- the retrain completed in the expected ~15-19 min/seed
# regardless, so not touched). No bug found.
from __future__ import annotations

from pathlib import Path

import pytest

from ultimate_pipeline.domain_gap_gnn.map_tile_dataset import MapTileDataset


VALID_XODR = """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
  <road name="R1" length="10.0" id="1" junction="-1">
    <planView><geometry s="0" x="0" y="0" hdg="0" length="10"><line/></geometry></planView>
    <lanes><laneSection s="0"><center><lane id="0" type="none"/></center>
    <right><lane id="-1" type="driving"/></right></laneSection></lanes>
  </road>
</OpenDRIVE>
"""


def test_loads_all_valid_tiles_in_sorted_order(tmp_path: Path):
    for name in ("tile_b.xodr", "tile_a.xodr", "tile_c.xodr"):
        (tmp_path / name).write_text(VALID_XODR, encoding="utf-8")

    ds = MapTileDataset(str(tmp_path))

    assert len(ds) == 3
    assert ds.files == ["tile_a.xodr", "tile_b.xodr", "tile_c.xodr"]
    assert ds.num_tiles == 3
    assert ds.skipped_tiles == []


def test_getitem_returns_a_graph_data_object(tmp_path: Path):
    (tmp_path / "tile_0_0.xodr").write_text(VALID_XODR, encoding="utf-8")
    ds = MapTileDataset(str(tmp_path))

    data = ds[0]

    assert hasattr(data, "x")
    assert hasattr(data, "edge_index")


def test_invalid_tile_skipped_by_default(tmp_path: Path):
    (tmp_path / "tile_valid.xodr").write_text(VALID_XODR, encoding="utf-8")
    (tmp_path / "tile_broken.xodr").write_text("not valid xml <<<", encoding="utf-8")

    ds = MapTileDataset(str(tmp_path))

    assert ds.files == ["tile_valid.xodr"]
    assert ds.skipped_tiles == ["tile_broken.xodr"]
    assert ds.num_tiles == 1


def test_strict_mode_raises_on_invalid_tile(tmp_path: Path):
    (tmp_path / "tile_valid.xodr").write_text(VALID_XODR, encoding="utf-8")
    (tmp_path / "tile_broken.xodr").write_text("not valid xml <<<", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Failed to build graph"):
        MapTileDataset(str(tmp_path), strict=True)


def test_non_xodr_files_ignored(tmp_path: Path):
    (tmp_path / "tile_0_0.xodr").write_text(VALID_XODR, encoding="utf-8")
    (tmp_path / "readme.txt").write_text("not a tile", encoding="utf-8")

    ds = MapTileDataset(str(tmp_path))

    assert ds.files == ["tile_0_0.xodr"]


def test_empty_valid_set_raises(tmp_path: Path):
    (tmp_path / "tile_broken.xodr").write_text("not valid xml <<<", encoding="utf-8")

    with pytest.raises(RuntimeError, match="No valid XODR graphs found"):
        MapTileDataset(str(tmp_path))


def test_summary_reflects_valid_and_skipped_counts(tmp_path: Path):
    (tmp_path / "tile_valid.xodr").write_text(VALID_XODR, encoding="utf-8")
    (tmp_path / "tile_broken.xodr").write_text("not valid xml <<<", encoding="utf-8")

    ds = MapTileDataset(str(tmp_path))
    summary = ds.summary()

    assert summary["num_valid_tiles"] == 1
    assert summary["num_skipped_tiles"] == 1
    assert summary["strict_mode"] is False
    assert summary["tiles_dir"] == str(tmp_path)
