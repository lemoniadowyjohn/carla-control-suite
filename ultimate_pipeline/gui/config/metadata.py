"""Access to the versioned settings metadata registry.

The registry is a committed, versioned data file (``settings_metadata.json``)
generated from the foundation's ``SETTINGS_MASTER.csv`` and verified against the
current source tree.  Nothing here invents a default, a range or a widget: a
value the catalog does not know stays ``UNKNOWN`` and is rendered as such.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

__all__ = [
    "REGISTRY_PATH", "SCHEMA", "SettingMeta", "SettingsRegistry",
    "load_registry", "UNSET", "ENV_PREFIX",
]

REGISTRY_PATH = Path(__file__).with_name("settings_metadata.json")
SCHEMA = "carla-gui-settings-registry/v1"

#: Sentinel for "no value recorded". Never coerced to ``None`` or to a default.
UNSET = object()

ENV_PREFIX = "UP_"


@dataclass(frozen=True)
class SettingMeta:
    """Metadata for one declaration site."""

    index: int
    setting_id: str
    kind: str
    lifecycle: str
    safety_class: str
    binds_to: str
    presence: str
    present_at_head: bool
    duplicated: bool
    range_is_known: bool
    declaration: str | None = None
    decl_line: int | None = None
    citation: str | None = None
    python_type: str | None = None
    default_expr: str | None = None
    apply_mode: str | None = None
    range_or_enum: str | None = None
    gui_widget: str | None = None
    validation: str | None = None
    persistence: str | None = None
    catalog_status: str | None = None
    catalog_evidence: str | None = None
    declaration_sites: int | None = None

    @property
    def is_editable(self) -> bool:
        """Only entries bound to a live location can be written by the GUI."""
        return self.binds_to in ("SETTINGS_FIELD", "MODULE_GLOBAL") and self.present_at_head

    @property
    def range_known(self) -> bool:
        return self.range_is_known

    @property
    def disabled_reason(self) -> str:
        """Why a control is disabled. Empty when it is not disabled."""
        if self.is_editable:
            return ""
        if not self.present_at_head:
            return f"declared at {self.citation} but absent at the current HEAD"
        return f"no live binding ({self.binds_to}); value cannot be written"

    @property
    def provenance_help(self) -> str:
        parts = [self.citation or self.declaration or "unknown source"]
        if self.default_expr:
            parts.append(f"default: {self.default_expr}")
        if self.apply_mode:
            parts.append(f"applies: {self.apply_mode}")
        if self.duplicated:
            parts.append(f"declared at {self.declaration_sites} sites")
        return " | ".join(parts)


@dataclass(frozen=True)
class SettingsRegistry:
    """All declaration sites, indexed by setting id."""

    schema: str
    base_sha: str
    entries: tuple[SettingMeta, ...]
    counts: dict[str, Any]
    env_coverage: dict[str, Any]

    def __iter__(self) -> Iterator[SettingMeta]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def by_id(self, setting_id: str) -> list[SettingMeta]:
        """Every declaration site for an id (len > 1 means dual-declared)."""
        return [e for e in self.entries if e.setting_id == setting_id]

    def one(self, setting_id: str) -> SettingMeta | None:
        found = self.by_id(setting_id)
        return found[0] if found else None

    @property
    def distinct_ids(self) -> list[str]:
        seen: dict[str, None] = {}
        for entry in self.entries:
            seen.setdefault(entry.setting_id, None)
        return list(seen)

    def editable(self) -> list[SettingMeta]:
        """One entry per editable setting (first declaration site wins)."""
        out: dict[str, SettingMeta] = {}
        for entry in self.entries:
            if entry.setting_id in out:
                continue
            if entry.is_editable:
                out[entry.setting_id] = entry
        return list(out.values())

    def categories(self) -> dict[str, list[SettingMeta]]:
        """Grouped for the searchable configurator."""
        grouped: dict[str, list[SettingMeta]] = {}
        for entry in self.editable():
            grouped.setdefault(entry.kind or "unclassified", []).append(entry)
        return {k: grouped[k] for k in sorted(grouped)}

    def search(self, needle: str) -> list[SettingMeta]:
        needle = (needle or "").strip().lower()
        if not needle:
            return []
        return [
            e for e in self.editable()
            if needle in e.setting_id.lower()
            or needle in (e.default_expr or "").lower()
            or needle in (e.citation or "").lower()
        ]


def _coerce(raw: dict) -> SettingMeta:
    return SettingMeta(
        index=raw["index"], setting_id=raw["setting_id"], kind=raw["kind"],
        lifecycle=raw["lifecycle"], safety_class=raw["safety_class"],
        binds_to=raw["binds_to"], presence=raw["presence"],
        present_at_head=raw["present_at_head"], duplicated=raw["duplicated"],
        range_is_known=raw["range_is_known"], declaration=raw.get("declaration"),
        decl_line=raw.get("decl_line"), citation=raw.get("citation"),
        python_type=raw.get("python_type"), default_expr=raw.get("default_expr"),
        apply_mode=raw.get("apply_mode"), range_or_enum=raw.get("range_or_enum"),
        gui_widget=raw.get("gui_widget"), validation=raw.get("validation"),
        persistence=raw.get("persistence"), catalog_status=raw.get("catalog_status"),
        catalog_evidence=raw.get("catalog_evidence"),
        declaration_sites=raw.get("declaration_sites"),
    )


@lru_cache(maxsize=1)
def load_registry(path: Path | None = None) -> SettingsRegistry:
    target = Path(path) if path else REGISTRY_PATH
    payload = json.loads(target.read_text(encoding="utf-8"))
    if payload.get("schema") != SCHEMA:
        raise ValueError(
            f"unsupported settings registry schema {payload.get('schema')!r}; expected {SCHEMA!r}"
        )
    return SettingsRegistry(
        schema=payload["schema"],
        base_sha=payload["base_sha"],
        entries=tuple(_coerce(raw) for raw in payload["entries"]),
        counts=payload["counts"],
        env_coverage=payload["env_coverage"],
    )


def env_name_for(setting_id: str) -> str:
    """The ``UP_*`` environment variable that overrides a setting, if any."""
    return f"{ENV_PREFIX}{setting_id}"


def effective_value(setting_id: str, env: dict[str, str] | None = None) -> Any:
    """Effective value: environment first, then the live module.

    Returns :data:`UNSET` rather than guessing when nothing is bound.  The
    caller must decide how to render ``UNSET``; it is never silently defaulted.
    """
    import os

    environ = os.environ if env is None else env
    name = env_name_for(setting_id)
    if name in environ:
        return ("ENV", name, environ[name])
    return ("UNBOUND", None, None)


def live_value(setting_id: str, binds_to: str) -> Any:
    """Read the current effective value out of the live settings module."""
    import warnings

    from ultimate_pipeline.config import settings as live_settings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if binds_to == "SETTINGS_FIELD":
            instance = getattr(live_settings, "Settings", None)
            if instance is None:
                return UNSET
            try:
                import dataclasses
                names = {f.name for f in dataclasses.fields(instance)}
            except TypeError:
                names = set()
            if setting_id not in names:
                return UNSET
            try:
                return getattr(instance(), setting_id)
            except Exception:
                return UNSET
        if binds_to == "MODULE_GLOBAL":
            if not hasattr(live_settings, setting_id):
                return UNSET
            return getattr(live_settings, setting_id)
    return UNSET


def default_expression(meta: SettingMeta) -> Any:
    """The catalog's default **expression**, evaluated safely when possible.

    A default is never invented. If the expression cannot be evaluated the
    caller receives :data:`UNSET`.
    """
    expr = meta.default_expr
    if not expr:
        return UNSET
    if expr in ("None", "True", "False"):
        return {"None": None, "True": True, "False": False}[expr]
    if re_is_number(expr):
        return float(expr) if "." in expr else int(expr)
    return UNSET


import re  # noqa: E402  (used only by default_expression)


def re_is_number(text: str) -> bool:
    return bool(re.fullmatch(r"-?\d+(\.\d+)?", text.strip()))