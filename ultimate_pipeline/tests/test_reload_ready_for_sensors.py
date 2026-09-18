from __future__ import annotations

from ultimate_pipeline.carla_tools.reload_ready_for_sensors import _reload_ready_for_sensors


class _Settings:
    def __init__(self) -> None:
        self.synchronous_mode = None
        self.fixed_delta_seconds = None


class _TrafficManager:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def set_synchronous_mode(self, enabled: bool) -> None:
        self._events.append(f"tm_sync_{str(bool(enabled)).lower()}")


class _OldWorld:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._settings = _Settings()

    def get_settings(self) -> _Settings:
        self._events.append("old_get_settings")
        return self._settings

    def apply_settings(self, settings: _Settings) -> None:
        self._events.append(
            f"old_apply_settings_sync_{str(bool(settings.synchronous_mode)).lower()}"
        )


class _NewWorld:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._settings = _Settings()

    def wait_for_tick(self, *, seconds: float) -> None:
        self._events.append("new_wait_for_tick")

    def get_settings(self) -> _Settings:
        self._events.append("new_get_settings")
        return self._settings

    def apply_settings(self, settings: _Settings) -> None:
        self._events.append(
            f"new_apply_settings_sync_{str(bool(settings.synchronous_mode)).lower()}"
        )

    def tick(self, *, seconds: float) -> int:
        self._events.append("new_tick")
        return 1


class _Client:
    def __init__(self, events: list[str], old_world: _OldWorld, new_world: _NewWorld) -> None:
        self._events = events
        self._old_world = old_world
        self._new_world = new_world
        self._tm = _TrafficManager(events)

    def set_timeout(self, timeout: float) -> None:
        self._events.append("set_timeout")

    def get_world(self) -> _OldWorld:
        self._events.append("get_world")
        return self._old_world

    def get_trafficmanager(self, tm_port: int) -> _TrafficManager:
        self._events.append(f"get_tm_{int(tm_port)}")
        return self._tm

    def load_world(self, map_name: str, reset_settings: bool = True) -> _NewWorld:
        self._events.append(f"load_world_{map_name}_{str(bool(reset_settings)).lower()}")
        return self._new_world


def _find_all(events: list[str], token: str) -> list[int]:
    return [i for i, value in enumerate(events) if value == token]


def test_reload_ready_for_sensors_sequence() -> None:
    events: list[str] = []
    old_world = _OldWorld(events)
    new_world = _NewWorld(events)
    client = _Client(events, old_world, new_world)

    async_warmup_frames = 3
    sync_warmup_frames = 4
    _reload_ready_for_sensors(
        client,
        map_name="Grid0828",
        tm_port=8000,
        fixed_dt=0.1,
        async_warmup_frames=async_warmup_frames,
        sync_warmup_frames=sync_warmup_frames,
        timeout=7.5,
    )

    old_apply_idx = events.index("old_apply_settings_sync_false")
    load_world_idx = events.index("load_world_Grid0828_true")
    assert old_apply_idx < load_world_idx

    wait_indices = _find_all(events, "new_wait_for_tick")
    assert len(wait_indices) == async_warmup_frames

    new_apply_idx = events.index("new_apply_settings_sync_true")
    assert new_apply_idx > wait_indices[-1]

    tick_indices = _find_all(events, "new_tick")
    assert len(tick_indices) == sync_warmup_frames
    assert all(idx > new_apply_idx for idx in tick_indices)
