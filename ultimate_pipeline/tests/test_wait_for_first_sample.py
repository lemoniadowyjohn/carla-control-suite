from __future__ import annotations

from ultimate_pipeline.carla_tools.thesis_sensor_rig import wait_for_first_sample


class _Sample:
    def __init__(self, frame: int) -> None:
        self.frame = int(frame)


class _Sensor:
    def __init__(self, emit_plan: dict[int, int]) -> None:
        self._emit_plan = dict(emit_plan)
        self._callback = None
        self.stop_calls = 0

    def listen(self, callback) -> None:
        self._callback = callback

    def stop(self) -> None:
        self.stop_calls += 1
        self._callback = None

    def on_tick(self, tick_frame: int) -> None:
        if self._callback is None:
            return
        if tick_frame in self._emit_plan:
            self._callback(_Sample(self._emit_plan[tick_frame]))


class _World:
    def __init__(self, sensor: _Sensor) -> None:
        self._sensor = sensor
        self._frame = 0
        self.tick_calls = 0

    def tick(self, *, seconds: float) -> int:
        self.tick_calls += 1
        self._frame += 1
        self._sensor.on_tick(self._frame)
        return self._frame


def test_wait_for_first_sample_returns_true_when_sensor_delivers_on_tick_two() -> None:
    sensor = _Sensor(emit_plan={2: 2})
    world = _World(sensor)

    ok = wait_for_first_sample(world, sensor, timeout=0.01, max_ticks=4)

    assert ok is True
    assert sensor.stop_calls >= 1


def test_wait_for_first_sample_returns_false_when_sensor_never_delivers() -> None:
    sensor = _Sensor(emit_plan={})
    world = _World(sensor)

    ok = wait_for_first_sample(world, sensor, timeout=0.01, max_ticks=3)

    assert ok is False
    assert world.tick_calls == 3
    assert sensor.stop_calls >= 1


def test_wait_for_first_sample_accepts_lag_of_two_frames() -> None:
    sensor = _Sensor(emit_plan={4: 2})
    world = _World(sensor)

    ok = wait_for_first_sample(world, sensor, timeout=0.01, max_ticks=5)

    assert ok is True


def test_wait_for_first_sample_clears_temporary_listener_before_return() -> None:
    sensor = _Sensor(emit_plan={1: 1})
    world = _World(sensor)

    ok = wait_for_first_sample(world, sensor, timeout=0.01, max_ticks=2)

    assert ok is True
    assert sensor._callback is None
    assert sensor.stop_calls >= 1
