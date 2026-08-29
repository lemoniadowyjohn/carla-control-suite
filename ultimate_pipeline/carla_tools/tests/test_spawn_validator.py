# -*- coding: utf-8 -*-
"""Tests for SpawnValidator (ultimate_pipeline/carla_tools/spawn_validator.py).

Live: imported directly by main_pipeline.py -- gates whether a CARLA world
is stable/drivable enough to proceed. Zero prior test coverage. Uses
duck-typed fakes (not the real carla module) since SpawnValidator only
calls client.get_world().get_map().get_spawn_points().
"""
from __future__ import annotations

import pytest

from ultimate_pipeline.carla_tools.spawn_validator import SpawnValidator


class _FakeMap:
    def __init__(self, spawn_points):
        self._spawn_points = spawn_points

    def get_spawn_points(self):
        return self._spawn_points


class _FakeWorld:
    def __init__(self, spawn_points=None, map_error=None):
        self._map = _FakeMap(spawn_points or [])
        self._map_error = map_error
        self.get_map_calls = 0

    def get_map(self):
        self.get_map_calls += 1
        if self._map_error is not None:
            raise self._map_error
        return self._map


class _FakeClient:
    def __init__(self, world=None, world_error=None):
        self._world = world
        self._world_error = world_error

    def get_world(self):
        if self._world_error is not None:
            raise self._world_error
        return self._world


def test_check_raises_typeerror_for_non_client_object():
    with pytest.raises(TypeError):
        SpawnValidator.check(object())


def test_check_returns_true_when_spawn_points_present():
    world = _FakeWorld(spawn_points=[1, 2, 3])
    client = _FakeClient(world=world)
    assert SpawnValidator.check(client) is True


def test_check_returns_false_when_get_world_raises():
    client = _FakeClient(world_error=RuntimeError("carla not connected"))
    assert SpawnValidator.check(client) is False


def test_wait_for_spawn_points_returns_empty_after_timeout():
    world = _FakeWorld(spawn_points=[])
    spawns = SpawnValidator._wait_for_spawn_points(world, timeout=0.05, poll=0.01)
    assert spawns == []
    assert world.get_map_calls >= 1


def test_wait_for_spawn_points_recovers_from_transient_map_exception():
    # A world that isn't fully ready yet raises from get_map(); the poll
    # loop should tolerate this and keep retrying rather than propagating.
    calls = {"n": 0}

    class _FlakyWorld:
        def get_map(self):
            calls["n"] += 1
            if calls["n"] < 2:
                raise RuntimeError("map not ready")
            return _FakeMap([42])

    spawns = SpawnValidator._wait_for_spawn_points(_FlakyWorld(), timeout=2.0, poll=0.01)
    assert spawns == [42]
    assert calls["n"] >= 2
