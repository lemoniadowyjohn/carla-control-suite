from __future__ import annotations

import types

import pytest


def _make_streamer(monkeypatch, *, enabled: bool = True):
    """
    Construct a MeshStreamer without requiring a live CARLA install.

    MeshStreamer.__init__ only requires `_CARLA_AVAILABLE` to be truthy and a
    `world` object exposing load_map_layer/unload_map_layer -- it does not
    touch any other CARLA API -- so a lightweight fake world is sufficient.
    """
    from ultimate_pipeline.carla_tools import mesh_streamer as ms

    monkeypatch.setattr(ms, "_CARLA_AVAILABLE", True)
    monkeypatch.setattr(ms.SETTINGS, "ENABLE_MESH_STREAMING", enabled, raising=False)

    calls = {"loaded": [], "unloaded": []}

    class FakeWorld:
        def load_map_layer(self, name):
            calls["loaded"].append(name)

        def unload_map_layer(self, name):
            calls["unloaded"].append(name)

    streamer = ms.MeshStreamer(world=FakeWorld())
    return streamer, calls


def test_update_loads_layers_for_required_tiles(monkeypatch):
    streamer, calls = _make_streamer(monkeypatch)

    streamer.update({"tile_0_0.xodr", "tile_0_1.xodr"})

    assert set(calls["loaded"]) == {"Tile_0_0", "Tile_0_1"}
    assert streamer.loaded_layers == {"Tile_0_0", "Tile_0_1"}


def test_update_unloads_layers_no_longer_required(monkeypatch):
    streamer, calls = _make_streamer(monkeypatch)

    streamer.update({"tile_0_0.xodr"})
    calls["loaded"].clear()

    streamer.update({"tile_1_1.xodr"})

    assert calls["unloaded"] == ["Tile_0_0"]
    assert calls["loaded"] == ["Tile_1_1"]
    assert streamer.loaded_layers == {"Tile_1_1"}


def test_update_defaults_to_empty_set_when_no_tiles_given(monkeypatch):
    streamer, calls = _make_streamer(monkeypatch)

    # No positional/keyword arg -> treated as "no tiles required" (unloads any
    # previously-loaded layers, loads nothing new). This matches update_layers's
    # existing empty-set behavior and keeps update() callable with zero args.
    streamer.update()

    assert calls["loaded"] == []
    assert streamer.loaded_layers == set()


def test_update_noop_when_disabled(monkeypatch):
    streamer, calls = _make_streamer(monkeypatch, enabled=False)

    streamer.update({"tile_0_0.xodr"})

    assert calls["loaded"] == []
    assert calls["unloaded"] == []
    assert streamer.loaded_layers == set()


def test_update_delegates_to_update_layers(monkeypatch):
    streamer, _calls = _make_streamer(monkeypatch)

    seen = {}

    def fake_update_layers(required_tiles):
        seen["required_tiles"] = required_tiles

    monkeypatch.setattr(streamer, "update_layers", fake_update_layers)

    streamer.update({"tile_2_2.xodr"})

    assert seen["required_tiles"] == {"tile_2_2.xodr"}
