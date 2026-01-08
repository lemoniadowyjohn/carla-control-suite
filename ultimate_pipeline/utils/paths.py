from __future__ import annotations

import os
from pathlib import Path
from typing import Union


PathLike = Union[str, os.PathLike, None]


def repo_root() -> Path:
    """Walk up from this file until a directory containing ultimate_pipeline/ exists."""
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "ultimate_pipeline").is_dir():
            return parent
    return here.parents[2]


def cities_root() -> Path:
    """Base directory for cities; overridable via UP_CITIES_DIR (repo-relative allowed)."""
    env_root = os.getenv("UP_CITIES_DIR", "").strip()
    if env_root:
        p = Path(env_root)
        if not p.is_absolute():
            p = repo_root() / p
        return p
    return repo_root() / "cities"


def city_dir(city: str | None = None) -> Path:
    """Directory for the given city (defaults to env UP_CITY or 'ingolstadt')."""
    name = (city or os.getenv("UP_CITY", "ingolstadt")).strip() or "ingolstadt"
    return cities_root() / name


def resolve_path(p: PathLike, *, default: Path) -> Path:
    """
    Resolve a path with repo-relative semantics.
    - None/empty -> default
    - absolute -> as-is
    - relative -> repo_root()/p
    """
    if not p:
        return default
    path = Path(p)
    if path.is_absolute():
        return path
    return repo_root() / path


# Backwards compat alias (avoid breakage for earlier refactors)
def resolve_city_path(value: PathLike | None, city: str = "ingolstadt") -> Path:
    return resolve_path(value, default=city_dir(city))
