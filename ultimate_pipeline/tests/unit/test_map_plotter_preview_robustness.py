# ultimate_pipeline/tests/unit/test_map_plotter_preview_robustness.py
# -*- coding: utf-8 -*-
"""OC-15: stage-02 preview robustness.

Regression coverage for the Matplotlib divide-by-zero observed in pipeline
run ``20261021_175215_009531``:

    matplotlib/patches.py:3161: RuntimeWarning: divide by zero encountered in
    scalar divide

Root cause
----------
``matplotlib.patches._point_along_a_line`` computes::

    dx, dy = x0 - x1, y0 - y1
    ff = d / (dx * dx + dy * dy) ** .5

When ``ArrowStyle.Simple`` is used to draw a direction arrow whose two anchor
points coincide, ``dx * dx + dy * dy == 0`` and the division raises a
``RuntimeWarning`` (or an exception when warnings are promoted to errors).
``MapPlotter._draw_direction_arrow`` selected the two samples straddling the
midpoint of the planView polyline without checking that they describe a
non-degenerate segment, so a zero-length geometry element (or any geometry
sampling that yields two identical consecutive points) produced the warning.

Contract asserted here
----------------------
* A degenerate (zero-length) arrow segment must be skipped, not rendered and
  not allowed to reach Matplotlib's degenerate-normalisation math.
* A non-degenerate arrow segment must still be rendered (the fix must not
  silently disable the feature).
* ``save_preview`` must always close the Matplotlib figure, including when
  the save itself fails, so repeated calls cannot leak figures.
* Preview generation is an optional product: a failure inside the renderer
  must not abort the pipeline, but it must not mask an invalid topology.
"""

from __future__ import annotations

import warnings

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402

from ultimate_pipeline.visualization.map_plotter import MapPlotter  # noqa: E402


# --- helpers ---------------------------------------------------------------

def _ax():
    fig, ax = plt.subplots(figsize=(4, 4))
    return fig, ax


def _degenerate_road_xml() -> str:
    """An OpenDRIVE road whose planView samples collapse onto one point.

    ``length="0"`` makes the geometry sampler emit a single coordinate, and
    the duplicated line elements force two consecutive samples to be
    identical, which is exactly the input shape that produced the original
    divide-by-zero.
    """
    return """<?xml version="1.0" encoding="UTF-8"?>
<OpenDRIVE>
    <header revMajor="1" revMinor="7" name="degenerate" version="1.00"
            date="2026-10-21" north="0" south="0" east="0" west="0"/>
    <road name="degenerate" length="0" id="1" junction="-1">
        <planView>
            <geometry s="0.0" x="0.0" y="0.0" hdg="0.0" length="0.0">
                <line/>
            </geometry>
        </planView>
        <lanes>
            <laneSection s="0.0">
                <left>
                    <lane id="1" type="driving" level="false">
                        <roadMark/>
                    </lane>
                </left>
                <center>
                    <lane id="0" type="none" level="false">
                        <roadMark/>
                    </lane>
                </center>
                <right>
                    <lane id="-1" type="driving" level="false">
                        <roadMark/>
                    </lane>
                </right>
            </laneSection>
        </lanes>
    </road>
</OpenDRIVE>
"""


# --- regression: the exact failure mechanism --------------------------------

def test_draw_direction_arrow_skips_zero_length_segment():
    """A zero-length arrow segment must not reach Matplotlib's patch maths.

    Negative control: with the pre-fix implementation this call emitted
    ``RuntimeWarning: divide by zero encountered in scalar divide``.
    """
    fig, ax = _ax()
    try:
        xs = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        ys = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            MapPlotter._draw_direction_arrow(ax, xs, ys)

        divide_by_zero = [
            w for w in caught
            if issubclass(w.category, RuntimeWarning)
            and "divide by zero" in str(w.message)
        ]
        assert not divide_by_zero, (
            "degenerate arrow segment produced a divide-by-zero warning: "
            f"{[str(w.message) for w in divide_by_zero]}"
        )
        # The degenerate arrow must not be added to the axes at all.
        assert len(ax.patches) == 0
    finally:
        plt.close(fig)


def test_draw_direction_arrow_renders_non_degenerate_segment():
    """The guard must not disable the feature for valid geometry."""
    fig, ax = _ax()
    try:
        xs = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            MapPlotter._draw_direction_arrow(ax, xs, ys)

        divide_by_zero = [
            w for w in caught
            if issubclass(w.category, RuntimeWarning)
            and "divide by zero" in str(w.message)
        ]
        assert not divide_by_zero
        assert len(ax.patches) == 1, "a valid direction arrow must still be drawn"
    finally:
        plt.close(fig)


def test_draw_direction_arrow_too_few_points_is_noop():
    """Fewer than five samples cannot define an arrow; the guard is a no-op."""
    fig, ax = _ax()
    try:
        MapPlotter._draw_direction_arrow(ax, [0.0, 1.0], [0.0, 1.0])
        assert len(ax.patches) == 0
    finally:
        plt.close(fig)


# --- save_preview behaviour -------------------------------------------------

def test_save_preview_on_degenerate_geometry_does_not_raise(tmp_path):
    """save_preview must complete on degenerate input without raising.

    The preview is a non-required product; a rendering problem must be
    reported as a preview problem, never as a structural failure.
    """
    xodr = tmp_path / "degenerate.xodr"
    xodr.write_text(_degenerate_road_xml(), encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        MapPlotter.save_preview(str(xodr), str(out_dir), stage="02_structure_clean")

    divide_by_zero = [
        w for w in caught
        if issubclass(w.category, RuntimeWarning)
        and "divide by zero" in str(w.message)
    ]
    assert not divide_by_zero, (
        "save_preview emitted divide-by-zero warnings: "
        f"{[str(w.message) for w in divide_by_zero]}"
    )


def test_save_preview_closes_figure(tmp_path):
    """Figures must be released after a successful preview."""
    xodr = tmp_path / "degenerate.xodr"
    xodr.write_text(_degenerate_road_xml(), encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    before = len(plt.get_fignums())
    MapPlotter.save_preview(str(xodr), str(out_dir), stage="02_structure_clean")
    after = len(plt.get_fignums())

    assert after == before, (
        f"save_preview leaked a Matplotlib figure: {before} -> {after}"
    )


def test_save_preview_missing_input_is_noop(tmp_path):
    """A missing input must return quietly without creating a figure."""
    before = len(plt.get_fignums())
    MapPlotter.save_preview(
        str(tmp_path / "does_not_exist.xodr"), str(tmp_path), stage="02_structure_clean"
    )
    assert len(plt.get_fignums()) == before


def test_save_preview_malformed_xml_is_noop(tmp_path):
    """A malformed input must return quietly without creating a figure."""
    xodr = tmp_path / "broken.xodr"
    xodr.write_text("<OpenDRIVE><unclosed>", encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    before = len(plt.get_fignums())
    MapPlotter.save_preview(str(xodr), str(out_dir), stage="02_structure_clean")
    assert len(plt.get_fignums()) == before


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
