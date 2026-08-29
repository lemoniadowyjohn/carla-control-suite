# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/visualization/heatmap_plotter.py.

Live: TileHeatmapPlotter is called 3 times by run_full_domain_gap.py.
Zero prior test coverage.
"""
from __future__ import annotations

import subprocess
import sys

from ultimate_pipeline.visualization.heatmap_plotter import TileHeatmapPlotter


# ---------------------------------------------------------------------------
# _parse_tile_name
# ---------------------------------------------------------------------------

def test_parse_tile_name_standard_form():
    assert TileHeatmapPlotter._parse_tile_name("tile_3_2.xodr") == (3, 2)


def test_parse_tile_name_strips_directory_prefix():
    assert TileHeatmapPlotter._parse_tile_name("C:/runs/tiles/tile_3_2.xodr") == (3, 2)


def test_parse_tile_name_without_extension():
    assert TileHeatmapPlotter._parse_tile_name("tile_5_1") == (5, 1)


def test_parse_tile_name_malformed_falls_back_to_origin():
    assert TileHeatmapPlotter._parse_tile_name("not_a_tile_name") == (0, 0)
    assert TileHeatmapPlotter._parse_tile_name("weird") == (0, 0)


# ---------------------------------------------------------------------------
# plot()
# ---------------------------------------------------------------------------

def test_plot_produces_a_valid_png(tmp_path):
    out_png = tmp_path / "heatmap.png"
    TileHeatmapPlotter.plot(
        {"tile_0_0.xodr": 0.1, "tile_0_1.xodr": 0.5, "tile_1_0.xodr": 0.9},
        str(out_png),
    )
    assert out_png.is_file()
    assert out_png.stat().st_size > 0
    with out_png.open("rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"  # real PNG signature, not a stub


def test_plot_creates_missing_output_directory(tmp_path):
    out_png = tmp_path / "nested" / "dir" / "heatmap.png"
    TileHeatmapPlotter.plot({"tile_0_0.xodr": 1.0}, str(out_png))
    assert out_png.is_file()


def test_plot_uses_a_headless_backend_in_a_fresh_process():
    # This system's matplotlib default backend is an interactive GUI backend
    # (tkagg), which requires a display and would fail/hang in a headless
    # environment (e.g. a CI server or a remote batch run of
    # run_full_domain_gap.py, which imports TileHeatmapPlotter but never
    # imports map_plotter.py -- the sibling module that correctly forces
    # matplotlib.use('Agg') before importing pyplot). Verified via a genuinely
    # fresh subprocess since backend state can leak across imports within a
    # single test process.
    result = subprocess.run(
        [
            sys.executable, "-c",
            "import matplotlib\n"
            "from ultimate_pipeline.visualization.heatmap_plotter import TileHeatmapPlotter\n"
            "print(matplotlib.get_backend())\n",
        ],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    backend = result.stdout.strip().lower()
    assert backend in ("agg", "svg", "pdf", "ps", "cairo"), (
        f"expected a headless/non-interactive backend, got {backend!r} "
        f"(stderr: {result.stderr})"
    )
