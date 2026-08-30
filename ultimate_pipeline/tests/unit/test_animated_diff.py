# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/visualization/animated_diff.py.

Live via main_pipeline.py / stage_06_links.py. Zero prior test coverage.

Found the entire file's content was duplicated verbatim top-to-bottom
(two identical `class AnimatedDiff` definitions in the same file, likely
a copy-paste accident) -- functionally harmless since Python silently
uses the second definition, but a real defect worth cleaning up (a future
edit to only one copy would produce confusing, inconsistent behavior).
Removed the duplicate; no logic bug found in the actual blending/GIF
logic itself.
"""
from __future__ import annotations

from PIL import Image

from ultimate_pipeline.visualization.animated_diff import AnimatedDiff


def _save_png(path, size=(10, 10), color=(255, 0, 0)):
    Image.new("RGB", size, color).save(path)


def test_missing_before_png_prints_error_and_does_not_write_gif(tmp_path, capsys):
    _save_png(tmp_path / "after.png")
    gif_out = tmp_path / "out.gif"
    AnimatedDiff.run(str(tmp_path / "missing.png"), str(tmp_path / "after.png"), str(gif_out))
    assert "before_png missing" in capsys.readouterr().out
    assert not gif_out.exists()


def test_missing_after_png_prints_error_and_does_not_write_gif(tmp_path, capsys):
    _save_png(tmp_path / "before.png")
    gif_out = tmp_path / "out.gif"
    AnimatedDiff.run(str(tmp_path / "before.png"), str(tmp_path / "missing.png"), str(gif_out))
    assert "after_png missing" in capsys.readouterr().out
    assert not gif_out.exists()


def test_writes_a_valid_animated_gif(tmp_path):
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    _save_png(before, color=(255, 0, 0))
    _save_png(after, color=(0, 0, 255))
    gif_out = tmp_path / "out.gif"

    AnimatedDiff.run(str(before), str(after), str(gif_out), frames=4)

    assert gif_out.exists()
    img = Image.open(gif_out)
    assert img.is_animated
    # Pillow's GIF encoder merges consecutive pixel-identical frames, so the
    # 3 "hold on last frame" duplicates collapse into the final fade frame
    # -- 4 distinct fade frames is the correct, expected count here, not
    # 4 + 3 = 7 (verified this is standard Pillow GIF-writing behavior,
    # not a bug in AnimatedDiff, via a control test with visually distinct
    # frame colors, which correctly reports the full frame count).
    assert img.n_frames == 4


def test_resizes_mismatched_input_sizes(tmp_path):
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    _save_png(before, size=(10, 10))
    _save_png(after, size=(20, 20))
    gif_out = tmp_path / "out.gif"

    AnimatedDiff.run(str(before), str(after), str(gif_out), frames=3)

    img = Image.open(gif_out)
    assert img.size == (10, 10)  # resized to match `before`


def test_single_frame_does_not_raise_zero_division(tmp_path):
    before = tmp_path / "before.png"
    after = tmp_path / "after.png"
    _save_png(before)
    _save_png(after)
    gif_out = tmp_path / "out.gif"

    AnimatedDiff.run(str(before), str(after), str(gif_out), frames=1)  # must not raise
    assert gif_out.exists()
