from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CarlaSession:
    host: str
    port: int
    timeout: float
    map_name: str = ""
    _client: Any = None
    _world: Any = None

    @classmethod
    def connect(cls, host: str = "localhost", port: int = 2000, timeout: float = 10.0) -> CarlaSession:
        import carla
        session = cls(host=host, port=port, timeout=timeout)
        session._client = carla.Client(host, port)
        session._client.set_timeout(timeout)
        session._world = session._client.get_world()
        return session

    def load_map(self, map_name: str) -> None:
        if self._client is None:
            raise RuntimeError("Not connected. Call connect() first.")
        self._world = self._client.load_world(map_name)
        self.map_name = map_name

    def reload_map(self) -> None:
        if self._client is None:
            raise RuntimeError("Not connected.")
        self._world = self._client.reload_world()
        self.map_name = ""

    def set_sync_mode(self, seconds: float = 1.0 / 60.0) -> None:
        if self._world is None:
            raise RuntimeError("No world loaded.")
        settings = self._world.get_settings()
        settings.fixed_delta_seconds = seconds
        settings.synchronous_mode = True
        self._world.apply_settings(settings)

    def tick(self, seconds: float | None = None) -> int:
        if self._world is None:
            raise RuntimeError("No world loaded.")
        if seconds is not None:
            self.set_sync_mode(seconds)
        frame = self._world.tick()
        return frame

    def set_async_mode(self) -> None:
        if self._world is None:
            return
        settings = self._world.get_settings()
        settings.synchronous_mode = False
        self._world.apply_settings(settings)

    def validate_map_identity(
        self,
        expected_map_name: str | None = None,
        expected_substring: str | None = None,
        strict: bool = False,
    ) -> dict[str, Any]:
        if self._world is None:
            raise RuntimeError("No world loaded.")
        from .map_identity_guard import validate_world_map
        return validate_world_map(
            self._world,
            expected_map_name=expected_map_name,
            expected_substring=expected_substring,
            strict=strict,
        )

    @property
    def client(self) -> Any:
        return self._client

    @property
    def world(self) -> Any:
        return self._world

    def close(self) -> None:
        if self._world is not None:
            self.set_async_mode()
        self._world = None
        self._client = None

    def __enter__(self) -> CarlaSession:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
