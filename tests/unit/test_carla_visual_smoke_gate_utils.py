"""ultimate_pipeline/tools/carla_visual_smoke_gate.py -- supplemental coverage for the pure,
CARLA-free utility functions not covered by test_carla_visual_smoke_gate_evaluation.py (which
covers evaluate_visual_smoke_report/run_visual_smoke_gate's offline paths). This file covers
_env_bool, _write_json, _mean_xy, and _transform_payload -- small helpers used to compute
camera framing for the visual smoke-test gate. _mean_xy/_transform_payload use simple duck-typed
stand-ins for carla.Location/Rotation/Transform (plain objects with x/y/z or pitch/yaw/roll
attributes) rather than the real CARLA API, matching this sweep's established pattern of testing
pure logic without a live CARLA connection. Found via the orphaned-.pyc sweep (test_carla_visual_
smoke_gate.py, the original exact-name test file, no longer exists on this branch).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from ultimate_pipeline.tools.carla_visual_smoke_gate import (
    _env_bool,
    _mean_xy,
    _transform_payload,
    _write_json,
)


# ---------------------------------------------------------------------------
# _env_bool
# ---------------------------------------------------------------------------

def test_env_bool_unset_returns_default(monkeypatch):
    monkeypatch.delenv("UP_SOME_FLAG", raising=False)
    assert _env_bool("UP_SOME_FLAG", default=True) is True
    assert _env_bool("UP_SOME_FLAG", default=False) is False


def test_env_bool_truthy_string_variants(monkeypatch):
    for val in ("1", "true", "TRUE", "yes", "on", "y"):
        monkeypatch.setenv("UP_SOME_FLAG", val)
        assert _env_bool("UP_SOME_FLAG") is True


def test_env_bool_falsy_string_variants(monkeypatch):
    for val in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("UP_SOME_FLAG", val)
        assert _env_bool("UP_SOME_FLAG") is False


def test_env_bool_strips_whitespace(monkeypatch):
    monkeypatch.setenv("UP_SOME_FLAG", "  true  ")
    assert _env_bool("UP_SOME_FLAG") is True


# ---------------------------------------------------------------------------
# _write_json
# ---------------------------------------------------------------------------

def test_write_json_creates_parent_dirs(tmp_path: Path):
    out = tmp_path / "nested" / "dir" / "out.json"
    _write_json(out, {"ok": True})
    assert out.is_file()
    assert json.loads(out.read_text(encoding="utf-8"))["ok"] is True


def test_write_json_output_sorted_and_newline_terminated(tmp_path: Path):
    out = tmp_path / "out.json"
    _write_json(out, {"z": 1, "a": 2})
    text = out.read_text(encoding="utf-8")
    assert text.index('"a"') < text.index('"z"')
    assert text.endswith("\n")


# ---------------------------------------------------------------------------
# _mean_xy
# ---------------------------------------------------------------------------

def _loc(x, y):
    return SimpleNamespace(location=SimpleNamespace(x=x, y=y))


def test_mean_xy_empty_input_returns_default_extent():
    assert _mean_xy([]) == (0.0, 0.0, 200.0)


def test_mean_xy_computes_centroid():
    points = [_loc(0.0, 0.0), _loc(10.0, 20.0)]
    cx, cy, extent = _mean_xy(points)
    assert cx == 5.0
    assert cy == 10.0


def test_mean_xy_extent_is_at_least_200():
    # spread is only 10 units in x/y -- extent must clamp up to the 200.0 floor.
    points = [_loc(0.0, 0.0), _loc(10.0, 5.0)]
    _, _, extent = _mean_xy(points)
    assert extent == 200.0


def test_mean_xy_extent_reflects_large_spread():
    points = [_loc(-500.0, 0.0), _loc(500.0, 0.0)]
    _, _, extent = _mean_xy(points)
    assert extent == 1000.0


def test_mean_xy_reads_location_via_transform_attribute_fallback():
    # some inputs (e.g. waypoints) expose .transform.location instead of .location directly
    point = SimpleNamespace(transform=SimpleNamespace(location=SimpleNamespace(x=4.0, y=8.0)))
    cx, cy, _ = _mean_xy([point])
    assert (cx, cy) == (4.0, 8.0)


def test_mean_xy_skips_items_with_no_location():
    points = [SimpleNamespace(), _loc(10.0, 10.0)]
    cx, cy, _ = _mean_xy(points)
    assert (cx, cy) == (10.0, 10.0)


# ---------------------------------------------------------------------------
# _transform_payload
# ---------------------------------------------------------------------------

def test_transform_payload_extracts_and_rounds_all_six_fields():
    transform = SimpleNamespace(
        location=SimpleNamespace(x=1.23456, y=2.0, z=3.0),
        rotation=SimpleNamespace(pitch=-8.11111, yaw=90.0, roll=0.0),
    )
    payload = _transform_payload(transform)
    assert payload == {
        "x": 1.235, "y": 2.0, "z": 3.0,
        "pitch": -8.111, "yaw": 90.0, "roll": 0.0,
    }
