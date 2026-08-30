# -*- coding: utf-8 -*-
"""Tests for ultimate_pipeline/tiling/tile_auto_forensics.py.

Live: TileAutoForensics is used by main_pipeline.py and
core/tile_failure_monitor.py. Zero prior test coverage. No bug found --
this is currently an intentional observation-only stub (its own comment:
"For now: NO automatic repair").
"""
from __future__ import annotations

from ultimate_pipeline.tiling.tile_auto_forensics import TileAutoForensics


def test_success_resets_the_failure_counter():
    forensics = TileAutoForensics("tiles", "out", trigger_n=3)
    forensics._consecutive_failures = 2
    result = forensics.note_tile_result("tile_0_0.xodr", ok=True)
    assert result is None
    assert forensics._consecutive_failures == 0


def test_failures_below_trigger_return_none_and_accumulate():
    forensics = TileAutoForensics("tiles", "out", trigger_n=3)
    assert forensics.note_tile_result("t1", ok=False) is None
    assert forensics._consecutive_failures == 1
    assert forensics.note_tile_result("t2", ok=False) is None
    assert forensics._consecutive_failures == 2


def test_reaching_trigger_n_fires_and_resets_counter(capsys):
    forensics = TileAutoForensics("tiles", "out", trigger_n=3)
    forensics.note_tile_result("t1", ok=False)
    forensics.note_tile_result("t2", ok=False)
    result = forensics.note_tile_result("t3", ok=False)
    assert result is None  # observation-only mode, no repair action yet
    assert forensics._consecutive_failures == 0
    out = capsys.readouterr().out
    assert "triggered" in out
    assert "observation-only" in out


def test_trigger_can_fire_again_after_reset():
    forensics = TileAutoForensics("tiles", "out", trigger_n=2)
    forensics.note_tile_result("t1", ok=False)
    forensics.note_tile_result("t2", ok=False)  # fires, resets to 0
    assert forensics._consecutive_failures == 0
    forensics.note_tile_result("t3", ok=False)
    assert forensics._consecutive_failures == 1
