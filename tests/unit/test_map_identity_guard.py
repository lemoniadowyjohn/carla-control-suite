from __future__ import annotations

import json

import pytest

from ultimate_pipeline.carla_tools.map_identity_guard import (
    is_town_fallback,
    save_map_identity,
    validate_world_map,
)
from ultimate_pipeline.carla_tools.session import CarlaSession


class _Map:
    def __init__(self, name: str) -> None:
        self.name = name


class _World:
    def __init__(self, name: str) -> None:
        self._map = _Map(name)

    def get_map(self) -> _Map:
        return self._map


def test_town_fallback_detection_handles_packaged_paths() -> None:
    assert is_town_fallback("/Game/Carla/Maps/Town05")
    assert is_town_fallback("Town10HD")
    assert not is_town_fallback("/Game/Carla/Maps/Grid0828")


def test_validate_world_map_passes_custom_map() -> None:
    result = validate_world_map(
        _World("/Game/Carla/Maps/Grid0828"),
        expected_substring="Grid0828",
        strict=True,
    )
    assert result["validation_passed"] is True
    assert result["world_map_name"].endswith("Grid0828")


def test_validate_world_map_raises_on_strict_town_fallback() -> None:
    with pytest.raises(RuntimeError, match="default Town map"):
        validate_world_map(_World("Town03"), expected_substring="Grid0828", strict=True)


def test_session_exposes_map_identity_guard() -> None:
    session = CarlaSession(host="localhost", port=2000, timeout=1.0)
    session._world = _World("Grid0828")
    result = session.validate_map_identity(expected_map_name="Grid0828", strict=True)
    assert result["validation_passed"] is True


def test_save_map_identity_writes_sorted_json(tmp_path) -> None:
    path = save_map_identity({"world_map_name": "Grid0828", "validation_passed": True}, tmp_path / "identity.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["world_map_name"] == "Grid0828"
