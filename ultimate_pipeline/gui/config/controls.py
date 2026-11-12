"""Staged-edit control layer for the settings configurator.

Contract from the GUI spec:

* searchable, categorised controls;
* provenance help on every control;
* a stated reason whenever a control is disabled;
* undo of staged edits;
* **no auto-application** of mutating settings -- staging never writes to the
  live settings module. Applying is a separate, explicitly confirmed step that
  Task 04 will gate behind a session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from ultimate_pipeline.gui.config.metadata import (
    UNSET,
    SettingMeta,
    SettingsRegistry,
    load_registry,
)

__all__ = ["ControlSpec", "StagedEdits", "ConfiguratorModel"]


@dataclass(frozen=True)
class ControlSpec:
    """One configurable control, derived from registry metadata."""

    setting_id: str
    kind: str
    widget: str
    lifecycle: str
    safety_class: str
    enabled: bool
    disabled_reason: str
    provenance: str
    python_type: str | None = None
    default_expr: str | None = None

    @classmethod
    def from_meta(cls, meta: SettingMeta) -> "ControlSpec":
        widget = (meta.gui_widget or "").strip()
        if not widget or widget.upper().startswith("TBD"):
            widget = "UNASSIGNED"
        return cls(
            setting_id=meta.setting_id,
            kind=meta.kind,
            widget=widget,
            lifecycle=meta.lifecycle,
            safety_class=meta.safety_class,
            enabled=meta.is_editable,
            disabled_reason=meta.disabled_reason,
            provenance=meta.provenance_help,
            python_type=meta.python_type,
            default_expr=meta.default_expr,
        )


@dataclass
class StagedEdits:
    """Undoable staging buffer. Applying is NOT part of this object."""

    values: dict[str, Any] = field(default_factory=dict)
    _undo: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def stage(self, setting_id: str, value: Any) -> None:
        # ``None`` is a legitimate staged value, so absence must be tracked with
        # a sentinel rather than with ``dict.get`` -- otherwise undo of a first
        # edit writes ``None`` instead of removing the key.
        self._undo.append({setting_id: self.values.get(setting_id, _MISSING)})
        self.values[setting_id] = value

    def undo(self) -> tuple[str, ...]:
        """Undo the most recent staged edit. Returns the affected ids."""
        if not self._undo:
            return ()
        last = self._undo.pop()
        affected: list[str] = []
        for setting_id, previous in last.items():
            if previous is _MISSING:
                self.values.pop(setting_id, None)
            else:
                self.values[setting_id] = previous
            affected.append(setting_id)
        return tuple(affected)

    @property
    def depth(self) -> int:
        return len(self._undo)

    def clear(self) -> None:
        self.values.clear()
        self._undo.clear()


class _Missing:
    __repr__ = lambda self: "<missing>"  # noqa: E731


_MISSING = _Missing()


class ConfiguratorModel:
    """Searchable, categorised view over the registry plus staged edits."""

    def __init__(self, registry: SettingsRegistry | None = None) -> None:
        self.registry = registry or load_registry()
        self.staged = StagedEdits()

    # -- catalogue ---------------------------------------------------------
    def controls(self) -> list[ControlSpec]:
        """Every declaration site, INCLUDING non-editable ones.

        The GUI spec requires a *disabled explanation* on a disabled control, so
        a non-writable setting must still appear in the catalogue rather than
        vanishing from the UI.
        """
        return [ControlSpec.from_meta(meta) for meta in self.registry]

    def categories(self) -> dict[str, list[ControlSpec]]:
        grouped: dict[str, list[ControlSpec]] = {}
        for control in self.controls():
            grouped.setdefault(control.kind, []).append(control)
        return {k: grouped[k] for k in sorted(grouped)}

    def search(self, needle: str) -> list[ControlSpec]:
        needle = (needle or "").strip().lower()
        if not needle:
            return []
        return [c for c in self.controls() if needle in c.setting_id.lower()]

    def disabled_controls(self) -> list[ControlSpec]:
        return [c for c in self.controls() if not c.enabled]

    def unassignable_widgets(self) -> list[str]:
        """Controls with no assigned widget: real UI work still outstanding."""
        return [c.setting_id for c in self.controls() if c.widget == "UNASSIGNED"]

    def irreversible(self) -> list[str]:
        return [c.setting_id for c in self.controls() if c.safety_class == "IRREVERSIBLE"]

    def secrets(self) -> list[str]:
        return [c.setting_id for c in self.controls() if c.safety_class == "SECRET"]

    # -- staging -----------------------------------------------------------
    def stage(self, setting_id: str, value: Any) -> ControlSpec:
        """Stage an edit. Does **not** apply it. Disabled ids are refused."""
        control = next((c for c in self.controls() if c.setting_id == setting_id), None)
        if control is None:
            raise KeyError(f"{setting_id} is not an editable setting")
        if not control.enabled:
            raise PermissionError(control.disabled_reason)
        self.staged.stage(setting_id, value)
        return control

    def undo(self) -> tuple[str, ...]:
        return self.staged.undo()

    def staged_values(self) -> dict[str, Any]:
        return dict(self.staged.values)

    def __iter__(self) -> Iterator[ControlSpec]:
        return iter(self.controls())