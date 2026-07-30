from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


STRICT_ENV = "UP_THESIS_STRICT"


def _strict_from_env() -> bool:
    return os.getenv(STRICT_ENV, "") == "1"


def _map_name(world: Any) -> str:
    carla_map = world.get_map()
    name = getattr(carla_map, "name", None)
    if not isinstance(name, str) or not name.strip():
        return "unknown"
    return name.strip()


def is_town_fallback(map_name: str) -> bool:
    normalized = map_name.replace("\\", "/")
    leaf = normalized.rsplit("/", 1)[-1]
    return leaf.startswith("Town") or "/Town" in normalized


def validate_world_map(
    world: Any,
    *,
    expected_substring: str | None = None,
    expected_map_name: str | None = None,
    strict: bool | None = None,
) -> dict[str, Any]:
    if strict is None:
        strict = _strict_from_env()

    result: dict[str, Any] = {
        "expected_map_name": expected_map_name,
        "expected_substring": expected_substring,
        "is_town_fallback": False,
        "strict_enabled": strict,
        "validation_passed": False,
        "world_map_name": None,
        "error": None,
    }

    try:
        map_name = _map_name(world)
    except Exception as exc:
        result["error"] = f"failed to read CARLA map identity: {exc}"
        if strict:
            raise RuntimeError(result["error"]) from exc
        return result

    result["world_map_name"] = map_name
    result["is_town_fallback"] = is_town_fallback(map_name)

    failures: list[str] = []
    if result["is_town_fallback"]:
        failures.append(f"CARLA loaded default Town map {map_name!r}")
    if expected_map_name is not None and map_name != expected_map_name:
        failures.append(f"map name {map_name!r} does not match expected {expected_map_name!r}")
    if expected_substring is not None and expected_substring not in map_name:
        failures.append(f"map name {map_name!r} does not contain {expected_substring!r}")

    if failures:
        result["error"] = "; ".join(failures)
        if strict:
            raise RuntimeError(result["error"])
        return result

    result["validation_passed"] = True
    return result


def save_map_identity(result: dict[str, Any], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return output


__all__ = ["STRICT_ENV", "is_town_fallback", "save_map_identity", "validate_world_map"]
