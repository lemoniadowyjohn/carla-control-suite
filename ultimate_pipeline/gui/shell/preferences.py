"""Persistent non-secret UI preferences.

Only non-secret, non-identifying values are persisted: window geometry, the
last route, column widths, theme. Secrets are never written -- there is no
code path that can put one here, and the whitelist is enforced at write time.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

__all__ = ["PREFS_SCHEMA", "UIPreferences", "SecretRejected", "SAFE_KEYS"]

PREFS_SCHEMA = "carla-gui-ui-prefs/v1"

#: The only keys that may ever be persisted.
SAFE_KEYS: frozenset[str] = frozenset({
    "schema", "last_route", "column_widths", "theme", "font_point_size",
    "high_dpi_enabled", "nav_expanded", "search_debounce_ms", "geometry",
})

_SECRET_RE = re.compile(r"(pass|secret|token|api[_-]?key|credential|auth)", re.IGNORECASE)

#: Tokens can also arrive as a VALUE (a geometry blob, a theme string).
_SECRET_VALUE_RE = re.compile(
    r"(?i)\b(bearer\s+[A-Za-z0-9._\-]{8,}|sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}"
    r"|AKIA[0-9A-Z]{8,}|eyJ[A-Za-z0-9_\-]{10,}\.)")


class SecretRejected(ValueError):
    """A secret-looking key was offered for persistence."""


@dataclass
class UIPreferences:
    """Non-secret UI state. Everything defaults to a safe offline value."""

    last_route: str = "01_home"
    column_widths: dict[str, int] = field(default_factory=dict)
    theme: str = "light"
    font_point_size: int = 10
    high_dpi_enabled: bool = True
    nav_expanded: bool = True
    search_debounce_ms: int = 250
    geometry: str = ""

    def to_dict(self) -> dict:
        return {"schema": PREFS_SCHEMA,
                **{f.name: getattr(self, f.name) for f in fields(self)}}

    def as_saveable(self) -> dict:
        """Project to the persisted whitelist, dropping anything unknown."""
        payload = self.to_dict()
        return {k: v for k, v in payload.items() if k in SAFE_KEYS}


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False, newline="\n")
    try:
        with handle as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def _secret_bearing(value: Any, path: str = "") -> list[str]:
    """Find secret-looking keys or values ANYWHERE in the structure.

    A top-level key scan is not enough: ``column_widths`` is a free-form dict and
    a token can also arrive as a *value* (a geometry blob, a theme string).
    """
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_RE.search(key):
                found.append(f"{path}{key}")
            found.extend(_secret_bearing(item, f"{path}{key}."))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_secret_bearing(item, f"{path}[{index}]."))
    elif isinstance(value, str):
        if _SECRET_VALUE_RE.search(value):
            found.append(f"{path}<value>")
    return found


def save(prefs: UIPreferences, path: Path) -> Path:
    """Persist preferences atomically, refusing any secret-looking key OR value.

    The scan runs BEFORE the whitelist projection, and it walks the whole
    structure. Silently dropping an unknown secret-looking key would look
    identical to accepting it safely, and would hide a caller trying to persist
    one; a nested dict key or an embedded token value reaches disk otherwise.
    """
    everything = prefs.to_dict()
    everything.update(getattr(prefs, "__dict__", {}) or {})
    offenders = _secret_bearing(everything)
    if offenders:
        raise SecretRejected(
            f"refusing to persist secret-looking content at: {sorted(set(offenders))}")
    payload = prefs.as_saveable()
    _atomic_write(Path(path), json.dumps(payload, indent=2, sort_keys=True))
    return Path(path)


def load(path: Path, default: UIPreferences | None = None,
         valid_routes: tuple[str, ...] | None = None) -> UIPreferences:
    """Load preferences, tolerating a missing or corrupt file.

    ``valid_routes`` is passed so a stale or hand-edited ``last_route`` cannot
    make the application unlaunchable: an unknown route falls back to the
    default rather than propagating out of the window constructor.
    """
    base = default or UIPreferences()
    target = Path(path)
    if not target.is_file():
        return base
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return base
    if not isinstance(payload, dict):
        return base
    accepted = UIPreferences()
    for f in fields(UIPreferences):
        if f.name not in SAFE_KEYS or f.name not in payload:
            continue
        value = payload[f.name]
        if f.name in ("column_widths",):
            if isinstance(value, dict):
                accepted.column_widths = {str(k): int(v) for k, v in value.items()
                                          if isinstance(v, (int, float))}
            continue
        if f.name == "font_point_size" and not isinstance(value, int):
            continue
        if f.name == "search_debounce_ms" and not isinstance(value, int):
            continue
        if f.name == "high_dpi_enabled" and not isinstance(value, bool):
            continue
        if f.name == "nav_expanded" and not isinstance(value, bool):
            continue
        if f.name == "theme" and not isinstance(value, str):
            continue
        if f.name == "last_route" and not isinstance(value, str):
            continue
        if f.name == "geometry" and not isinstance(value, str):
            continue
        if f.name == "last_route" and valid_routes is not None \
                and value not in valid_routes:
            # An unknown route must never reach the navigator.
            continue
        setattr(accepted, f.name, value)
    return accepted