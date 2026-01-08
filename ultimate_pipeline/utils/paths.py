from __future__ import annotations

import os
from pathlib import Path
from typing import Union


PathLike = Union[str, os.PathLike]


def repo_root() -> Path:
    """Return repository root inferred from this file location."""
    return Path(__file__).resolve().parents[2]


def _cities_root() -> Path:
    """Base directory for cities, optionally overridden via UP_CITIES_DIR."""
    env_root = os.getenv("UP_CITIES_DIR", "").strip()
    if env_root:
        base = Path(env_root)
        if not base.is_absolute():
            base = repo_root() / base
        return base
    return repo_root() / "cities"


def default_city_dir(city: str = "ingolstadt") -> Path:
    """Default city directory under the repo (or UP_CITIES_DIR override)."""
    return _cities_root() / city


def resolve_city_path(value: PathLike | None, city: str = "ingolstadt") -> Path:
    """
    Resolve a city-related path with sensible defaults:
    - absolute values are returned as-is
    - relative values are treated as repo-relative
    - None falls back to <cities_root>/<city>
    """
    city = os.getenv("UP_CITY", city).strip() or city
    if value:
        p = Path(value)
        if p.is_absolute():
            return p
        return repo_root() / p
    return default_city_dir(city)
