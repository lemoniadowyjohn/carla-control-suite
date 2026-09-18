from __future__ import annotations

from types import ModuleType
from typing import Optional

_CARLA_MODULE: Optional[ModuleType] = None
_CARLA_CHECKED = False


def _probe_carla_module() -> Optional[ModuleType]:
    global _CARLA_MODULE, _CARLA_CHECKED
    if _CARLA_CHECKED:
        return _CARLA_MODULE

    try:
        import carla  # pragma: no cover

        _CARLA_MODULE = carla
    except ModuleNotFoundError:
        _CARLA_MODULE = None
    finally:
        _CARLA_CHECKED = True

    return _CARLA_MODULE


def get_carla() -> ModuleType:
    """
    Lazy CARLA importer that raises a friendly RuntimeError when CARLA is missing.
    """
    module = _probe_carla_module()
    if module is None:
        raise RuntimeError(
            "The CARLA Python API is not installed; set UP_DISABLE_CARLA=1 or install the matching package for your CARLA build."
        )
    return module


def carla_available() -> bool:
    """
    Returns True if the CARLA Python API can be imported.
    """
    return _probe_carla_module() is not None
