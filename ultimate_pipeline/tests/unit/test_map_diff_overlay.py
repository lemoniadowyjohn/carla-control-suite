# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/visualization/map_diff.py::overlay_maps.

Live: imported and called directly by run_full_domain_gap.py. Zero prior
test coverage for the actual plotting entry point (only _sample_geometry,
a pure geometry helper, was previously tested elsewhere).
"""
from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET

from ultimate_pipeline.visualization.map_diff import overlay_maps


def _write_xodr(path, *, x=0.0, y=0.0, hdg=0.0, length=50.0):
    root = ET.Element("OpenDRIVE")
    road = ET.SubElement(root, "road", id="1", length=str(length))
    plan = ET.SubElement(road, "planView")
    g = ET.SubElement(
        plan, "geometry",
        s="0", x=str(x), y=str(y), hdg=str(hdg), length=str(length),
    )
    ET.SubElement(g, "line")
    ET.ElementTree(root).write(str(path), encoding="utf-8", xml_declaration=True)
    return path


def test_overlay_maps_produces_a_valid_png(tmp_path):
    xodr_a = _write_xodr(tmp_path / "a.xodr", x=0.0)
    xodr_b = _write_xodr(tmp_path / "b.xodr", x=5.0)
    out_png = tmp_path / "overlay.png"
    result_path = overlay_maps(str(xodr_a), str(xodr_b), out_png=str(out_png))
    assert result_path == str(out_png)
    assert out_png.is_file()
    with out_png.open("rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"


def test_overlay_maps_uses_a_headless_backend_in_a_fresh_process():
    # Same defect class as heatmap_plotter.py: this system's matplotlib
    # default backend (tkagg) requires a display and crashes with a
    # TclError on an incomplete Tk install. run_full_domain_gap.py imports
    # overlay_maps directly and never imports map_plotter.py (the sibling
    # module that forces Agg), so there was no other safety net.
    result = subprocess.run(
        [
            sys.executable, "-c",
            "import matplotlib\n"
            "from ultimate_pipeline.visualization.map_diff import overlay_maps\n"
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
